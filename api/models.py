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
