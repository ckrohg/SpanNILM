const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export interface DeviceCluster {
  cluster_id: number
  circuit_id: string
  circuit_name: string
  label: string | null
  mean_power_w: number
  std_power_w: number
  mean_duration_s: number | null
  observation_count: number
  matches: SignatureMatch[]
  is_on: boolean
  current_power_w: number
}

export interface SignatureMatch {
  device_name: string
  confidence: number
  category: string
}

export interface PowerEvent {
  timestamp: string
  circuit_id: string
  circuit_name: string
  power_before_w: number
  power_after_w: number
  delta_w: number
  event_type: 'on' | 'off'
}

export interface AnalysisResponse {
  total_readings: number
  date_range: string[] | null
  total_events: number
  total_runs: number
  devices: DeviceCluster[]
  events: PowerEvent[]
  total_power_w: number
}

export interface PowerPoint {
  timestamp: string
  power_w: number
}

export interface CircuitInfo {
  equipment_id: string
  name: string
  circuit_number: string | null
}

export async function runAnalysis(hoursBack = 24): Promise<AnalysisResponse> {
  const res = await fetch(`${API_URL}/api/analyze?hours_back=${hoursBack}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(`Analysis failed: ${res.status}`)
  return res.json()
}

export async function getCircuits(): Promise<CircuitInfo[]> {
  const res = await fetch(`${API_URL}/api/circuits`)
  if (!res.ok) throw new Error(`Failed to fetch circuits: ${res.status}`)
  return res.json()
}

export interface CircuitConfig {
  equipment_id: string
  name: string
  circuit_number: string | null
  user_label: string | null
  is_dedicated: boolean
  dedicated_device_type: string | null
}

export interface CircuitConfigUpdate {
  user_label?: string | null
  is_dedicated: boolean
  dedicated_device_type?: string | null
}

export async function getCircuitConfigs(): Promise<CircuitConfig[]> {
  const res = await fetch(`${API_URL}/api/circuits/config`)
  if (!res.ok) throw new Error(`Failed to fetch circuit configs: ${res.status}`)
  return res.json()
}

export async function updateCircuitConfig(
  equipmentId: string,
  update: CircuitConfigUpdate
): Promise<CircuitConfig> {
  const res = await fetch(`${API_URL}/api/circuits/${equipmentId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(update),
  })
  if (!res.ok) throw new Error(`Failed to update circuit: ${res.status}`)
  return res.json()
}

export async function getPowerTimeseries(
  equipmentId: string,
  hoursBack = 24
): Promise<{ circuit_id: string; points: PowerPoint[] }> {
  const res = await fetch(
    `${API_URL}/api/power/${equipmentId}?hours_back=${hoursBack}`
  )
  if (!res.ok) throw new Error(`Failed to fetch power: ${res.status}`)
  return res.json()
}

// Dashboard types and API

export interface DetectedDevice {
  name: string
  power_w: number
  confidence: number
  pct_of_time: number
  template_curve: number[] | null
  session_count: number
  avg_duration_min: number
  is_cycling: boolean
  num_phases: number
  energy_per_session_wh: number
  suppressed_on_other_circuit: boolean
  user_confirmed: boolean
}

export interface TemporalInfo {
  total_sessions: number
  total_hours_on: number
  duty_cycle: number
  has_cycling: boolean
  cycle_period_min: number | null
  cycle_on_min: number | null
  cycle_regularity: number | null
  peak_hours: number[]
}

export interface CorrelationInfo {
  name: string
  score: number
}

export interface CircuitPower {
  equipment_id: string
  name: string
  power_w: number
  is_dedicated: boolean
  device_type: string | null
  energy_today_kwh: number
  energy_month_kwh: number
  cost_today: number
  cost_month: number
  always_on_w: number
  detected_devices: DetectedDevice[]
  temporal: TemporalInfo | null
  correlations: CorrelationInfo[]
}

export interface TimelineBucket {
  timestamp: string
  total_w: number
  circuits: Record<string, number>
}

export interface BillProjection {
  projected_monthly_kwh: number
  projected_monthly_cost: number
  days_elapsed: number
  days_remaining: number
  daily_avg_kwh: number
}

export interface CostAttribution {
  name: string
  energy_kwh: number
  cost: number
  pct_of_total: number
}

export interface UsageTrend {
  circuit_name: string
  current_period_kwh: number
  previous_period_kwh: number
  change_pct: number
  direction: 'up' | 'down' | 'stable'
}

export interface TOUPeriod {
  start: number
  end: number
  rate: number
  weekdays_only?: boolean
}

export interface TOUSchedule {
  enabled: boolean
  peak?: TOUPeriod | null
  off_peak?: TOUPeriod | null
  mid_peak?: TOUPeriod | null
}

export interface DashboardData {
  total_power_w: number
  always_on_w: number
  active_power_w: number
  circuits: CircuitPower[]
  timeline: TimelineBucket[]
  total_energy_today_kwh: number
  total_cost_today: number
  total_energy_month_kwh: number
  total_cost_month: number
  electricity_rate: number
  bill_projection: BillProjection | null
  top_cost_drivers: CostAttribution[]
  trends: UsageTrend[]
  period: string
  period_label: string
  tou_schedule: TOUSchedule | null
  current_tou_rate: number | null
  current_tou_period_name: string | null
  anomalies: Anomaly[]
}

export interface DailyEnergy {
  date: string
  energy_kwh: number
  cost: number
}

export interface Anomaly {
  circuit_name: string
  anomaly_type: string
  severity: 'info' | 'warning' | 'alert'
  title: string
  description: string
  value: number
  expected: number
  timestamp: string
}

export interface CircuitDetailData {
  equipment_id: string
  name: string
  is_dedicated: boolean
  device_type: string | null
  power_series: PowerPoint[]
  daily_energy: DailyEnergy[]
  devices: DetectedDevice[]
  avg_power_w: number
  peak_power_w: number
  min_power_w: number
  always_on_w: number
  energy_period_kwh: number
  cost_period: number
  anomalies: Anomaly[]
}

export type DateRange = 'today' | 'yesterday' | '7d' | '30d' | 'month' | 'year' | '365d'

export async function fetchDashboard(period: DateRange = 'today'): Promise<DashboardData> {
  const res = await fetch(`${API_URL}/api/dashboard?period=${period}`, { method: 'POST' })
  if (!res.ok) throw new Error(`Dashboard failed: ${res.status}`)
  return res.json()
}

export async function runProfile(days = 30): Promise<{ status: string; profiles_saved: number }> {
  const res = await fetch(`${API_URL}/api/profile?days=${days}`, { method: 'POST' })
  if (!res.ok) throw new Error(`Profile failed: ${res.status}`)
  return res.json()
}

export async function getProfiles(): Promise<{ status: string; profiles: unknown[] }> {
  const res = await fetch(`${API_URL}/api/profile`)
  if (!res.ok) throw new Error(`Failed to fetch profiles: ${res.status}`)
  return res.json()
}

// Settings API

export type Settings = Record<string, string>

export async function getSettings(): Promise<Settings> {
  const res = await fetch(`${API_URL}/api/settings`)
  if (!res.ok) throw new Error(`Failed to fetch settings: ${res.status}`)
  return res.json()
}

export async function updateSettings(updates: Settings): Promise<Settings> {
  const res = await fetch(`${API_URL}/api/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new Error(`Failed to update settings: ${res.status}`)
  return res.json()
}

export async function fetchCircuitDetail(
  equipmentId: string,
  days = 7
): Promise<CircuitDetailData> {
  const res = await fetch(
    `${API_URL}/api/circuit/${equipmentId}/detail?days=${days}`
  )
  if (!res.ok) throw new Error(`Circuit detail failed: ${res.status}`)
  return res.json()
}

// Device naming API

export interface DeviceSuggestion {
  name: string
  reasoning: string
}

export async function suggestDeviceNames(
  equipmentId: string,
  clusterId: number
): Promise<DeviceSuggestion[]> {
  const res = await fetch(
    `${API_URL}/api/devices/${equipmentId}/${clusterId}/suggest`,
    { method: 'POST' }
  )
  if (!res.ok) throw new Error(`Suggest failed: ${res.status}`)
  const data = await res.json()
  return data.suggestions
}

export async function setDeviceName(
  equipmentId: string,
  clusterId: number,
  name: string
): Promise<void> {
  const res = await fetch(
    `${API_URL}/api/devices/${equipmentId}/${clusterId}/name`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }
  )
  if (!res.ok) throw new Error(`Set name failed: ${res.status}`)
}

// Device detail API

export interface DeviceSession {
  start: string
  end: string
  duration_min: number
  avg_power_w: number
  energy_wh: number
}

export interface DeviceDetailData {
  equipment_id: string
  cluster_id: number
  name: string
  circuit_name: string
  template_curve: number[]
  avg_power_w: number
  peak_power_w: number
  sessions: DeviceSession[]
  total_energy_kwh: number
  total_sessions: number
  avg_sessions_per_day: number
  peak_hours: number[]
}

export async function fetchDeviceDetail(
  equipmentId: string,
  clusterId: number,
  days = 30
): Promise<DeviceDetailData> {
  const res = await fetch(
    `${API_URL}/api/devices/${equipmentId}/${clusterId}/detail?days=${days}`
  )
  if (!res.ok) throw new Error(`Device detail failed: ${res.status}`)
  return res.json()
}

// Forecast types and API

export interface MonthlyForecast {
  month: number
  month_name: string
  usage_kwh: number
  is_actual: boolean
  avg_temp_f: number
  cost_without_solar: number
  solar_production_kwh: number
  cost_with_solar: number
  savings: number
  method: string
  data_days: number
  hdd: number
  cdd: number
  prior_year_kwh: number | null
}

export interface AnnualForecastData {
  months: MonthlyForecast[]
  annual_usage_kwh: number
  annual_cost_without_solar: number
  annual_cost_with_solar: number
  annual_savings: number
  solar_monthly_payment: number
  has_solar_quote: boolean
  methodology: string
  data_months: number
  regression_formula: string | null
}

export async function fetchForecast(): Promise<AnnualForecastData> {
  const res = await fetch(`${API_URL}/api/forecast`)
  if (!res.ok) throw new Error(`Forecast failed: ${res.status}`)
  return res.json()
}
