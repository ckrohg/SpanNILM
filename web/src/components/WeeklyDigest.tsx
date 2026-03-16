import type { DashboardData } from '../lib/api'

interface Props {
  data: DashboardData
}

export default function WeeklyDigest({ data }: Props) {
  // Use month-to-date data as proxy for weekly metrics
  // daily average from bill projection if available, else compute
  const dailyAvgKwh = data.bill_projection?.daily_avg_kwh
    ?? (data.total_energy_month_kwh / Math.max(data.bill_projection?.days_elapsed ?? 1, 1))

  const daysElapsed = data.bill_projection?.days_elapsed ?? 1
  const weekDays = Math.min(daysElapsed, 7)

  // Estimated weekly totals
  const weeklyKwh = dailyAvgKwh * weekDays
  const weeklyCost = (data.total_cost_month / Math.max(daysElapsed, 1)) * weekDays

  // Most expensive circuit
  const topCircuit = [...data.circuits]
    .sort((a, b) => b.cost_month - a.cost_month)[0]

  // Find the most notable trend (biggest absolute % change)
  const biggestTrend = data.trends.length > 0
    ? [...data.trends].sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct))[0]
    : null

  // Always-on percentage
  const alwaysOnPct = data.total_power_w > 0
    ? Math.round((data.always_on_w / data.total_power_w) * 100)
    : 0

  return (
    <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
      <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-4">
        Weekly Summary
      </h3>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Total Energy</div>
          <div className="text-lg font-mono font-semibold text-gray-900 dark:text-white">
            {weeklyKwh.toFixed(1)}
            <span className="text-xs text-gray-500 ml-1">kWh</span>
          </div>
        </div>
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Total Cost</div>
          <div className="text-lg font-mono font-semibold text-green-400">
            ${weeklyCost.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Daily Average</div>
          <div className="text-lg font-mono font-semibold text-gray-900 dark:text-white">
            {dailyAvgKwh.toFixed(1)}
            <span className="text-xs text-gray-500 ml-1">kWh</span>
          </div>
        </div>
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Always On</div>
          <div className="text-lg font-mono font-semibold text-amber-400">
            {alwaysOnPct}%
          </div>
        </div>
      </div>

      {/* Top circuit */}
      {topCircuit && (
        <div className="flex items-center gap-2 text-sm mb-2">
          <span className="text-gray-500">Most expensive:</span>
          <span className="text-gray-800 dark:text-gray-200 font-medium">{topCircuit.name}</span>
          <span className="font-mono text-green-500/80">
            ${topCircuit.cost_month.toFixed(2)}/mo
          </span>
        </div>
      )}

      {/* Top insight */}
      {biggestTrend && (
        <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-800/50">
          <div className="text-[10px] text-gray-500 uppercase mb-1">Top Insight</div>
          <p className="text-sm text-gray-700 dark:text-gray-300">
            {biggestTrend.direction === 'up' ? (
              <span>
                <span className="text-red-400 font-medium">{biggestTrend.circuit_name}</span>
                {' '}usage is up{' '}
                <span className="text-red-400 font-mono">+{Math.round(biggestTrend.change_pct)}%</span>
                {' '}vs last week ({biggestTrend.previous_period_kwh.toFixed(1)} &rarr; {biggestTrend.current_period_kwh.toFixed(1)} kWh).
              </span>
            ) : (
              <span>
                <span className="text-green-400 font-medium">{biggestTrend.circuit_name}</span>
                {' '}usage is down{' '}
                <span className="text-green-400 font-mono">{Math.round(biggestTrend.change_pct)}%</span>
                {' '}vs last week ({biggestTrend.previous_period_kwh.toFixed(1)} &rarr; {biggestTrend.current_period_kwh.toFixed(1)} kWh).
              </span>
            )}
          </p>
        </div>
      )}
    </div>
  )
}
