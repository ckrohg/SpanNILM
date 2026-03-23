import { useState } from 'react'
import type { CircuitPower } from '../lib/api'

interface Props {
  alwaysOnW: number
  totalPowerW: number
  totalEnergyTodayKwh: number
  circuits: CircuitPower[]
  electricityRate: number
}

function formatPower(w: number): string {
  if (w >= 1000) return `${(w / 1000).toFixed(1)} kW`
  return `${Math.round(w)} W`
}

export default function AlwaysOnCard({
  alwaysOnW,
  totalPowerW,
  totalEnergyTodayKwh,
  circuits,
  electricityRate,
}: Props) {
  const [expanded, setExpanded] = useState(false)

  const pctOfPower = totalPowerW > 0 ? Math.round((alwaysOnW / totalPowerW) * 100) : 0
  const hoursToday = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })).getHours() + new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' })).getMinutes() / 60
  const alwaysOnKwh = hoursToday > 0 ? (alwaysOnW * hoursToday) / 1000 : 0
  const alwaysOnMonthlyKwh = alwaysOnW * 24 * 30 / 1000
  const alwaysOnMonthlyCost = alwaysOnMonthlyKwh * electricityRate
  const alwaysOnAnnualCost = alwaysOnMonthlyCost * 12

  // Per-circuit always-on breakdown, sorted by always-on power
  const circuitBreakdown = circuits
    .filter((c) => c.always_on_w > 0.5)
    .sort((a, b) => b.always_on_w - a.always_on_w)

  const maxAlwaysOn = circuitBreakdown[0]?.always_on_w || 1

  return (
    <div className="bg-amber-900/20 border border-amber-800/40 rounded-xl overflow-hidden">
      {/* Header — clickable to expand */}
      <div
        className="px-4 py-3 cursor-pointer hover:bg-amber-900/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-amber-700 dark:text-amber-400/70 uppercase tracking-wide font-medium mb-1">
              Always On
            </div>
            <div className="text-2xl font-mono font-bold text-amber-700 dark:text-amber-300">
              {formatPower(alwaysOnW)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm text-amber-700 dark:text-amber-400/80 font-mono">
              {pctOfPower}% of current
            </div>
            <div className="text-xs text-gray-500">
              ~${alwaysOnMonthlyCost.toFixed(0)}/mo (${alwaysOnAnnualCost.toFixed(0)}/yr)
            </div>
          </div>
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="text-[10px] text-gray-500">
            {circuitBreakdown.length} circuits with standby power — click to see breakdown
          </span>
          <svg
            className={`w-4 h-4 text-amber-500/50 transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </div>

      {/* Expanded breakdown */}
      {expanded && (
        <div className="border-t border-amber-800/30 bg-gray-50 dark:bg-gray-950/50 px-4 py-3">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">
            Always-On Power by Circuit
          </div>
          <div className="space-y-2">
            {circuitBreakdown.map((circuit) => {
              const pct = alwaysOnW > 0 ? (circuit.always_on_w / alwaysOnW) * 100 : 0
              const barPct = (circuit.always_on_w / maxAlwaysOn) * 100
              const monthlyCost = (circuit.always_on_w * 24 * 30 / 1000) * electricityRate
              const annualCost = monthlyCost * 12

              return (
                <div key={circuit.equipment_id} className="text-xs">
                  <div className="flex items-center justify-between mb-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-gray-700 dark:text-gray-300 font-medium">{circuit.name}</span>
                      {circuit.is_dedicated && circuit.device_type && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-blue-900/40 text-blue-400 border border-blue-800/30">
                          {circuit.device_type}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-right">
                      <span className="font-mono text-amber-700 dark:text-amber-300">{formatPower(circuit.always_on_w)}</span>
                      <span className="text-gray-500 w-10">{pct.toFixed(0)}%</span>
                      <span className="text-green-500/70 w-14">${monthlyCost.toFixed(1)}/mo</span>
                    </div>
                  </div>
                  <div className="h-1 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-amber-500/60 rounded-full"
                      style={{ width: `${barPct}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>

          {/* Insight */}
          <div className="mt-4 bg-amber-900/10 border border-amber-800/30 rounded-lg px-3 py-2">
            <p className="text-xs text-amber-700 dark:text-amber-400/80 leading-relaxed">
              {circuitBreakdown.length > 0 && (
                <>
                  Your biggest always-on load is <span className="text-amber-700 dark:text-amber-300 font-medium">{circuitBreakdown[0].name}</span> at {formatPower(circuitBreakdown[0].always_on_w)}.
                  {' '}Reducing standby power across all circuits by just 25% would save{' '}
                  <span className="text-green-400 font-medium">
                    ~${(alwaysOnAnnualCost * 0.25).toFixed(0)}/year
                  </span>.
                  {' '}Common culprits: device chargers, entertainment systems, older appliances with high standby draw.
                </>
              )}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
