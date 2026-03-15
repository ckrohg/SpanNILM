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
}

export async function fetchDashboard(): Promise<DashboardData> {
  const res = await fetch(`${API_URL}/api/dashboard`, { method: 'POST' })
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
