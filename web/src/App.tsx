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
import Anomalies from './components/Anomalies'
import AnnualForecast from './components/AnnualForecast'
import Circuits from './pages/Circuits'
import CircuitDetail from './pages/CircuitDetail'
import DeviceDetail from './pages/DeviceDetail'
import Categories from './pages/Categories'
import Settings from './pages/Settings'
import DateRangePicker from './components/DateRangePicker'
import type { DateRange } from './lib/api'

type Page = 'dashboard' | 'circuits' | 'categories' | 'settings' | 'detail' | 'device_detail'

const PERIOD_LABELS: Record<DateRange, string> = {
  today: 'Today',
  '24h': 'Last 24 Hours',
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
          ? 'bg-gray-200 text-gray-900 dark:bg-gray-800 dark:text-white'
          : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
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
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (localStorage.getItem('theme') as 'dark' | 'light') || 'dark'
  )

  useEffect(() => {
    localStorage.setItem('theme', theme)
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }, [theme])

  return (
    <div className="min-h-screen bg-white text-gray-900 dark:bg-gray-950 dark:text-white">
      <header className="border-b border-gray-200 dark:border-gray-800 px-3 sm:px-6 py-3 sm:py-4">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 sm:gap-0">
          <div className="flex items-center gap-2 sm:gap-4 w-full sm:w-auto">
            <div
              className="flex items-center gap-2 sm:gap-3 cursor-pointer flex-shrink-0"
              onClick={() => setPage('dashboard')}
            >
              <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-lg bg-blue-600 flex items-center justify-center text-xs sm:text-sm font-bold text-white">
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
              <NavLink active={page === 'categories'} onClick={() => setPage('categories')}>
                Categories
              </NavLink>
              <NavLink active={page === 'settings'} onClick={() => setPage('settings')}>
                Settings
              </NavLink>
            </nav>
            <button
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              className="ml-auto sm:ml-2 p-1.5 rounded-lg text-gray-500 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {theme === 'dark' ? (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
                </svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
                </svg>
              )}
            </button>
          </div>
          {dashboard && page === 'dashboard' && (
            <div className="text-left sm:text-right flex sm:block items-center gap-3 sm:gap-0">
              <div className="text-2xl sm:text-3xl font-mono font-bold">
                ${dashboard.total_cost_today.toFixed(2)} <span className="text-sm font-normal text-gray-500">today</span>
              </div>
              <div className="flex flex-col sm:items-end">
                <div className="text-[10px] sm:text-xs text-gray-500">
                  {dashboard.total_energy_today_kwh.toFixed(1)} kWh &middot; {formatPower(dashboard.total_power_w)} now
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
        {page === 'categories' && dashboard && <Categories data={dashboard} dateRange={dateRange} onDateRangeChange={setDateRange} />}
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

            {loading && !dashboard && (
              <div className="space-y-4 sm:space-y-6 animate-pulse">
                {/* Skeleton: timeline */}
                <div className="h-56 sm:h-72 rounded-xl bg-gray-100 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800" />
                {/* Skeleton: bill + trends */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="h-48 rounded-xl bg-gray-100 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800" />
                  <div className="h-48 rounded-xl bg-gray-100 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800" />
                </div>
                {/* Skeleton: energy */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="h-24 rounded-xl bg-gray-100 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800" />
                  <div className="h-24 rounded-xl bg-gray-100 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800" />
                </div>
                {/* Skeleton: circuits */}
                <div className="space-y-2">
                  {[1,2,3,4,5].map(i => (
                    <div key={i} className="h-14 rounded-lg bg-gray-100 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-800/50" />
                  ))}
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

                {/* Anomalies */}
                {dashboard.anomalies && dashboard.anomalies.length > 0 && (
                  <Anomalies anomalies={dashboard.anomalies} />
                )}

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

                <div className="border-t border-gray-200 dark:border-gray-800 pt-6 mt-2">
                  <h2 className="text-base font-semibold text-gray-700 dark:text-gray-300 mb-4">Circuits & Devices</h2>
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

                <div className="border-t border-gray-200 dark:border-gray-800 pt-6 mt-2">
                  <h2 className="text-base font-semibold text-gray-700 dark:text-gray-300 mb-4">Solar & Energy Forecast</h2>
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
