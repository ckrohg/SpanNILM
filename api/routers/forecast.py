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


class AnnualForecastResponse(BaseModel):
    months: list[MonthlyForecast]
    annual_usage_kwh: float
    annual_cost_without_solar: float
    annual_cost_with_solar: float
    annual_savings: float
    solar_monthly_payment: float
    has_solar_quote: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hdd(temp_f: float) -> float:
    """Heating degree days from monthly avg temp."""
    return max(0.0, 65.0 - temp_f)


def _cdd(temp_f: float) -> float:
    """Cooling degree days from monthly avg temp."""
    return max(0.0, temp_f - 65.0)


def _get_historical_monthly(property_id: str) -> dict[int, float]:
    """Return {month_number: total_kwh} from span_circuit_aggregations."""
    conn = _tempiq_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    EXTRACT(MONTH FROM bucket_start)::int AS month,
                    SUM(energy_wh::float) / 1000.0 AS total_kwh,
                    MIN(bucket_start) AS first_bucket,
                    MAX(bucket_start) AS last_bucket
                FROM span_circuit_aggregations
                WHERE property_id = %s
                  AND energy_wh IS NOT NULL
                GROUP BY EXTRACT(MONTH FROM bucket_start)
                ORDER BY month
                """,
                (property_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    result: dict[int, float] = {}
    for row in rows:
        month = int(row["month"])
        kwh = float(row["total_kwh"])
        first = row["first_bucket"]
        last = row["last_bucket"]

        # If the month is partial, scale up to full month
        if first and last:
            days_span = max((last - first).total_seconds() / 86400.0, 1.0)
            days_in_month = calendar.monthrange(first.year, month)[1]
            if days_span < days_in_month * 0.8:
                # Partial month — scale up
                kwh = kwh * (days_in_month / days_span)

        result[month] = kwh

    return result


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
    historical: dict[int, float],
    temps: list[float],
    rate: float,
    solar_annual_kwh: float,
    solar_monthly_payment: float,
    net_metering: bool,
) -> list[MonthlyForecast]:
    """Build 12-month forecast using degree-day regression."""

    # Pair actual months with their degree days
    actual_months = []
    for m, kwh in historical.items():
        t = temps[m - 1]
        actual_months.append((m, kwh, _hdd(t), _cdd(t), t))

    # Fit regression: kwh = a*HDD + b*CDD + c
    if len(actual_months) >= 3:
        # Simple least-squares: kwh = a*HDD + b*CDD + c
        import numpy as np

        X = []
        y = []
        for _, kwh, hdd, cdd, _ in actual_months:
            X.append([hdd, cdd, 1.0])
            y.append(kwh)
        X = np.array(X)
        y = np.array(y)

        # Use least squares (may be underdetermined, use lstsq)
        result = np.linalg.lstsq(X, y, rcond=None)
        coeffs = result[0]  # [a, b, c]
        a_hdd, b_cdd, c_base = coeffs[0], coeffs[1], coeffs[2]

        # Ensure non-negative base and coefficients
        if c_base < 0:
            c_base = 0.0
        if a_hdd < 0:
            a_hdd = 0.0
        if b_cdd < 0:
            b_cdd = 0.0

        def predict(month: int) -> float:
            t = temps[month - 1]
            est = a_hdd * _hdd(t) + b_cdd * _cdd(t) + c_base
            return max(est, c_base * 0.5)  # floor at half the base
    else:
        # Not enough data points — use simpler approach
        # Calculate average daily kWh and scale by degree-day ratio
        total_kwh = sum(kwh for _, kwh, _, _, _ in actual_months)
        total_days_equiv = len(actual_months) * 30
        daily_avg = total_kwh / max(total_days_equiv, 1)

        # Use actual average as a simple base
        avg_kwh = total_kwh / max(len(actual_months), 1)

        def predict(month: int) -> float:
            return avg_kwh  # simple fallback

    forecasts: list[MonthlyForecast] = []
    for m in range(1, 13):
        is_actual = m in historical
        usage_kwh = historical[m] if is_actual else predict(m)
        usage_kwh = max(usage_kwh, 0.0)
        avg_temp = temps[m - 1]

        cost_no_solar = usage_kwh * rate

        # Solar production for this month
        solar_kwh = solar_annual_kwh * MONTHLY_SOLAR_FACTORS[m - 1] if solar_annual_kwh > 0 else 0.0

        # Cost with solar
        if solar_annual_kwh > 0:
            if net_metering:
                net_grid = max(0.0, usage_kwh - solar_kwh)
                cost_w_solar = net_grid * rate + solar_monthly_payment
            else:
                # Only offset up to usage during solar hours (~50% of day usage)
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
        ))

    return forecasts


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/forecast")
def get_forecast() -> AnnualForecastResponse:
    """Return a 12-month energy forecast with solar offset analysis."""
    property_id = _get_property_id()

    # Step 1: historical monthly energy
    historical = _get_historical_monthly(property_id)
    logger.info("Historical data for months: %s", sorted(historical.keys()))

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
    months = _build_forecast(
        historical, temps, rate,
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
    )
