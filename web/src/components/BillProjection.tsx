import type { BillProjection as BillProjectionData, CostAttribution } from '../lib/api'

interface Props {
  projection: BillProjectionData
  costDrivers: CostAttribution[]
}

export default function BillProjection({ projection, costDrivers }: Props) {
  const progressPct = (projection.days_elapsed / (projection.days_elapsed + projection.days_remaining)) * 100

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">
            Projected Monthly Bill
          </h3>
          <div className="text-3xl font-mono font-bold text-white">
            ${projection.projected_monthly_cost.toFixed(0)}
          </div>
          <div className="text-sm text-gray-500 mt-0.5">
            On track for {projection.projected_monthly_kwh.toFixed(0)} kWh
          </div>
        </div>
        <div className="text-right text-xs text-gray-500">
          <div>{projection.daily_avg_kwh.toFixed(1)} kWh/day avg</div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="mb-4">
        <div className="flex justify-between text-[11px] text-gray-500 mb-1">
          <span>Day {projection.days_elapsed}</span>
          <span>{projection.days_remaining} days left</span>
        </div>
        <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
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
              <div key={driver.name} className="flex items-center gap-2">
                <span className="text-xs text-gray-400 w-32 min-w-[8rem] truncate">
                  {driver.name}
                </span>
                <div className="flex-1 h-2 bg-gray-800/60 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-emerald-500/60"
                    style={{ width: `${driver.pct_of_total}%` }}
                  />
                </div>
                <span className="text-[11px] font-mono text-green-500/80 w-12 text-right">
                  ${driver.cost.toFixed(0)}
                </span>
                <span className="text-[11px] font-mono text-gray-600 w-10 text-right">
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
