import { useState, useMemo } from 'react'
import type { CircuitPower } from '../lib/api'

type Category = 'HVAC' | 'EV Charging' | 'Kitchen' | 'Laundry' | 'Water' | 'Lighting & Outlets' | 'Other'

const CATEGORY_META: Record<Category, { icon: string; color: string; border: string; bg: string; text: string }> = {
  'HVAC':              { icon: '\u2744\uFE0F', color: '#3b82f6', border: 'border-blue-500',   bg: 'bg-blue-500/10',   text: 'text-blue-400' },
  'EV Charging':       { icon: '\u26A1',       color: '#22c55e', border: 'border-green-500',  bg: 'bg-green-500/10',  text: 'text-green-400' },
  'Kitchen':           { icon: '\uD83C\uDF73', color: '#f97316', border: 'border-orange-500', bg: 'bg-orange-500/10', text: 'text-orange-400' },
  'Laundry':           { icon: '\uD83E\uDDFA', color: '#a855f7', border: 'border-purple-500', bg: 'bg-purple-500/10', text: 'text-purple-400' },
  'Water':             { icon: '\uD83D\uDCA7', color: '#06b6d4', border: 'border-cyan-500',   bg: 'bg-cyan-500/10',   text: 'text-cyan-400' },
  'Lighting & Outlets':{ icon: '\uD83D\uDCA1', color: '#eab308', border: 'border-yellow-500', bg: 'bg-yellow-500/10', text: 'text-yellow-400' },
  'Other':             { icon: '\uD83D\uDD0C', color: '#6b7280', border: 'border-gray-500',   bg: 'bg-gray-500/10',   text: 'text-gray-400' },
}

const CATEGORY_ORDER: Category[] = [
  'HVAC', 'EV Charging', 'Kitchen', 'Laundry', 'Water', 'Lighting & Outlets', 'Other',
]

function categorizeCircuit(circuit: CircuitPower): Category {
  const name = (circuit.name + ' ' + (circuit.device_type || '')).toLowerCase()
  if (/mini.?split|heat.?pump|air.?water|hydronic|hvac|compressor|glycol|zone.?pump/.test(name)) return 'HVAC'
  if (/ev.?charg/.test(name)) return 'EV Charging'
  if (/range|oven|stove|dishwasher|refrigerator|fridge|microwave/.test(name)) return 'Kitchen'
  if (/dryer|washer|laundry/.test(name) && !/dish/.test(name)) return 'Laundry'
  if (/well.?pump|water.?heater|buffer.?tank|hot.?water/.test(name)) return 'Water'
  if (/light|outlet|lamp/.test(name)) return 'Lighting & Outlets'
  return 'Other'
}

function formatPower(w: number): string {
  if (w >= 1000) return `${(w / 1000).toFixed(1)} kW`
  return `${Math.round(w)} W`
}

function formatEnergy(kwh: number): string {
  if (kwh >= 100) return `${Math.round(kwh)} kWh`
  if (kwh >= 10) return `${kwh.toFixed(1)} kWh`
  return `${kwh.toFixed(2)} kWh`
}

interface CategoryData {
  category: Category
  circuits: CircuitPower[]
  totalPowerW: number
  totalEnergyTodayKwh: number
  totalEnergyMonthKwh: number
  totalAlwaysOnW: number
}

interface Props {
  circuits: CircuitPower[]
}

function EnergyBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="w-full h-2 bg-gray-800 rounded-full overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.max(1, pct)}%`, backgroundColor: color }}
      />
    </div>
  )
}

function CategoryCard({ data, totalEnergyMonth }: { data: CategoryData; totalEnergyMonth: number }) {
  const [expanded, setExpanded] = useState(false)
  const meta = CATEGORY_META[data.category]
  const pctOfTotal = totalEnergyMonth > 0 ? (data.totalEnergyMonthKwh / totalEnergyMonth) * 100 : 0
  const isActive = data.totalPowerW > 5

  return (
    <div
      className={`rounded-xl bg-gray-900/60 border border-gray-800 overflow-hidden cursor-pointer
        hover:border-gray-700 transition-all duration-200 border-l-4 ${meta.border}`}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="p-4">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2.5">
            <span className="text-xl">{meta.icon}</span>
            <div>
              <h3 className="text-sm font-semibold text-white">{data.category}</h3>
              <span className="text-[10px] text-gray-500">{data.circuits.length} circuit{data.circuits.length !== 1 ? 's' : ''}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {isActive && (
              <span className="relative flex h-2.5 w-2.5">
                <span
                  className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-50"
                  style={{ backgroundColor: meta.color }}
                />
                <span
                  className="relative inline-flex rounded-full h-2.5 w-2.5"
                  style={{ backgroundColor: meta.color }}
                />
              </span>
            )}
            <span className="text-lg font-mono font-bold text-white">
              {formatPower(data.totalPowerW)}
            </span>
          </div>
        </div>

        {/* Energy stats */}
        <div className="grid grid-cols-2 gap-3 mb-3 text-xs">
          <div>
            <div className="text-gray-500">Today</div>
            <div className="text-gray-200 font-medium">{formatEnergy(data.totalEnergyTodayKwh)}</div>
          </div>
          <div>
            <div className="text-gray-500">This Month</div>
            <div className="text-gray-200 font-medium">{formatEnergy(data.totalEnergyMonthKwh)}</div>
          </div>
        </div>

        {/* % of total bar */}
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <EnergyBar pct={pctOfTotal} color={meta.color} />
          </div>
          <span className="text-[10px] text-gray-500 w-10 text-right">{pctOfTotal.toFixed(1)}%</span>
        </div>

        {data.totalAlwaysOnW > 5 && (
          <div className="mt-2 text-[10px] text-gray-500">
            Always on: {formatPower(data.totalAlwaysOnW)}
          </div>
        )}
      </div>

      {/* Expanded: circuit list */}
      {expanded && (
        <div className="border-t border-gray-800 bg-gray-950/40">
          <div className="divide-y divide-gray-800/50">
            {data.circuits
              .sort((a, b) => b.energy_month_kwh - a.energy_month_kwh)
              .map((c) => (
                <div key={c.equipment_id} className="px-4 py-2.5 flex items-center justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="text-xs text-gray-300 truncate">{c.name}</div>
                    <div className="text-[10px] text-gray-500 flex gap-3 mt-0.5">
                      <span>Today: {formatEnergy(c.energy_today_kwh)}</span>
                      <span>Month: {formatEnergy(c.energy_month_kwh)}</span>
                      {c.always_on_w > 5 && <span>Always on: {formatPower(c.always_on_w)}</span>}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                    {c.power_w > 5 && (
                      <span className="relative flex h-1.5 w-1.5">
                        <span
                          className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-50"
                          style={{ backgroundColor: meta.color }}
                        />
                        <span
                          className="relative inline-flex rounded-full h-1.5 w-1.5"
                          style={{ backgroundColor: meta.color }}
                        />
                      </span>
                    )}
                    <span className="text-xs font-mono text-gray-200">{formatPower(c.power_w)}</span>
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Expand indicator */}
      <div className="flex justify-center pb-1.5">
        <svg
          className={`w-4 h-4 text-gray-600 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </div>
  )
}

export default function Categories({ circuits }: Props) {
  const categoryData = useMemo(() => {
    const grouped: Record<Category, CircuitPower[]> = {
      'HVAC': [], 'EV Charging': [], 'Kitchen': [], 'Laundry': [],
      'Water': [], 'Lighting & Outlets': [], 'Other': [],
    }

    for (const circuit of circuits) {
      const cat = categorizeCircuit(circuit)
      grouped[cat].push(circuit)
    }

    const result: CategoryData[] = CATEGORY_ORDER
      .filter((cat) => grouped[cat].length > 0)
      .map((cat) => {
        const circs = grouped[cat]
        return {
          category: cat,
          circuits: circs,
          totalPowerW: circs.reduce((s, c) => s + c.power_w, 0),
          totalEnergyTodayKwh: circs.reduce((s, c) => s + c.energy_today_kwh, 0),
          totalEnergyMonthKwh: circs.reduce((s, c) => s + c.energy_month_kwh, 0),
          totalAlwaysOnW: circs.reduce((s, c) => s + c.always_on_w, 0),
        }
      })

    // Sort by monthly energy (highest first)
    result.sort((a, b) => b.totalEnergyMonthKwh - a.totalEnergyMonthKwh)
    return result
  }, [circuits])

  const totalEnergyMonth = categoryData.reduce((s, d) => s + d.totalEnergyMonthKwh, 0)
  const totalPowerNow = categoryData.reduce((s, d) => s + d.totalPowerW, 0)

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Summary header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-white">Energy Categories</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {categoryData.length} categories across {circuits.length} circuits
          </p>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <div>
            <span className="text-gray-500">Now: </span>
            <span className="font-mono font-bold text-white">{formatPower(totalPowerNow)}</span>
          </div>
          <div>
            <span className="text-gray-500">Month: </span>
            <span className="font-mono font-bold text-white">{formatEnergy(totalEnergyMonth)}</span>
          </div>
        </div>
      </div>

      {/* Category cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {categoryData.map((data) => (
          <CategoryCard
            key={data.category}
            data={data}
            totalEnergyMonth={totalEnergyMonth}
          />
        ))}
      </div>
    </div>
  )
}
