"""Annual energy forecast endpoint.

Builds a 12-month forecast using:
- Historical consumption from span_circuit_aggregations
- Outdoor temperature correlation (degree-day regression)
- Solar offset from user's solar quote settings
"""

import calendar
import logging
import os

import psycopg2
import psycopg2.extras
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("span_nilm.api.forecast")
router = APIRouter(prefix="/api")

# Average monthly temps (deg F) for Boston / North Shore MA
NE_AVG_TEMPS = [29, 31, 39, 49, 59, 68, 74, 72, 64, 54, 44, 33]

# Monthly solar production fractions (sum ~1.0)
MONTHLY_SOLAR_FACTORS = [
    0.055, 0.065, 0.085, 0.095, 0.105, 0.115,
    0.115, 0.105, 0.090, 0.075, 0.055, 0.045,
]

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _tempiq_db():
    return psycopg2.connect(os.environ["TEMPIQ_DATABASE_URL"])


def _spannilm_db():
    return psycopg2.connect(os.environ["SPANNILM_DATABASE_URL"])


def _get_property_id() -> str:
    return os.environ["TEMPIQ_PROPERTY_ID"]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MonthlyForecast(BaseModel):
    month: int
    month_name: str
    usage_kwh: float
    is_actual: bool
    avg_temp_f: float
    cost_without_solar: float
    solar_production_kwh: float
    cost_with_solar: float
    savings: float
    method: str  # 'actual', 'scaled_partial', 'degree_day_regression', 'average_fallback'
    data_days: int  # how many days of actual data this month has
    hdd: float  # heating degree days
    cdd: float  # cooling degree days
    prior_year_kwh: float | None = None  # last year's actual usage for this month


class AnnualForecastResponse(BaseModel):
    months: list[MonthlyForecast]
    annual_usage_kwh: float
    annual_cost_without_solar: float
    annual_cost_with_solar: float
    annual_savings: float
    solar_monthly_payment: float
    has_solar_quote: bool
    methodology: str  # explanation of how the forecast was built
    data_months: int  # how many months have actual data
    regression_formula: str | None  # the regression formula if used


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hdd(temp_f: float) -> float:
    """Heating degree days from monthly avg temp."""
    return max(0.0, 65.0 - temp_f)


def _cdd(temp_f: float) -> float:
    """Cooling degree days from monthly avg temp."""
    return max(0.0, temp_f - 65.0)


def _get_historical_monthly(property_id: str) -> tuple[dict[int, dict], dict[int, float]]:
    """Return (current_data, prior_year_data) from span_circuit_aggregations.

    Data spans Nov 2025 - Mar 2026. We treat:
    - "Current": the most recent occurrence of each month (for the forward-looking year)
    - "Prior year": any earlier occurrence of the same month

    For months where we have data from two different years (e.g., if we had Nov 2024 + Nov 2025),
    the newer one is "current" and the older is "prior year."

    Since we only have ~5 months of data starting Nov 2025, ALL months with data are "current"
    and none have prior year data yet. But as data accumulates past 12 months, prior year
    comparisons will appear automatically.
    """
    from datetime import datetime
    now = datetime.now()
    current_year = now.year
    current_month = now.month

    conn = _tempiq_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    EXTRACT(YEAR FROM bucket_start)::int AS year,
                    EXTRACT(MONTH FROM bucket_start)::int AS month,
                    SUM(energy_wh::float) / 1000.0 AS total_kwh,
                    MIN(bucket_start) AS first_bucket,
                    MAX(bucket_start) AS last_bucket,
                    COUNT(DISTINCT DATE(bucket_start)) AS data_days
                FROM span_circuit_aggregations
                WHERE property_id = %s
                  AND energy_wh IS NOT NULL
                GROUP BY EXTRACT(YEAR FROM bucket_start), EXTRACT(MONTH FROM bucket_start)
                ORDER BY year, month
                """,
                (property_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    # Collect all year-month entries
    all_entries: dict[tuple[int, int], dict] = {}  # (year, month) -> data
    for row in rows:
        year = int(row["year"])
        month = int(row["month"])
        kwh = float(row["total_kwh"])
        raw_kwh = kwh
        data_days = int(row["data_days"])
        first = row["first_bucket"]
        last = row["last_bucket"]
        is_partial = False

        if first and last:
            days_span = max((last - first).total_seconds() / 86400.0, 1.0)
            days_in_month = calendar.monthrange(first.year, month)[1]
            if days_span < days_in_month * 0.8:
                kwh = kwh * (days_in_month / days_span)
                is_partial = True

        all_entries[(year, month)] = {
            "kwh": kwh,
            "raw_kwh": raw_kwh,
            "data_days": data_days,
            "is_partial": is_partial,
            "year": year,
        }

    # For each month, find "current" (most recent) and "prior year" (one year earlier)
    result: dict[int, dict] = {}
    prior_year: dict[int, float] = {}

    for month in range(1, 13):
        # Find all years that have data for this month
        years_with_data = sorted([y for (y, m) in all_entries if m == month], reverse=True)

        if not years_with_data:
            continue

        # Most recent = current
        newest_year = years_with_data[0]
        entry = all_entries[(newest_year, month)]
        result[month] = {
            "kwh": entry["kwh"],
            "raw_kwh": entry["raw_kwh"],
            "data_days": entry["data_days"],
            "is_partial": entry["is_partial"],
            "_year": newest_year,
        }

        # If there's an older year, that's prior year
        if len(years_with_data) > 1:
            older_year = years_with_data[1]
            prior_year[month] = all_entries[(older_year, month)]["kwh"]

    return result, prior_year


def _get_settings() -> dict[str, str]:
    """Load settings from SpanNILM DB."""
    conn = _spannilm_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT key, value FROM settings")
            return {row["key"]: row["value"] for row in cur.fetchall()}
    finally:
        conn.close()


def _build_forecast(
    historical: dict[int, dict],
    prior_year: dict[int, float],
    temps: list[float],
    rate: float,
    solar_annual_kwh: float,
    solar_monthly_payment: float,
    net_metering: bool,
) -> tuple[list[MonthlyForecast], str, str | None]:
    """Build 12-month forecast using degree-day regression.

    Returns (forecasts, methodology_text, regression_formula).
    """

    # Pair actual months with their degree days
    actual_months = []
    for m, info in historical.items():
        t = temps[m - 1]
        actual_months.append((m, info["kwh"], _hdd(t), _cdd(t), t, info))

    regression_formula = None
    methodology = ""

    # Fit regression: kwh = a*HDD + b*CDD + c
    if len(actual_months) >= 3:
        import numpy as np

        X = []
        y = []
        for _, kwh, hdd, cdd, _, _ in actual_months:
            X.append([hdd, cdd, 1.0])
            y.append(kwh)
        X_arr = np.array(X)
        y_arr = np.array(y)

        result = np.linalg.lstsq(X_arr, y_arr, rcond=None)
        coeffs = result[0]
        a_hdd, b_cdd, c_base = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])

        if c_base < 0:
            c_base = 0.0
        if a_hdd < 0:
            a_hdd = 0.0
        if b_cdd < 0:
            b_cdd = 0.0

        regression_formula = f"kWh = {a_hdd:.1f} × HDD + {b_cdd:.1f} × CDD + {c_base:.0f}"

        # Compute trend adjustment: how much do actuals deviate from the model?
        # If recent months are consistently higher/lower than predicted, adjust future months
        residuals = []
        for m, kwh, hdd, cdd, _, _ in actual_months:
            predicted = a_hdd * hdd + b_cdd * cdd + c_base
            if predicted > 0:
                residuals.append(kwh / predicted)
        trend_factor = float(np.median(residuals)) if residuals else 1.0
        # Clamp to reasonable range (0.7 - 1.3)
        trend_factor = max(0.7, min(1.3, trend_factor))

        def predict(month: int) -> float:
            t = temps[month - 1]
            est = a_hdd * _hdd(t) + b_cdd * _cdd(t) + c_base
            est = est * trend_factor  # Apply trend adjustment
            return max(est, c_base * 0.5)

        trend_pct = (trend_factor - 1.0) * 100
        trend_str = f" Trend adjustment: {trend_pct:+.0f}% applied to projections based on recent actual vs predicted." if abs(trend_pct) > 2 else ""

        actual_month_names = [MONTH_NAMES[m - 1] for m, _, _, _, _, _ in actual_months]
        methodology = (
            f"Forecast uses {len(actual_months)} months of actual data "
            f"({', '.join(actual_month_names)}) to fit a degree-day regression model. "
            f"Formula: {regression_formula}. "
            f"HDD = heating degree days (base 65°F), CDD = cooling degree days. "
            f"Months without data are projected using this formula with average "
            f"New England temperatures, adjusted for recent consumption trends.{trend_str} "
            f"Partial months are scaled proportionally."
        )
    else:
        total_kwh = sum(info["kwh"] for _, info in historical.items())
        avg_kwh = total_kwh / max(len(actual_months), 1)

        def predict(month: int) -> float:
            return avg_kwh

        methodology = (
            f"Only {len(actual_months)} months of data available — using simple average "
            f"({avg_kwh:.0f} kWh/month) for projected months. More data will improve accuracy."
        )

    forecasts: list[MonthlyForecast] = []
    for m in range(1, 13):
        hist_info = historical.get(m)
        is_actual = hist_info is not None
        hdd_val = _hdd(temps[m - 1])
        cdd_val = _cdd(temps[m - 1])

        if is_actual:
            usage_kwh = hist_info["kwh"]
            data_days = hist_info["data_days"]
            if hist_info["is_partial"]:
                method = "scaled_partial"
            else:
                method = "actual"
        else:
            usage_kwh = predict(m)
            data_days = 0
            method = "degree_day_regression" if regression_formula else "average_fallback"

        usage_kwh = max(usage_kwh, 0.0)
        avg_temp = temps[m - 1]
        cost_no_solar = usage_kwh * rate

        solar_kwh = solar_annual_kwh * MONTHLY_SOLAR_FACTORS[m - 1] if solar_annual_kwh > 0 else 0.0

        if solar_annual_kwh > 0:
            if net_metering:
                net_grid = max(0.0, usage_kwh - solar_kwh)
                cost_w_solar = net_grid * rate + solar_monthly_payment
            else:
                usable = min(solar_kwh, usage_kwh * 0.5)
                net_grid = usage_kwh - usable
                cost_w_solar = net_grid * rate + solar_monthly_payment
        else:
            cost_w_solar = cost_no_solar

        savings = cost_no_solar - cost_w_solar

        forecasts.append(MonthlyForecast(
            month=m,
            month_name=MONTH_NAMES[m - 1],
            usage_kwh=round(usage_kwh, 1),
            is_actual=is_actual,
            avg_temp_f=avg_temp,
            cost_without_solar=round(cost_no_solar, 2),
            solar_production_kwh=round(solar_kwh, 1),
            cost_with_solar=round(cost_w_solar, 2),
            savings=round(savings, 2),
            method=method,
            data_days=data_days,
            hdd=round(hdd_val, 1),
            cdd=round(cdd_val, 1),
            prior_year_kwh=round(prior_year.get(m, 0), 1) if prior_year.get(m) else None,
        ))

    return forecasts, methodology, regression_formula


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/forecast")
def get_forecast() -> AnnualForecastResponse:
    """Return a 12-month energy forecast with solar offset analysis."""
    property_id = _get_property_id()

    # Step 1: historical monthly energy
    historical, prior_year = _get_historical_monthly(property_id)
    logger.info("Historical data for months: %s, prior year: %s", sorted(historical.keys()), sorted(prior_year.keys()))

    # Step 2: temperatures — use New England averages
    temps = [float(t) for t in NE_AVG_TEMPS]

    # Step 3: load settings
    settings = _get_settings()
    rate = float(settings.get("electricity_rate", "0.14"))
    solar_annual_kwh = float(settings.get("solar_annual_kwh", "0"))
    solar_monthly_payment = float(settings.get("solar_monthly_payment", "0"))
    net_metering = settings.get("net_metering", "yes") != "no"
    has_solar_quote = solar_annual_kwh > 0 and solar_monthly_payment > 0

    # Step 4: build forecast
    months, methodology, regression_formula = _build_forecast(
        historical, prior_year, temps, rate,
        solar_annual_kwh, solar_monthly_payment, net_metering,
    )

    annual_usage = sum(m.usage_kwh for m in months)
    annual_no_solar = sum(m.cost_without_solar for m in months)
    annual_w_solar = sum(m.cost_with_solar for m in months)
    annual_savings = annual_no_solar - annual_w_solar

    return AnnualForecastResponse(
        months=months,
        annual_usage_kwh=round(annual_usage, 1),
        annual_cost_without_solar=round(annual_no_solar, 2),
        annual_cost_with_solar=round(annual_w_solar, 2),
        annual_savings=round(annual_savings, 2),
        solar_monthly_payment=solar_monthly_payment,
        has_solar_quote=has_solar_quote,
        methodology=methodology,
        data_months=len(historical),
        regression_formula=regression_formula,
    )
