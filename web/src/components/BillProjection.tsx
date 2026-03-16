import type { BillProjection as BillProjectionData, CostAttribution } from '../lib/api'

interface Props {
  projection: BillProjectionData
  costDrivers: CostAttribution[]
}

export default function BillProjection({ projection, costDrivers }: Props) {
  const progressPct = (projection.days_elapsed / (projection.days_elapsed + projection.days_remaining)) * 100

  return (
    <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-3 sm:p-5">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between mb-3 sm:mb-4 gap-1 sm:gap-0">
        <div>
          <h3 className="text-[10px] sm:text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">
            Projected Monthly Bill
          </h3>
          <div className="text-2xl sm:text-3xl font-mono font-bold text-gray-900 dark:text-white">
            ${projection.projected_monthly_cost.toFixed(0)}
          </div>
          <div className="text-xs sm:text-sm text-gray-500 mt-0.5">
            On track for {projection.projected_monthly_kwh.toFixed(0)} kWh
          </div>
        </div>
        <div className="text-left sm:text-right text-[10px] sm:text-xs text-gray-500">
          <div>{projection.daily_avg_kwh.toFixed(1)} kWh/day avg</div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="mb-3 sm:mb-4">
        <div className="flex justify-between text-[10px] sm:text-[11px] text-gray-500 mb-1">
          <span>Day {projection.days_elapsed}</span>
          <span>{projection.days_remaining} days left</span>
        </div>
        <div className="h-1.5 sm:h-2 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full bg-blue-500/80 transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Top cost drivers */}
      {costDrivers.length > 0 && (
        <div>
          <h4 className="text-[10px] text-gray-600 uppercase tracking-wider mb-2">
            Top Cost Drivers (Month)
          </h4>
          <div className="space-y-1.5">
            {costDrivers.slice(0, 5).map((driver) => (
              <div key={driver.name} className="flex items-center gap-1.5 sm:gap-2">
                <span className="text-[10px] sm:text-xs text-gray-400 w-20 sm:w-32 min-w-[5rem] sm:min-w-[8rem] truncate">
                  {driver.name}
                </span>
                <div className="flex-1 h-1.5 sm:h-2 bg-gray-200/60 dark:bg-gray-800/60 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-emerald-500/60"
                    style={{ width: `${driver.pct_of_total}%` }}
                  />
                </div>
                <span className="text-[10px] sm:text-[11px] font-mono text-green-500/80 w-10 sm:w-12 text-right">
                  ${driver.cost.toFixed(0)}
                </span>
                <span className="text-[10px] sm:text-[11px] font-mono text-gray-600 w-8 sm:w-10 text-right">
                  {driver.pct_of_total.toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
