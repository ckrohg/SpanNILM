import type { UsageTrend } from '../lib/api'

interface Props {
  trends: UsageTrend[]
}

export default function UsageTrends({ trends }: Props) {
  if (trends.length === 0) return null

  const up = trends.filter((t) => t.direction === 'up')
  const down = trends.filter((t) => t.direction === 'down')

  return (
    <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
      <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
        Usage Trends (vs last week)
      </h3>
      <div className="space-y-1.5">
        {up.map((t) => (
          <div key={t.circuit_name} className="flex items-center gap-2">
            <span className="text-red-400 text-sm w-5 flex-shrink-0">
              &#x2191;
            </span>
            <span className="text-sm text-gray-700 dark:text-gray-300 flex-1 truncate">
              {t.circuit_name}
            </span>
            <span className="text-sm font-mono text-red-400 flex-shrink-0">
              +{Math.round(t.change_pct)}%
            </span>
            <span className="text-[11px] text-gray-600 flex-shrink-0 w-24 text-right">
              {t.previous_period_kwh.toFixed(1)} &rarr; {t.current_period_kwh.toFixed(1)} kWh
            </span>
          </div>
        ))}
        {down.map((t) => (
          <div key={t.circuit_name} className="flex items-center gap-2">
            <span className="text-green-400 text-sm w-5 flex-shrink-0">
              &#x2193;
            </span>
            <span className="text-sm text-gray-700 dark:text-gray-300 flex-1 truncate">
              {t.circuit_name}
            </span>
            <span className="text-sm font-mono text-green-400 flex-shrink-0">
              {Math.round(t.change_pct)}%
            </span>
            <span className="text-[11px] text-gray-600 flex-shrink-0 w-24 text-right">
              {t.previous_period_kwh.toFixed(1)} &rarr; {t.current_period_kwh.toFixed(1)} kWh
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
