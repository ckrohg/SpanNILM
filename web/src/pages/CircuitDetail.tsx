import { useEffect, useState } from 'react'
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { fetchCircuitDetail } from '../lib/api'
import type { CircuitDetailData } from '../lib/api'

function formatPower(w: number): string {
  if (w >= 1000) return `${(w / 1000).toFixed(1)} kW`
  return `${Math.round(w)} W`
}

function formatDuration(min: number): string {
  if (min >= 60) return `${(min / 60).toFixed(1)}h`
  return `${Math.round(min)}min`
}

interface Props {
  equipmentId: string
  onBack: () => void
}

type Period = 1 | 3 | 7 | 30

export default function CircuitDetail({ equipmentId, onBack }: Props) {
  const [data, setData] = useState<CircuitDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [period, setPeriod] = useState<Period>(7)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchCircuitDetail(equipmentId, period)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [equipmentId, period])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="flex items-center gap-3 text-gray-400">
          <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span>Loading circuit detail...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-800 rounded-xl p-4 text-red-300">
        <p className="font-medium">Failed to load circuit detail</p>
        <p className="text-sm mt-1">{error}</p>
        <button onClick={onBack} className="mt-3 px-3 py-1.5 text-xs rounded-lg bg-red-800 hover:bg-red-700 transition-colors">
          Back to Dashboard
        </button>
      </div>
    )
  }

  if (!data) return null

  // Format power series for chart
  const powerChartData = data.power_series.map((p) => {
    const d = new Date(p.timestamp)
    return {
      time: d.getTime(),
      label: d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }),
      power_w: p.power_w,
    }
  })

  // Format daily energy for bar chart
  const dailyChartData = data.daily_energy.map((d) => ({
    date: d.date,
    label: new Date(d.date + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    energy_kwh: d.energy_kwh,
    cost: d.cost,
  }))

  const fillColor = data.is_dedicated ? '#3b82f6' : '#10b981'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <button
            onClick={onBack}
            className="text-gray-500 hover:text-gray-300 text-sm mb-2 flex items-center gap-1 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            Back to Dashboard
          </button>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-semibold text-gray-900 dark:text-white">{data.name}</h2>
            {data.is_dedicated && data.device_type && (
              <span className="text-xs px-2 py-0.5 rounded bg-blue-900/60 text-blue-300 border border-blue-800/50">
                {data.device_type}
              </span>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-mono font-bold text-gray-900 dark:text-white">
            {data.energy_period_kwh.toFixed(1)} kWh
          </div>
          <div className="text-sm text-green-400 font-mono">
            ${data.cost_period.toFixed(2)}
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            Last {period} day{period > 1 ? 's' : ''}
          </div>
        </div>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {[
          { label: 'Average', value: formatPower(data.avg_power_w) },
          { label: 'Peak', value: formatPower(data.peak_power_w) },
          { label: 'Minimum', value: formatPower(data.min_power_w) },
          { label: 'Always On', value: formatPower(data.always_on_w) },
          { label: 'Total Energy', value: `${data.energy_period_kwh.toFixed(1)} kWh` },
        ].map((stat) => (
          <div key={stat.label} className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl px-3 py-2.5">
            <div className="text-[10px] text-gray-500 uppercase tracking-wide">{stat.label}</div>
            <div className="text-lg font-mono font-semibold text-gray-900 dark:text-white mt-0.5">{stat.value}</div>
          </div>
        ))}
      </div>

      {/* Period selector + Power chart */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-gray-400">Power Over Time</h3>
          <div className="flex gap-1">
            {([1, 3, 7, 30] as Period[]).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  period === p
                    ? 'bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white'
                    : 'text-gray-500 hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800/50'
                }`}
              >
                {p}d
              </button>
            ))}
          </div>
        </div>
        <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
          {powerChartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={powerChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis
                  dataKey="time"
                  type="number"
                  domain={['dataMin', 'dataMax']}
                  tickFormatter={(v) => {
                    const d = new Date(v)
                    if (period <= 3) {
                      return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' })
                    }
                    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
                  }}
                  stroke="#4b5563"
                  tick={{ fontSize: 11 }}
                />
                <YAxis
                  tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${v}`)}
                  stroke="#4b5563"
                  tick={{ fontSize: 11 }}
                  width={45}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '8px' }}
                  labelFormatter={(v) => new Date(v).toLocaleString()}
                  formatter={(value: number) => [`${formatPower(value)}`, 'Power']}
                />
                <Area
                  type="monotone"
                  dataKey="power_w"
                  stroke={fillColor}
                  fill={fillColor}
                  fillOpacity={0.15}
                  strokeWidth={1.5}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-48 flex items-center justify-center text-gray-600 text-sm">
              No power data for this period
            </div>
          )}
        </div>
      </section>

      {/* Daily energy bar chart */}
      {dailyChartData.length > 1 && (
        <section>
          <h3 className="text-sm font-medium text-gray-400 mb-2">Daily Energy</h3>
          <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={dailyChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="label" stroke="#4b5563" tick={{ fontSize: 11 }} />
                <YAxis
                  stroke="#4b5563"
                  tick={{ fontSize: 11 }}
                  width={45}
                  tickFormatter={(v) => `${v.toFixed(1)}`}
                />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '8px' }}
                  formatter={(value: number, name: string) => {
                    if (name === 'energy_kwh') return [`${value.toFixed(2)} kWh`, 'Energy']
                    return [`$${value.toFixed(2)}`, 'Cost']
                  }}
                />
                <Bar dataKey="energy_kwh" fill={fillColor} fillOpacity={0.7} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {/* Detected devices */}
      {data.devices.length > 0 && (
        <section>
          <h3 className="text-sm font-medium text-gray-400 mb-2">
            Detected Devices ({data.devices.length})
          </h3>
          <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-4 space-y-3">
            {data.devices.map((d, i) => {
              const conf = d.confidence
              const confColor = conf >= 0.7 ? 'text-green-400' : conf >= 0.4 ? 'text-yellow-400' : 'text-gray-500'
              return (
                <div key={i} className="flex items-center gap-4">
                  {d.template_curve && d.template_curve.length > 0 && (
                    <MiniSparkline curve={d.template_curve} />
                  )}
                  <div className="flex-1">
                    <div className="text-sm text-gray-800 dark:text-gray-200">{d.name.replace(/_/g, ' ')}</div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {d.session_count} sessions, {formatDuration(d.avg_duration_min)} avg, {d.energy_per_session_wh.toFixed(0)} Wh/session
                    </div>
                  </div>
                  <span className="text-sm font-mono text-gray-400">{formatPower(d.power_w)}</span>
                  <span className={`text-sm font-mono ${confColor}`}>{Math.round(conf * 100)}%</span>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* Anomalies */}
      {data.anomalies.length > 0 && (
        <section>
          <h3 className="text-sm font-medium text-gray-400 mb-2">
            Unusual Activity ({data.anomalies.length})
          </h3>
          <div className="space-y-2">
            {data.anomalies.map((a, i) => (
              <div
                key={i}
                className={`bg-gray-900/50 border rounded-xl px-4 py-3 ${
                  a.severity === 'warning'
                    ? 'border-amber-800/60'
                    : a.severity === 'alert'
                    ? 'border-red-800/60'
                    : 'border-gray-200 dark:border-gray-800'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      a.severity === 'warning'
                        ? 'bg-amber-400'
                        : a.severity === 'alert'
                        ? 'bg-red-400'
                        : 'bg-blue-400'
                    }`}
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">{a.timestamp}</span>
                </div>
                <p className="text-xs text-gray-500 mt-1 ml-4">{a.description}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function MiniSparkline({ curve }: { curve: number[] }) {
  const w = 100
  const h = 28
  const points = curve
    .map((v, i) => {
      const x = (i / (curve.length - 1)) * w
      const y = h - v * (h - 2) - 1
      return `${x},${y}`
    })
    .join(' ')
  return (
    <svg width={w} height={h} className="flex-shrink-0">
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className="text-emerald-500/70"
      />
    </svg>
  )
}
