import { useState, useEffect } from 'react'
import { useDashboard } from './hooks/useDashboard'
import PowerNow from './components/PowerNow'
import StackedTimeline from './components/StackedTimeline'
import EnergySummary from './components/EnergySummary'
import AlwaysOnCard from './components/AlwaysOnCard'
import BillProjectionCard from './components/BillProjection'
import UsageTrends from './components/UsageTrends'
import CostBreakdown from './components/CostBreakdown'
import WeeklyDigest from './components/WeeklyDigest'
import EfficiencyScore from './components/EfficiencyScore'
import SolarAnalysis from './components/SolarAnalysis'
import LearnedDevices from './components/LearnedDevices'
import AnnualForecast from './components/AnnualForecast'
import Circuits from './pages/Circuits'
import CircuitDetail from './pages/CircuitDetail'
import DeviceDetail from './pages/DeviceDetail'
import Settings from './pages/Settings'
import DateRangePicker from './components/DateRangePicker'
import type { DateRange } from './lib/api'

type Page = 'dashboard' | 'circuits' | 'settings' | 'detail' | 'device_detail'

const PERIOD_LABELS: Record<DateRange, string> = {
  today: 'Today',
  yesterday: 'Yesterday',
  '7d': 'Last 7 Days',
  '30d': 'Last 30 Days',
  month: 'This Month',
  year: 'This Year',
  '365d': 'Last 365 Days',
}

const TOU_PERIOD_LABELS: Record<string, string> = {
  peak: 'Peak',
  off_peak: 'Off-Peak',
  mid_peak: 'Mid-Peak',
  flat: 'Flat',
}

function formatPower(w: number): string {
  return w >= 1000 ? `${(w / 1000).toFixed(1)} kW` : `${Math.round(w)} W`
}

function NavLink({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-sm rounded-lg transition-colors whitespace-nowrap ${
        active
          ? 'bg-gray-800 text-white'
          : 'text-gray-500 hover:text-gray-300'
      }`}
    >
      {children}
    </button>
  )
}

function LastUpdated({ date }: { date: Date | null }) {
  const [, setTick] = useState(0)

  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 5000)
    return () => clearInterval(interval)
  }, [])

  if (!date) return null

  const seconds = Math.round((Date.now() - date.getTime()) / 1000)
  let label: string
  if (seconds < 5) label = 'Just now'
  else if (seconds < 60) label = `${seconds}s ago`
  else label = `${Math.floor(seconds / 60)}m ago`

  return (
    <span className="text-[10px] sm:text-xs text-gray-600">
      Updated {label}
    </span>
  )
}

function TOUBadge({ periodName, rate }: { periodName: string; rate: number }) {
  const label = TOU_PERIOD_LABELS[periodName] || periodName
  const colorClasses =
    periodName === 'peak'
      ? 'bg-red-900/40 border-red-800/50 text-red-300'
      : periodName === 'off_peak'
        ? 'bg-green-900/40 border-green-800/50 text-green-300'
        : periodName === 'mid_peak'
          ? 'bg-yellow-900/40 border-yellow-800/50 text-yellow-300'
          : 'bg-gray-800/40 border-gray-700/50 text-gray-300'

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-[10px] sm:text-xs font-medium rounded-full border ${colorClasses}`}>
      {label}: ${rate.toFixed(2)}/kWh
    </span>
  )
}

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [selectedCircuit, setSelectedCircuit] = useState<string | null>(null)
  const [selectedDevice, setSelectedDevice] = useState<{ equipmentId: string; clusterId: number } | null>(null)
  const [dateRange, setDateRange] = useState<DateRange>('today')
  const { data: dashboard, loading, error, refresh, lastUpdated } = useDashboard(dateRange)


  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="border-b border-gray-800 px-3 sm:px-6 py-3 sm:py-4">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 sm:gap-0">
          <div className="flex items-center gap-2 sm:gap-4 w-full sm:w-auto">
            <div
              className="flex items-center gap-2 sm:gap-3 cursor-pointer flex-shrink-0"
              onClick={() => setPage('dashboard')}
            >
              <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-lg bg-blue-600 flex items-center justify-center text-xs sm:text-sm font-bold">
                S
              </div>
              <h1 className="text-base sm:text-lg font-semibold">SpanNILM</h1>
            </div>
            <nav className="flex items-center gap-1 ml-2 sm:ml-4 overflow-x-auto">
              <NavLink active={page === 'dashboard'} onClick={() => setPage('dashboard')}>
                Dashboard
              </NavLink>
              <NavLink active={page === 'circuits'} onClick={() => setPage('circuits')}>
                Circuits
              </NavLink>
              <NavLink active={page === 'settings'} onClick={() => setPage('settings')}>
                Settings
              </NavLink>
            </nav>
          </div>
          {dashboard && page === 'dashboard' && (
            <div className="text-left sm:text-right flex sm:block items-center gap-3 sm:gap-0">
              <div className="text-2xl sm:text-3xl font-mono font-bold">
                {formatPower(dashboard.total_power_w)}
              </div>
              <div className="flex flex-col sm:items-end">
                <div className="text-[10px] sm:text-xs text-gray-500">
                  {formatPower(dashboard.active_power_w)} active &middot; {formatPower(dashboard.always_on_w)} always on
                </div>
                <div className="flex items-center gap-2">
                  {dashboard.current_tou_rate != null && dashboard.current_tou_period_name && (
                    <TOUBadge periodName={dashboard.current_tou_period_name} rate={dashboard.current_tou_rate} />
                  )}
                  <LastUpdated date={lastUpdated} />
                </div>
              </div>
            </div>
          )}
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-3 sm:px-6 py-4 sm:py-6 space-y-4 sm:space-y-6">
        {page === 'circuits' && <Circuits />}
        {page === 'settings' && <Settings />}
        {page === 'detail' && selectedCircuit && (
          <CircuitDetail
            equipmentId={selectedCircuit}
            onBack={() => { setPage('dashboard'); setSelectedCircuit(null) }}
          />
        )}
        {page === 'device_detail' && selectedDevice && (
          <DeviceDetail
            equipmentId={selectedDevice.equipmentId}
            clusterId={selectedDevice.clusterId}
            onBack={() => { setPage('dashboard'); setSelectedDevice(null) }}
          />
        )}

        {page === 'dashboard' && (
          <>
            {/* Date Range Picker — at the top */}
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <DateRangePicker value={dateRange} onChange={setDateRange} />
            </div>

            {loading && (
              <div className="flex items-center justify-center py-20">
                <div className="flex items-center gap-3 text-gray-400">
                  <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                    <circle
                      className="opacity-25"
                      cx="12" cy="12" r="10"
                      stroke="currentColor" strokeWidth="4" fill="none"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                  <span>Loading dashboard...</span>
                </div>
              </div>
            )}

            {error && (
              <div className="bg-red-900/30 border border-red-800 rounded-xl p-4 text-red-300">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">Dashboard failed</p>
                    <p className="text-sm mt-1">{error}</p>
                  </div>
                  <button
                    onClick={refresh}
                    className="px-3 py-1.5 text-xs rounded-lg bg-red-800 hover:bg-red-700 transition-colors"
                  >
                    Retry
                  </button>
                </div>
              </div>
            )}

            {dashboard && (
              <>
                {/* ═══════════════════════════════════════════
                    SECTION 1: OVERVIEW (top of page)
                    Timeline, bill, trends, energy, costs
                    All respond to the date range picker
                    ═══════════════════════════════════════════ */}

                {/* Stacked timeline */}
                <section>
                  <h2 className="text-sm font-medium text-gray-400 mb-2">
                    Power Timeline — {PERIOD_LABELS[dateRange]}
                  </h2>
                  <StackedTimeline
                    timeline={dashboard.timeline}
                    alwaysOnW={dashboard.always_on_w}
                  />
                </section>

                {/* Bill projection + Usage trends */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">
                  {dashboard.bill_projection && (
                    <BillProjectionCard
                      projection={dashboard.bill_projection}
                      costDrivers={dashboard.top_cost_drivers}
                    />
                  )}
                  {dashboard.trends.length > 0 && (
                    <UsageTrends trends={dashboard.trends} />
                  )}
                </div>

                {/* Energy summary */}
                <section>
                  <h2 className="text-sm font-medium text-gray-400 mb-2">
                    Energy Usage — {PERIOD_LABELS[dateRange]}
                  </h2>
                  <EnergySummary
                    circuits={dashboard.circuits}
                    totalEnergyToday={dashboard.total_energy_today_kwh}
                    totalCostToday={dashboard.total_cost_today}
                    totalEnergyMonth={dashboard.total_energy_month_kwh}
                    totalCostMonth={dashboard.total_cost_month}
                    dateRange={dateRange}
                  />
                  {dashboard.top_cost_drivers.length > 0 && (
                    <div className="mt-4">
                      <CostBreakdown
                        costDrivers={dashboard.top_cost_drivers}
                        circuits={dashboard.circuits}
                      />
                    </div>
                  )}
                </section>

                {/* Always On + Efficiency + Weekly */}
                <section>
                  <h2 className="text-sm font-medium text-gray-400 mb-2">
                    Always-On Loads
                  </h2>
                  <AlwaysOnCard
                    alwaysOnW={dashboard.always_on_w}
                    totalPowerW={dashboard.total_power_w}
                    totalEnergyTodayKwh={dashboard.total_energy_today_kwh}
                    circuits={dashboard.circuits}
                    electricityRate={dashboard.electricity_rate}
                  />
                </section>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">
                  <EfficiencyScore data={dashboard} />
                  <WeeklyDigest data={dashboard} />
                </div>

                {/* ═══════════════════════════════════════════
                    SECTION 2: CIRCUITS & DEVICES
                    ═══════════════════════════════════════════ */}

                <div className="border-t border-gray-800 pt-6 mt-2">
                  <h2 className="text-base font-semibold text-gray-300 mb-4">Circuits & Devices</h2>
                </div>

                {/* Power Now — per-circuit breakdown */}
                <section>
                  <h2 className="text-sm font-medium text-gray-400 mb-2">
                    Power Now
                  </h2>
                  <PowerNow
                    circuits={dashboard.circuits}
                    onCircuitClick={(id) => { setSelectedCircuit(id); setPage('detail') }}
                    onDeviceClick={(eid, cid) => { setSelectedDevice({ equipmentId: eid, clusterId: cid }); setPage('device_detail') }}
                  />
                </section>

                {/* Learned Devices — high confidence detections needing review */}
                <LearnedDevices circuits={dashboard.circuits} />

                {/* ═══════════════════════════════════════════
                    SECTION 3: SOLAR & FORECAST
                    Solar readiness, annual forecast
                    ═══════════════════════════════════════════ */}

                <div className="border-t border-gray-800 pt-6 mt-2">
                  <h2 className="text-base font-semibold text-gray-300 mb-4">Solar & Energy Forecast</h2>
                </div>

                <section>
                  <h2 className="text-sm font-medium text-gray-400 mb-2">
                    Solar Readiness
                  </h2>
                  <SolarAnalysis data={dashboard} />
                </section>

                <section>
                  <h2 className="text-sm font-medium text-gray-400 mb-2">
                    Annual Energy Forecast
                  </h2>
                  <AnnualForecast />
                </section>

              </>
            )}
          </>
        )}
      </main>
    </div>
  )
}
