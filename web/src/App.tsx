import { useState } from 'react'
import { useDashboard } from './hooks/useDashboard'
import { useAnalysis } from './hooks/useAnalysis'
import PowerNow from './components/PowerNow'
import StackedTimeline from './components/StackedTimeline'
import EnergySummary from './components/EnergySummary'
import AlwaysOnCard from './components/AlwaysOnCard'
import DeviceCard from './components/DeviceCard'
import ActivityFeed from './components/ActivityFeed'
import Circuits from './pages/Circuits'
import Settings from './pages/Settings'

type Page = 'dashboard' | 'circuits' | 'settings'

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
      className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
        active
          ? 'bg-gray-800 text-white'
          : 'text-gray-500 hover:text-gray-300'
      }`}
    >
      {children}
    </button>
  )
}

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const { data: dashboard, loading, error, refresh } = useDashboard()
  const { data: analysis } = useAnalysis(24)

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="border-b border-gray-800 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div
              className="flex items-center gap-3 cursor-pointer"
              onClick={() => setPage('dashboard')}
            >
              <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-sm font-bold">
                S
              </div>
              <h1 className="text-lg font-semibold">SpanNILM</h1>
            </div>
            <nav className="flex items-center gap-1 ml-4">
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
            <div className="text-right">
              <div className="text-3xl font-mono font-bold">
                {formatPower(dashboard.total_power_w)}
              </div>
              <div className="text-xs text-gray-500">
                {formatPower(dashboard.active_power_w)} active &middot; {formatPower(dashboard.always_on_w)} always on
              </div>
            </div>
          )}
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-6 space-y-6">
        {page === 'circuits' && <Circuits />}
        {page === 'settings' && <Settings />}

        {page === 'dashboard' && (
          <>
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
                {/* Always On card */}
                <AlwaysOnCard
                  alwaysOnW={dashboard.always_on_w}
                  totalPowerW={dashboard.total_power_w}
                  totalEnergyTodayKwh={dashboard.total_energy_today_kwh}
                />

                {/* Power Now — where is my power going? */}
                <section>
                  <h2 className="text-sm font-medium text-gray-400 mb-2">
                    Power Now
                  </h2>
                  <PowerNow circuits={dashboard.circuits} />
                </section>

                {/* Stacked timeline */}
                <section>
                  <h2 className="text-sm font-medium text-gray-400 mb-2">
                    Power Timeline (24h)
                  </h2>
                  <StackedTimeline
                    timeline={dashboard.timeline}
                    alwaysOnW={dashboard.always_on_w}
                  />
                </section>

                {/* Energy summary */}
                <section>
                  <h2 className="text-sm font-medium text-gray-400 mb-2">
                    Energy Usage
                  </h2>
                  <EnergySummary
                    circuits={dashboard.circuits}
                    totalEnergyToday={dashboard.total_energy_today_kwh}
                    totalCostToday={dashboard.total_cost_today}
                    totalEnergyMonth={dashboard.total_energy_month_kwh}
                    totalCostMonth={dashboard.total_cost_month}
                  />
                </section>

                {/* Detected devices and activity feed (from analysis) */}
                {analysis && (analysis.devices.length > 0 || analysis.events.length > 0) && (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {analysis.devices.length > 0 && (
                      <section>
                        <h2 className="text-sm font-medium text-gray-400 mb-3">
                          Detected Devices ({analysis.devices.length})
                        </h2>
                        <div className="space-y-3">
                          {analysis.devices
                            .sort((a, b) => {
                              if (a.is_on !== b.is_on) return a.is_on ? -1 : 1
                              return b.mean_power_w - a.mean_power_w
                            })
                            .map((device) => (
                              <DeviceCard key={`${device.circuit_id}-${device.cluster_id}`} device={device} />
                            ))}
                        </div>
                      </section>
                    )}

                    {analysis.events.length > 0 && (
                      <section>
                        <h2 className="text-sm font-medium text-gray-400 mb-3">
                          Recent Activity
                        </h2>
                        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-2">
                          <ActivityFeed events={analysis.events} />
                        </div>
                      </section>
                    )}
                  </div>
                )}
              </>
            )}
          </>
        )}
      </main>
    </div>
  )
}
