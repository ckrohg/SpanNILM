import type { CircuitPower } from '../lib/api'

function formatEnergy(kwh: number): string {
  if (kwh >= 100) return `${Math.round(kwh)} kWh`
  if (kwh >= 10) return `${kwh.toFixed(1)} kWh`
  return `${kwh.toFixed(2)} kWh`
}

function formatCost(dollars: number): string {
  return `$${dollars.toFixed(2)}`
}

interface Props {
  circuits: CircuitPower[]
  totalEnergyToday: number
  totalCostToday: number
  totalEnergyMonth: number
  totalCostMonth: number
}

export default function EnergySummary({
  circuits,
  totalEnergyToday,
  totalCostToday,
  totalEnergyMonth,
  totalCostMonth,
}: Props) {
  const topConsumers = [...circuits]
    .sort((a, b) => b.energy_today_kwh - a.energy_today_kwh)
    .slice(0, 6)
    .filter((c) => c.energy_today_kwh > 0)

  const maxEnergy = topConsumers[0]?.energy_today_kwh || 1

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl px-4 py-3">
          <div className="text-xs text-gray-500 mb-1">Today</div>
          <div className="text-xl font-mono font-semibold text-white">
            {formatEnergy(totalEnergyToday)}
          </div>
          <div className="text-sm text-green-400 font-mono">
            {formatCost(totalCostToday)}
          </div>
        </div>
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl px-4 py-3">
          <div className="text-xs text-gray-500 mb-1">This Month</div>
          <div className="text-xl font-mono font-semibold text-white">
            {formatEnergy(totalEnergyMonth)}
          </div>
          <div className="text-sm text-green-400 font-mono">
            {formatCost(totalCostMonth)}
          </div>
        </div>
      </div>

      {/* Top consumers */}
      {topConsumers.length > 0 && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
          <h3 className="text-xs font-medium text-gray-400 mb-3 uppercase tracking-wide">
            Top Consumers Today
          </h3>
          <div className="space-y-2">
            {topConsumers.map((circuit) => {
              const pct = (circuit.energy_today_kwh / maxEnergy) * 100
              return (
                <div key={circuit.equipment_id} className="flex items-center gap-3">
                  <span className="text-sm text-gray-300 w-36 min-w-[9rem] truncate">
                    {circuit.name}
                  </span>
                  <div className="flex-1 h-3 bg-gray-800/60 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-emerald-500/70"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-xs font-mono text-gray-400 w-20 text-right">
                    {formatEnergy(circuit.energy_today_kwh)}
                  </span>
                  <span className="text-xs font-mono text-green-500/70 w-14 text-right">
                    {formatCost(circuit.cost_today)}
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
