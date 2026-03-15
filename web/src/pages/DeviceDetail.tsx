import { useEffect, useState } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { fetchDeviceDetail } from '../lib/api'
import type { DeviceDetailData } from '../lib/api'

function formatPower(w: number): string {
  if (w >= 1000) return `${(w / 1000).toFixed(1)} kW`
  return `${Math.round(w)} W`
}

function formatDuration(min: number): string {
  if (min >= 60) {
    const h = Math.floor(min / 60)
    const m = Math.round(min % 60)
    return m > 0 ? `${h}h ${m}m` : `${h}h`
  }
  return `${Math.round(min)}min`
}

function TemplateSparkline({ curve }: { curve: number[] }) {
  const w = 200
  const h = 60
  const points = curve
    .map((v, i) => {
      const x = (i / (curve.length - 1)) * w
      const y = h - v * (h - 4) - 2
      return `${x},${y}`
    })
    .join(' ')
  return (
    <svg width={w} height={h} className="flex-shrink-0">
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="text-emerald-500"
      />
    </svg>
  )
}

interface Props {
  equipmentId: string
  clusterId: number
  onBack: () => void
}

type Period = 7 | 14 | 30

export default function DeviceDetail({ equipmentId, clusterId, onBack }: Props) {
  const [data, setData] = useState<DeviceDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [period, setPeriod] = useState<Period>(30)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchDeviceDetail(equipmentId, clusterId, period)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [equipmentId, clusterId, period])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="flex items-center gap-3 text-gray-400">
          <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span>Loading device detail...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-800 rounded-xl p-4 text-red-300">
        <p className="font-medium">Failed to load device detail</p>
        <p className="text-sm mt-1">{error}</p>
        <button onClick={onBack} className="mt-3 px-3 py-1.5 text-xs rounded-lg bg-red-800 hover:bg-red-700 transition-colors">
          Back
        </button>
      </div>
    )
  }

  if (!data) return null

  // Build daily energy from sessions
  const dailyMap: Record<string, number> = {}
  for (const session of data.sessions) {
    const date = new Date(session.start).toLocaleDateString(undefined, { year: 'numeric', month: '2-digit', day: '2-digit' })
    dailyMap[date] = (dailyMap[date] || 0) + session.energy_wh / 1000
  }
  const dailyChartData = Object.entries(dailyMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, kwh]) => ({
      date,
      label: new Date(date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
      energy_kwh: Math.round(kwh * 1000) / 1000,
    }))

  // Peak hours bar chart data
  const hourCounts: Record<number, number> = {}
  for (const session of data.sessions) {
    const hour = new Date(session.start).getHours()
    hourCounts[hour] = (hourCounts[hour] || 0) + 1
  }
  const peakHoursData = Array.from({ length: 24 }, (_, i) => ({
    hour: i,
    label: `${i}:00`,
    sessions: hourCounts[i] || 0,
  }))

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
            Back
          </button>
          <h2 className="text-2xl font-semibold text-white">
            {data.name.replace(/_/g, ' ')}
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">
            on {data.circuit_name}
          </p>
        </div>
        <div className="text-right flex items-start gap-6">
          {data.template_curve.length > 0 && (
            <TemplateSparkline curve={data.template_curve} />
          )}
          <div>
            <div className="text-2xl font-mono font-bold text-white">
              {data.total_energy_kwh.toFixed(1)} kWh
            </div>
            <div className="text-xs text-gray-500 mt-0.5">
              {data.total_sessions} sessions in {period} days
            </div>
          </div>
        </div>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {[
          { label: 'Avg Power', value: formatPower(data.avg_power_w) },
          { label: 'Peak Power', value: formatPower(data.peak_power_w) },
          { label: 'Sessions/Day', value: data.avg_sessions_per_day.toFixed(1) },
          { label: 'Total Sessions', value: String(data.total_sessions) },
          { label: 'Total Energy', value: `${data.total_energy_kwh.toFixed(1)} kWh` },
        ].map((stat) => (
          <div key={stat.label} className="bg-gray-900/50 border border-gray-800 rounded-xl px-3 py-2.5">
            <div className="text-[10px] text-gray-500 uppercase tracking-wide">{stat.label}</div>
            <div className="text-lg font-mono font-semibold text-white mt-0.5">{stat.value}</div>
          </div>
        ))}
      </div>

      {/* Period selector */}
      <div className="flex gap-1">
        {([7, 14, 30] as Period[]).map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
              period === p
                ? 'bg-gray-700 text-white'
                : 'text-gray-500 hover:text-gray-300 hover:bg-gray-800/50'
            }`}
          >
            {p}d
          </button>
        ))}
      </div>

      {/* Daily energy chart */}
      {dailyChartData.length > 1 && (
        <section>
          <h3 className="text-sm font-medium text-gray-400 mb-2">Daily Energy</h3>
          <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
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
                  formatter={(value: number) => [`${value.toFixed(3)} kWh`, 'Energy']}
                />
                <Bar dataKey="energy_kwh" fill="#10b981" fillOpacity={0.7} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {/* Peak hours chart */}
      {data.sessions.length > 0 && (
        <section>
          <h3 className="text-sm font-medium text-gray-400 mb-2">Usage by Hour of Day</h3>
          <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={peakHoursData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis
                  dataKey="hour"
                  stroke="#4b5563"
                  tick={{ fontSize: 10 }}
                  tickFormatter={(v) => `${v}`}
                />
                <YAxis stroke="#4b5563" tick={{ fontSize: 11 }} width={30} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111827', border: '1px solid #374151', borderRadius: '8px' }}
                  labelFormatter={(v) => `${v}:00`}
                  formatter={(value: number) => [`${value} sessions`, 'Count']}
                />
                <Bar dataKey="sessions" fill="#8b5cf6" fillOpacity={0.7} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {/* Session list */}
      <section>
        <h3 className="text-sm font-medium text-gray-400 mb-2">
          Sessions ({data.sessions.length})
        </h3>
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl overflow-hidden">
          {data.sessions.length === 0 ? (
            <div className="p-6 text-center text-gray-600 text-sm">
              No matching sessions found in this period
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                    <th className="text-left px-4 py-2.5">Start</th>
                    <th className="text-left px-4 py-2.5">End</th>
                    <th className="text-right px-4 py-2.5">Duration</th>
                    <th className="text-right px-4 py-2.5">Avg Power</th>
                    <th className="text-right px-4 py-2.5">Energy</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sessions.slice(0, 100).map((s, i) => (
                    <tr
                      key={i}
                      className="border-b border-gray-800/30 hover:bg-gray-800/20 transition-colors"
                    >
                      <td className="px-4 py-2 text-gray-300 font-mono text-xs">
                        {new Date(s.start).toLocaleString(undefined, {
                          month: 'short', day: 'numeric',
                          hour: 'numeric', minute: '2-digit',
                        })}
                      </td>
                      <td className="px-4 py-2 text-gray-400 font-mono text-xs">
                        {new Date(s.end).toLocaleString(undefined, {
                          hour: 'numeric', minute: '2-digit',
                        })}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-400 font-mono text-xs">
                        {formatDuration(s.duration_min)}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-300 font-mono text-xs">
                        {formatPower(s.avg_power_w)}
                      </td>
                      <td className="px-4 py-2 text-right text-emerald-400 font-mono text-xs">
                        {s.energy_wh >= 1000
                          ? `${(s.energy_wh / 1000).toFixed(2)} kWh`
                          : `${s.energy_wh.toFixed(0)} Wh`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.sessions.length > 100 && (
                <div className="px-4 py-2 text-xs text-gray-600 text-center">
                  Showing 100 of {data.sessions.length} sessions
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
