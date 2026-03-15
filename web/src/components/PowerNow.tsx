import { useState } from 'react'
import type { CircuitPower } from '../lib/api'

function formatPower(w: number): string {
  if (w >= 1000) return `${(w / 1000).toFixed(1)} kW`
  return `${Math.round(w)} W`
}

function formatDuration(min: number): string {
  if (min >= 60) return `${(min / 60).toFixed(1)}h`
  return `${Math.round(min)}min`
}

function MiniSparkline({ curve }: { curve: number[] }) {
  const w = 80
  const h = 20
  const points = curve
    .map((v, i) => {
      const x = (i / (curve.length - 1)) * w
      const y = h - v * (h - 2) - 1
      return `${x},${y}`
    })
    .join(' ')
  return (
    <svg width={w} height={h} className="flex-shrink-0">
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className="text-emerald-500/70"
      />
    </svg>
  )
}

export default function PowerNow({ circuits }: { circuits: CircuitPower[] }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const sorted = [...circuits].sort((a, b) => b.energy_today_kwh - a.energy_today_kwh)
  const maxEnergy = sorted[0]?.energy_today_kwh || 1

  if (!sorted.length) {
    return (
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-6 text-gray-500 text-center">
        No circuit data
      </div>
    )
  }

  return (
    <div className="space-y-1">
      {sorted.map((circuit) => {
        const pct = maxEnergy > 0 ? (circuit.energy_today_kwh / maxEnergy) * 100 : 0
        const isActive = circuit.power_w > 5
        const isExpanded = expanded === circuit.equipment_id
        const devices = circuit.detected_devices || []
        const t = circuit.temporal
        const corrs = circuit.correlations || []

        return (
          <div key={circuit.equipment_id} className="bg-gray-900/40 rounded-lg border border-gray-800/50 overflow-hidden">
            {/* Circuit header row */}
            <div
              className="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-gray-800/30 transition-colors"
              onClick={() => setExpanded(isExpanded ? null : circuit.equipment_id)}
            >
              <span
                className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                  isActive ? 'bg-green-400' : 'bg-gray-700'
                }`}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-medium truncate ${isActive ? 'text-gray-100' : 'text-gray-400'}`}>
                    {circuit.name}
                  </span>
                  {circuit.is_dedicated && circuit.device_type && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/60 text-blue-300 flex-shrink-0 border border-blue-800/50">
                      {circuit.device_type}
                    </span>
                  )}
                </div>
                {/* Energy bar */}
                <div className="mt-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${circuit.is_dedicated ? 'bg-blue-500' : 'bg-emerald-500'}`}
                    style={{ width: `${Math.max(pct, 0.5)}%`, opacity: circuit.energy_today_kwh > 0.01 ? 0.8 : 0.1 }}
                  />
                </div>
              </div>
              <div className="flex items-center gap-4 flex-shrink-0 text-right">
                <span className={`text-sm font-mono ${isActive ? 'text-gray-200' : 'text-gray-600'}`}>
                  {isActive ? formatPower(circuit.power_w) : '--'}
                </span>
                <span className="text-xs text-gray-500 w-16">
                  {circuit.energy_today_kwh > 0.01 ? `${circuit.energy_today_kwh.toFixed(1)} kWh` : '--'}
                </span>
                <svg
                  className={`w-4 h-4 text-gray-600 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
            </div>

            {/* Expanded: nested devices + details */}
            {isExpanded && (
              <div className="border-t border-gray-800/50 bg-gray-950/50">
                {/* Devices nested under circuit */}
                {devices.length > 0 && (
                  <div className="px-4 py-2 space-y-1">
                    <div className="text-[10px] text-gray-600 uppercase tracking-wider mb-1.5">
                      Detected Devices
                    </div>
                    {devices.map((d, i) => {
                      const conf = d.confidence
                      const confColor = conf >= 0.7 ? 'text-green-400' : conf >= 0.4 ? 'text-yellow-400' : 'text-gray-500'
                      const hasShapeData = d.template_curve && d.template_curve.length > 0
                      return (
                        <div key={i} className="pl-5 py-1.5 text-xs">
                          <div className="flex items-center gap-3">
                            <span className="w-1.5 h-1.5 rounded-full bg-gray-600 flex-shrink-0" />
                            {hasShapeData && <MiniSparkline curve={d.template_curve!} />}
                            <span className="text-gray-300 flex-1">
                              {d.name.replace(/_/g, ' ')}
                            </span>
                            <span className="text-gray-500 font-mono">~{formatPower(d.power_w)}</span>
                            <span className={`font-mono ${confColor}`}>{Math.round(conf * 100)}%</span>
                          </div>
                          {hasShapeData && (
                            <div className="flex items-center gap-3 pl-5 mt-0.5 text-[11px] text-gray-500">
                              <span>{d.session_count} sessions</span>
                              <span>{formatDuration(d.avg_duration_min)} avg</span>
                              <span>{d.energy_per_session_wh.toFixed(0)} Wh/session</span>
                              {d.is_cycling && (
                                <span className="px-1.5 py-0 rounded bg-purple-900/50 text-purple-300 border border-purple-800/50">
                                  cycling
                                </span>
                              )}
                              {d.num_phases > 2 && (
                                <span className="text-gray-600">{d.num_phases}-phase</span>
                              )}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}

                {/* Stats */}
                <div className="px-4 py-2 border-t border-gray-800/30 text-xs space-y-1.5">
                  <div className="flex gap-6 text-gray-400">
                    <span>Today: <span className="text-gray-300">{circuit.energy_today_kwh.toFixed(1)} kWh</span> <span className="text-green-500">${circuit.cost_today.toFixed(2)}</span></span>
                    <span>Month: <span className="text-gray-300">{circuit.energy_month_kwh.toFixed(1)} kWh</span> <span className="text-green-500">${circuit.cost_month.toFixed(2)}</span></span>
                    {circuit.always_on_w > 0 && (
                      <span>Always on: <span className="text-amber-400">{formatPower(circuit.always_on_w)}</span></span>
                    )}
                  </div>

                  {/* Temporal */}
                  {t && t.total_sessions > 0 && (
                    <div className="text-gray-500">
                      {t.total_sessions} sessions, {t.total_hours_on.toFixed(0)}h active ({(t.duty_cycle * 100).toFixed(1)}%)
                      {t.has_cycling && t.cycle_period_min && (
                        <span className="ml-2 text-purple-400">
                          Cycles every {Math.round(t.cycle_period_min)}min
                        </span>
                      )}
                    </div>
                  )}

                  {/* Correlations */}
                  {corrs.length > 0 && (
                    <div className="text-gray-500">
                      Linked: {corrs.map((c, i) => (
                        <span key={i} className="text-cyan-400/80">
                          {c.name} ({Math.round(c.score * 100)}%){i < corrs.length - 1 ? ', ' : ''}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
