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
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl px-3 sm:px-4 py-3">
          <div className="text-[10px] sm:text-xs text-gray-500 mb-1">{displayLabel}</div>
          <div className="text-lg sm:text-xl font-mono font-semibold text-white">
            {formatEnergy(displayEnergy)}
          </div>
          <div className="text-xs sm:text-sm text-green-400 font-mono">
            {formatCost(displayCost)}
          </div>
        </div>
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl px-3 sm:px-4 py-3">
          <div className="text-[10px] sm:text-xs text-gray-500 mb-1">
            {isMonthView ? 'Today' : 'This Month'}
          </div>
          <div className="text-lg sm:text-xl font-mono font-semibold text-white">
            {formatEnergy(isMonthView ? totalEnergyToday : totalEnergyMonth)}
          </div>
          <div className="text-xs sm:text-sm text-green-400 font-mono">
            {formatCost(isMonthView ? totalCostToday : totalCostMonth)}
          </div>
        </div>
      </div>

      {/* Top consumers */}
      {topConsumers.length > 0 && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-3 sm:p-4">
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
                  <span className="text-xs sm:text-sm text-gray-300 w-24 sm:w-36 min-w-[6rem] sm:min-w-[9rem] truncate">
                    {circuit.name}
                  </span>
                  <div className="flex-1 h-2 sm:h-3 bg-gray-800/60 rounded-full overflow-hidden">
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
    </div>
  )
}
