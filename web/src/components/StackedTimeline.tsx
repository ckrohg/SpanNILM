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

// Distinct color palette for circuits
const COLORS = [
  '#3b82f6', // blue
  '#22c55e', // green
  '#f59e0b', // orange
  '#8b5cf6', // purple
  '#06b6d4', // cyan
  '#ec4899', // pink
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

export default function StackedTimeline({ timeline, alwaysOnW }: Props) {
  if (!timeline.length) {
    return (
      <div className="h-48 sm:h-64 rounded-xl bg-gray-900/50 border border-gray-800 flex items-center justify-center text-gray-500">
        No timeline data
      </div>
    )
  }

  // Find top 6 circuits by total energy across all buckets
  const circuitTotals: Record<string, number> = {}
  for (const bucket of timeline) {
    for (const [name, power] of Object.entries(bucket.circuits)) {
      circuitTotals[name] = (circuitTotals[name] || 0) + power
    }
  }

  const sortedCircuits = Object.entries(circuitTotals)
    .sort((a, b) => b[1] - a[1])

  const topCircuits = sortedCircuits.slice(0, 6).map(([name]) => name)
  const otherCircuits = sortedCircuits.slice(6).map(([name]) => name)
  const hasOther = otherCircuits.length > 0

  // Build flat data for Recharts
  const chartData = timeline.map((bucket) => {
    const point: Record<string, number | string> = {
      time: formatTime(bucket.timestamp),
      timestamp: bucket.timestamp,
    }

    for (const name of topCircuits) {
      point[name] = Math.round(bucket.circuits[name] || 0)
    }

    if (hasOther) {
      let otherSum = 0
      for (const name of otherCircuits) {
        otherSum += bucket.circuits[name] || 0
      }
      point['Other'] = Math.round(otherSum)
    }

    return point
  })

  const allKeys = [...topCircuits]
  if (hasOther) allKeys.push('Other')

  const colorMap: Record<string, string> = {}
  allKeys.forEach((key, i) => {
    colorMap[key] = key === 'Other' ? '#4b5563' : COLORS[i % COLORS.length]
  })

  return (
    <div className="rounded-xl bg-gray-900/50 border border-gray-800 p-2 sm:p-4">
      <div className="h-48 sm:h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData}>
            <defs>
              {allKeys.map((key) => (
                <linearGradient key={key} id={`grad-${key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={colorMap[key]} stopOpacity={0.6} />
                  <stop offset="95%" stopColor={colorMap[key]} stopOpacity={0.1} />
                </linearGradient>
              ))}
            </defs>
            <XAxis
              dataKey="time"
              stroke="#4b5563"
              fontSize={10}
              tickLine={false}
              interval="preserveStartEnd"
              minTickGap={60}
            />
            <YAxis
              stroke="#4b5563"
              fontSize={10}
              tickLine={false}
              tickFormatter={(v) => formatPower(v)}
              width={50}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1f2937',
                border: '1px solid #374151',
                borderRadius: '0.5rem',
                fontSize: '11px',
              }}
              formatter={(value: number, name: string) => [formatPower(value), name]}
              labelFormatter={(label) => `Time: ${label}`}
              itemSorter={(item) => -(item.value as number)}
            />
            <Legend
              wrapperStyle={{ fontSize: '10px', paddingTop: '4px' }}
              iconType="square"
              iconSize={8}
              formatter={(value) => (
                <span className="text-gray-400">{value}</span>
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
            {allKeys.map((key) => (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                stackId="1"
                stroke={colorMap[key]}
                fill={`url(#grad-${key})`}
                strokeWidth={1}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
