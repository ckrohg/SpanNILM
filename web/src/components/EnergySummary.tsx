import type { CircuitPower, DateRange } from '../lib/api'

function formatEnergy(kwh: number): string {
  if (kwh >= 100) return `${Math.round(kwh)} kWh`
  if (kwh >= 10) return `${kwh.toFixed(1)} kWh`
  return `${kwh.toFixed(2)} kWh`
}

function formatCost(dollars: number): string {
  return `$${dollars.toFixed(2)}`
}

const RANGE_LABELS: Record<DateRange, string> = {
  today: 'Today',
  yesterday: 'Yesterday',
  '7d': 'Last 7 Days',
  '30d': 'Last 30 Days',
  month: 'This Month',
  year: 'This Year',
  '365d': 'Last 365 Days',
}

interface Props {
  circuits: CircuitPower[]
  totalEnergyToday: number
  totalCostToday: number
  totalEnergyMonth: number
  totalCostMonth: number
  dateRange?: DateRange
}

export default function EnergySummary({
  circuits,
  totalEnergyToday,
  totalCostToday,
  totalEnergyMonth,
  totalCostMonth,
  dateRange = 'today',
}: Props) {
  // Determine which data to show based on dateRange
  const isMonthView = dateRange === 'month' || dateRange === '30d' || dateRange === 'year' || dateRange === '365d'
  const displayEnergy = isMonthView ? totalEnergyMonth : totalEnergyToday
  const displayCost = isMonthView ? totalCostMonth : totalCostToday
  const displayLabel = RANGE_LABELS[dateRange]

  // Sort circuits by the appropriate metric
  const topConsumers = [...circuits]
    .sort((a, b) =>
      isMonthView
        ? b.energy_month_kwh - a.energy_month_kwh
        : b.energy_today_kwh - a.energy_today_kwh
    )
    .slice(0, 6)
    .filter((c) => (isMonthView ? c.energy_month_kwh : c.energy_today_kwh) > 0)

  const maxEnergy = isMonthView
    ? (topConsumers[0]?.energy_month_kwh || 1)
    : (topConsumers[0]?.energy_today_kwh || 1)

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl px-3 sm:px-4 py-3">
          <div className="text-[10px] sm:text-xs text-gray-500 mb-1">{displayLabel}</div>
          <div className="text-lg sm:text-xl font-mono font-semibold text-gray-900 dark:text-white">
            {formatEnergy(displayEnergy)}
          </div>
          <div className="text-xs sm:text-sm text-green-400 font-mono">
            {formatCost(displayCost)}
          </div>
        </div>
        <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl px-3 sm:px-4 py-3">
          <div className="text-[10px] sm:text-xs text-gray-500 mb-1">
            {isMonthView ? 'Today' : 'This Month'}
          </div>
          <div className="text-lg sm:text-xl font-mono font-semibold text-gray-900 dark:text-white">
            {formatEnergy(isMonthView ? totalEnergyToday : totalEnergyMonth)}
          </div>
          <div className="text-xs sm:text-sm text-green-400 font-mono">
            {formatCost(isMonthView ? totalCostToday : totalCostMonth)}
          </div>
        </div>
      </div>

      {/* Top consumers */}
      {topConsumers.length > 0 && (
        <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-3 sm:p-4">
          <h3 className="text-[10px] sm:text-xs font-medium text-gray-400 mb-3 uppercase tracking-wide">
            Top Consumers — {displayLabel}
          </h3>
          <div className="space-y-2">
            {topConsumers.map((circuit) => {
              const energy = isMonthView ? circuit.energy_month_kwh : circuit.energy_today_kwh
              const cost = isMonthView ? circuit.cost_month : circuit.cost_today
              const pct = (energy / maxEnergy) * 100
              return (
                <div key={circuit.equipment_id} className="flex items-center gap-2 sm:gap-3">
                  <span className="text-xs sm:text-sm text-gray-700 dark:text-gray-300 w-24 sm:w-36 min-w-[6rem] sm:min-w-[9rem] truncate">
                    {circuit.name}
                  </span>
                  <div className="flex-1 h-2 sm:h-3 bg-gray-200/60 dark:bg-gray-800/60 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-emerald-500/70"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-[10px] sm:text-xs font-mono text-gray-400 w-16 sm:w-20 text-right">
                    {formatEnergy(energy)}
                  </span>
                  <span className="text-[10px] sm:text-xs font-mono text-green-500/70 w-10 sm:w-14 text-right">
                    {formatCost(cost)}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Top Always-On loads */}
      {(() => {
        const topAlwaysOn = [...circuits]
          .filter((c) => c.always_on_w > 1)
          .sort((a, b) => b.always_on_w - a.always_on_w)
          .slice(0, 5)
        const maxAO = topAlwaysOn[0]?.always_on_w || 1

        // Estimate always-on cost for the selected period
        const periodHours = isMonthView
          ? (dateRange === 'year' || dateRange === '365d' ? 8760 : 720)
          : (dateRange === '7d' ? 168 : 24)
        const rate = displayCost / Math.max(displayEnergy, 1)

        if (topAlwaysOn.length === 0) return null
        const totalAOW = topAlwaysOn.reduce((s, c) => s + c.always_on_w, 0)
        const totalAOCost = (totalAOW * periodHours / 1000) * rate

        return (
          <div className="bg-amber-900/10 border border-amber-800/30 rounded-xl p-3 sm:p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-[10px] sm:text-xs font-medium text-amber-700 dark:text-amber-400/80 uppercase tracking-wide">
                Top Always-On Loads
              </h3>
              <span className="text-[10px] text-amber-700 dark:text-amber-400/60">
                ~{formatCost(totalAOCost)} during {displayLabel.toLowerCase()}
              </span>
            </div>
            <div className="space-y-2">
              {topAlwaysOn.map((circuit) => {
                const pct = (circuit.always_on_w / maxAO) * 100
                const aoCostPeriod = (circuit.always_on_w * periodHours / 1000) * rate
                return (
                  <div key={circuit.equipment_id} className="flex items-center gap-2 sm:gap-3">
                    <span className="text-xs sm:text-sm text-gray-700 dark:text-gray-300 w-24 sm:w-36 min-w-[6rem] sm:min-w-[9rem] truncate">
                      {circuit.name}
                    </span>
                    <div className="flex-1 h-2 sm:h-3 bg-gray-200/60 dark:bg-gray-800/60 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-amber-500/50"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-[10px] sm:text-xs font-mono text-amber-700 dark:text-amber-300 w-14 sm:w-16 text-right">
                      {circuit.always_on_w >= 1000
                        ? `${(circuit.always_on_w / 1000).toFixed(1)} kW`
                        : `${Math.round(circuit.always_on_w)} W`}
                    </span>
                    <span className="text-[10px] sm:text-xs font-mono text-amber-700 dark:text-amber-400/60 w-10 sm:w-14 text-right">
                      {formatCost(aoCostPeriod)}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })()}
    </div>
  )
}
