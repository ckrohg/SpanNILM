import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import type { CostAttribution, CircuitPower } from '../lib/api'

// Blue tones for dedicated, green tones for shared
const DEDICATED_COLORS = [
  '#3b82f6', '#2563eb', '#1d4ed8', '#60a5fa', '#93c5fd',
  '#1e40af', '#3b82f6', '#2563eb',
]
const SHARED_COLORS = [
  '#22c55e', '#16a34a', '#15803d', '#4ade80', '#86efac',
  '#166534', '#22c55e', '#16a34a',
]

interface Props {
  costDrivers: CostAttribution[]
  circuits: CircuitPower[]
}

export default function CostBreakdown({ costDrivers, circuits }: Props) {
  if (costDrivers.length === 0) return null

  // Build a lookup for dedicated status
  const dedicatedMap = new Map<string, boolean>()
  for (const c of circuits) {
    dedicatedMap.set(c.name, c.is_dedicated)
  }

  // Assign colors based on dedicated vs shared
  let dedIdx = 0
  let sharedIdx = 0
  const data = costDrivers.map((d) => {
    const isDedicated = dedicatedMap.get(d.name) ?? false
    const color = isDedicated
      ? DEDICATED_COLORS[dedIdx++ % DEDICATED_COLORS.length]
      : SHARED_COLORS[sharedIdx++ % SHARED_COLORS.length]
    return { ...d, color }
  })

  const totalCost = data.reduce((sum, d) => sum + d.cost, 0)

  return (
    <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
      <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
        Monthly Cost Breakdown
      </h3>

      <div className="flex items-center gap-6">
        {/* Donut chart */}
        <div className="relative w-48 h-48 flex-shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="cost"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                paddingAngle={1}
                strokeWidth={0}
              >
                {data.map((entry, i) => (
                  <Cell key={i} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1f2937',
                  border: '1px solid #374151',
                  borderRadius: '0.5rem',
                  fontSize: '11px',
                }}
                formatter={(value: number, name: string) => [
                  `$${value.toFixed(2)}`,
                  name,
                ]}
              />
            </PieChart>
          </ResponsiveContainer>
          {/* Center label */}
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <span className="text-lg font-mono font-bold text-gray-900 dark:text-white">
              ${totalCost.toFixed(0)}
            </span>
            <span className="text-[10px] text-gray-500">total</span>
          </div>
        </div>

        {/* Legend */}
        <div className="flex-1 space-y-1.5 overflow-hidden">
          {data.map((d) => (
            <div key={d.name} className="flex items-center gap-2">
              <span
                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                style={{ backgroundColor: d.color }}
              />
              <span className="text-xs text-gray-700 dark:text-gray-300 truncate flex-1">
                {d.name}
              </span>
              <span className="text-xs font-mono text-green-500/80 flex-shrink-0">
                ${d.cost.toFixed(2)}
              </span>
              <span className="text-[11px] font-mono text-gray-600 w-10 text-right flex-shrink-0">
                {d.pct_of_total.toFixed(0)}%
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Color key */}
      <div className="flex items-center gap-4 mt-3 pt-3 border-t border-gray-200 dark:border-gray-800/50">
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-blue-500" />
          <span className="text-[10px] text-gray-500">Dedicated</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-green-500" />
          <span className="text-[10px] text-gray-500">Shared</span>
        </div>
      </div>
    </div>
  )
}
