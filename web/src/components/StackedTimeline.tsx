import { useMemo } from 'react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
} from 'recharts'
import type { TimelineBucket } from '../lib/api'

// Rich 12-color palette with good contrast on dark backgrounds
const COLORS = [
  '#3b82f6', // blue
  '#22c55e', // green
  '#f97316', // orange
  '#a855f7', // purple
  '#06b6d4', // cyan
  '#ec4899', // pink
  '#eab308', // yellow
  '#14b8a6', // teal
  '#f43f5e', // rose
  '#8b5cf6', // violet
  '#84cc16', // lime
  '#e879f9', // fuchsia
]

function formatTime(ts: string): string {
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatPower(w: number): string {
  if (w >= 1000) return `${(w / 1000).toFixed(1)} kW`
  return `${Math.round(w)} W`
}

interface Props {
  timeline: TimelineBucket[]
  alwaysOnW: number
}

interface TooltipPayloadItem {
  name: string
  value: number
  color: string
  dataKey: string
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: TooltipPayloadItem[]
  label?: string
}) {
  if (!active || !payload || !payload.length) return null

  // Sort by value descending, filter out zero
  const items = payload
    .filter((p) => p.value > 0)
    .sort((a, b) => b.value - a.value)

  const total = items.reduce((sum, p) => sum + p.value, 0)

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 shadow-xl text-xs max-w-[260px]">
      <div className="text-gray-400 mb-1.5 font-medium">{label}</div>
      <div className="space-y-0.5">
        {items.map((item) => (
          <div key={item.dataKey} className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-1.5 min-w-0">
              <div
                className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
                style={{ backgroundColor: item.color }}
              />
              <span className="text-gray-300 truncate">{item.name}</span>
            </div>
            <span className="text-white font-mono tabular-nums flex-shrink-0">
              {formatPower(item.value)}
            </span>
          </div>
        ))}
      </div>
      <div className="border-t border-gray-700 mt-1.5 pt-1.5 flex justify-between">
        <span className="text-gray-400">Total</span>
        <span className="text-white font-mono font-bold">{formatPower(total)}</span>
      </div>
    </div>
  )
}

export default function StackedTimeline({ timeline, alwaysOnW }: Props) {
  if (!timeline.length) {
    return (
      <div className="h-48 sm:h-64 rounded-xl bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 flex items-center justify-center text-gray-500">
        No timeline data
      </div>
    )
  }

  // Sort circuits: most stable/always-on at bottom, most variable/spiky at top.
  // This creates a flat baseline of always-on loads with active loads stacked above.
  const { chartData, sortedKeys, colorMap } = useMemo(() => {
    const circuitTotals: Record<string, number> = {}
    const circuitVariance: Record<string, number> = {}
    const circuitReadings: Record<string, number[]> = {}

    for (const bucket of timeline) {
      for (const [name, power] of Object.entries(bucket.circuits)) {
        circuitTotals[name] = (circuitTotals[name] || 0) + power
        if (!circuitReadings[name]) circuitReadings[name] = []
        circuitReadings[name].push(power)
      }
    }

    // Compute coefficient of variation (std/mean) — lower = more stable = bottom of stack
    for (const [name, readings] of Object.entries(circuitReadings)) {
      const mean = readings.reduce((s, v) => s + v, 0) / readings.length
      const variance = readings.reduce((s, v) => s + (v - mean) ** 2, 0) / readings.length
      const std = Math.sqrt(variance)
      circuitVariance[name] = mean > 0 ? std / mean : 0  // CV: 0 = perfectly flat, high = spiky
    }

    // Sort: most stable (lowest CV) first = renders at bottom of stack
    // Tie-break by total energy (higher energy = more visually prominent at bottom)
    const sorted = Object.entries(circuitTotals)
      .sort((a, b) => {
        const cvA = circuitVariance[a[0]] || 0
        const cvB = circuitVariance[b[0]] || 0
        // Stable loads (low CV) at bottom, spiky loads (high CV) at top
        if (Math.abs(cvA - cvB) > 0.3) return cvA - cvB
        // Tie-break: higher total energy at bottom (more visually stable)
        return b[1] - a[1]
      })

    // Show all circuits individually — with only 17 circuits, no need for "Other"
    const allCircuits = sorted.map(([name]) => name)
    const keys = [...allCircuits]

    const colors: Record<string, string> = {}
    keys.forEach((key, i) => {
      colors[key] = key === 'Other' ? '#6b7280' : COLORS[i % COLORS.length]
    })

    const data = timeline.map((bucket) => {
      const point: Record<string, number | string> = {
        time: formatTime(bucket.timestamp),
        timestamp: bucket.timestamp,
      }

      for (const name of allCircuits) {
        point[name] = Math.max(0, Math.round(bucket.circuits[name] || 0))
      }

      return point
    })

    return { chartData: data, sortedKeys: keys, colorMap: colors }
  }, [timeline])

  return (
    <div className="rounded-xl bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 p-2 sm:p-4">
      <div className="h-56 sm:h-72">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <defs>
              {sortedKeys.map((key) => (
                <linearGradient key={key} id={`fill-${key.replace(/[^a-zA-Z0-9]/g, '_')}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={colorMap[key]} stopOpacity={0.7} />
                  <stop offset="100%" stopColor={colorMap[key]} stopOpacity={0.5} />
                </linearGradient>
              ))}
            </defs>
            <XAxis
              dataKey="time"
              stroke="#4b5563"
              fontSize={10}
              tickLine={false}
              axisLine={{ stroke: '#374151' }}
              interval="preserveStartEnd"
              minTickGap={60}
            />
            <YAxis
              stroke="#4b5563"
              fontSize={10}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => formatPower(v)}
              width={52}
            />
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ stroke: '#6b7280', strokeWidth: 1, strokeDasharray: '4 4' }}
            />
            <Legend
              wrapperStyle={{ fontSize: '10px', paddingTop: '8px' }}
              iconType="square"
              iconSize={8}
              formatter={(value: string) => (
                <span className="text-gray-400 text-[10px]">{value}</span>
              )}
            />
            {alwaysOnW > 0 && (
              <ReferenceLine
                y={alwaysOnW}
                stroke="#f59e0b"
                strokeDasharray="6 3"
                strokeWidth={1.5}
                label={{
                  value: `Always on: ${formatPower(alwaysOnW)}`,
                  position: 'right',
                  fill: '#f59e0b',
                  fontSize: 10,
                }}
              />
            )}
            {/* Render largest consumers first (bottom of stack) */}
            {sortedKeys.map((key) => (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                stackId="1"
                stroke={colorMap[key]}
                strokeWidth={0.5}
                fill={`url(#fill-${key.replace(/[^a-zA-Z0-9]/g, '_')})`}
                fillOpacity={1}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
