"""Pydantic response schemas for the API."""

from pydantic import BaseModel


class CircuitInfo(BaseModel):
    equipment_id: str
    name: str
    circuit_number: str | None = None


class PowerEventOut(BaseModel):
    timestamp: str
    circuit_id: str
    circuit_name: str
    power_before_w: float
    power_after_w: float
    delta_w: float
    event_type: str


class DeviceRunOut(BaseModel):
    circuit_id: str
    circuit_name: str
    on_timestamp: str
    off_timestamp: str | None
    power_draw_w: float
    duration_s: float | None
    energy_wh: float | None


class SignatureMatchOut(BaseModel):
    device_name: str
    confidence: float
    category: str


class DeviceClusterOut(BaseModel):
    cluster_id: int
    circuit_id: str
    circuit_name: str
    label: str | None
    mean_power_w: float
    std_power_w: float
    mean_duration_s: float | None
    observation_count: int
    matches: list[SignatureMatchOut]
    is_on: bool = False
    current_power_w: float = 0.0


class AnalysisResponse(BaseModel):
    total_readings: int
    date_range: list[str] | None
    total_events: int
    total_runs: int
    devices: list[DeviceClusterOut]
    events: list[PowerEventOut]
    total_power_w: float


class CircuitConfig(BaseModel):
    equipment_id: str
    name: str
    circuit_number: str | None = None
    user_label: str | None = None
    is_dedicated: bool = False
    dedicated_device_type: str | None = None


class CircuitConfigUpdate(BaseModel):
    user_label: str | None = None
    is_dedicated: bool = False
    dedicated_device_type: str | None = None


class PowerPoint(BaseModel):
    timestamp: str
    power_w: float


class PowerTimeseriesResponse(BaseModel):
    circuit_id: str
    circuit_name: str | None = None
    points: list[PowerPoint]


class DetectedDevice(BaseModel):
    name: str
    power_w: float
    confidence: float
    pct_of_time: float
    template_curve: list[float] | None = None  # 32-point normalized power shape
    session_count: int = 0
    avg_duration_min: float = 0
    is_cycling: bool = False
    num_phases: int = 1
    energy_per_session_wh: float = 0
    suppressed_on_other_circuit: bool = False  # Same AI name was suppressed elsewhere
    user_confirmed: bool = False  # User confirmed or named this device


class CorrelationInfo(BaseModel):
    name: str
    score: float


class TemporalInfo(BaseModel):
    total_sessions: int = 0
    total_hours_on: float = 0
    duty_cycle: float = 0
    has_cycling: bool = False
    cycle_period_min: float | None = None
    cycle_on_min: float | None = None
    cycle_regularity: float | None = None
    peak_hours: list[int] = []


class CircuitPower(BaseModel):
    equipment_id: str
    name: str
    power_w: float
    is_dedicated: bool
    device_type: str | None = None
    energy_today_kwh: float
    energy_month_kwh: float
    cost_today: float
    cost_month: float
    always_on_w: float
    detected_devices: list[DetectedDevice] = []
    temporal: TemporalInfo | None = None
    correlations: list[CorrelationInfo] = []


class TimelineBucket(BaseModel):
    timestamp: str
    total_w: float
    circuits: dict[str, float]


class BillProjection(BaseModel):
    projected_monthly_kwh: float
    projected_monthly_cost: float
    days_elapsed: int
    days_remaining: int
    daily_avg_kwh: float


class CostAttribution(BaseModel):
    name: str
    energy_kwh: float
    cost: float
    pct_of_total: float


class UsageTrend(BaseModel):
    circuit_name: str
    current_period_kwh: float
    previous_period_kwh: float
    change_pct: float
    direction: str  # up, down, stable


class TOUPeriod(BaseModel):
    start: int  # hour 0-23
    end: int
    rate: float
    weekdays_only: bool = False


class TOUSchedule(BaseModel):
    enabled: bool = False
    peak: TOUPeriod | None = None
    off_peak: TOUPeriod | None = None
    mid_peak: TOUPeriod | None = None


class DailyEnergy(BaseModel):
    date: str
    energy_kwh: float
    cost: float


class Anomaly(BaseModel):
    circuit_name: str = ""
    anomaly_type: str = ""  # 'high_energy', 'extended_run', 'baseline_shift', 'missing_device', 'cost_spike'
    severity: str = "info"  # info, warning, alert
    title: str = ""
    description: str = ""
    value: float = 0.0
    expected: float = 0.0
    timestamp: str = ""


class DashboardResponse(BaseModel):
    total_power_w: float
    always_on_w: float
    active_power_w: float
    circuits: list[CircuitPower]
    timeline: list[TimelineBucket]
    total_energy_today_kwh: float
    total_cost_today: float
    total_energy_month_kwh: float
    total_cost_month: float
    electricity_rate: float
    bill_projection: BillProjection | None = None
    top_cost_drivers: list[CostAttribution] = []
    trends: list[UsageTrend] = []
    period: str = "today"
    period_label: str = "Today"
    tou_schedule: TOUSchedule | None = None
    current_tou_rate: float | None = None
    current_tou_period_name: str | None = None
    anomalies: list[Anomaly] = []


class CircuitDetailResponse(BaseModel):
    equipment_id: str
    name: str
    is_dedicated: bool
    device_type: str | None = None
    power_series: list[PowerPoint]
    daily_energy: list[DailyEnergy]
    devices: list[DetectedDevice] = []
    avg_power_w: float
    peak_power_w: float
    min_power_w: float
    always_on_w: float
    energy_period_kwh: float
    cost_period: float
    anomalies: list[Anomaly] = []


class DeviceSession(BaseModel):
    start: str
    end: str
    duration_min: float
    avg_power_w: float
    energy_wh: float


class DeviceDetailResponse(BaseModel):
    equipment_id: str
    cluster_id: int
    name: str
    circuit_name: str
    template_curve: list[float]
    avg_power_w: float
    peak_power_w: float
    sessions: list[DeviceSession]
    total_energy_kwh: float
    total_sessions: int
    avg_sessions_per_day: float
    peak_hours: list[int]
