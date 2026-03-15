import { useState } from 'react'
import type { CircuitPower } from '../lib/api'

function formatPower(w: number): string {
  if (w >= 1000) return `${(w / 1000).toFixed(1)} kW`
  return `${Math.round(w)} W`
}

function confidenceColor(c: number): string {
  if (c >= 0.7) return 'bg-green-900/50 text-green-400 border-green-800'
  if (c >= 0.4) return 'bg-yellow-900/50 text-yellow-400 border-yellow-800'
  return 'bg-gray-800/50 text-gray-400 border-gray-700'
}

export default function PowerNow({ circuits }: { circuits: CircuitPower[] }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const sorted = [...circuits].sort((a, b) => b.energy_today_kwh - a.energy_today_kwh)
  const maxEnergy = sorted[0]?.energy_today_kwh || 1

  if (!sorted.length) {
    return (
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-6 text-gray-500 text-center">
        No circuit data available
      </div>
    )
  }

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
      <div className="space-y-1">
        {sorted.map((circuit) => {
          const pct = maxEnergy > 0 ? (circuit.energy_today_kwh / maxEnergy) * 100 : 0
          const isActive = circuit.power_w > 5
          const isExpanded = expanded === circuit.equipment_id
          const barColor = circuit.is_dedicated ? 'bg-blue-500' : 'bg-emerald-500'
          const barBg = circuit.is_dedicated ? 'bg-blue-500/5' : 'bg-gray-500/5'
          const devices = circuit.detected_devices || []
          const t = circuit.temporal
          const corrs = circuit.correlations || []

          return (
            <div key={circuit.equipment_id}>
              <div
                className={`flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer hover:bg-gray-800/30 transition-colors ${barBg}`}
                onClick={() => setExpanded(isExpanded ? null : circuit.equipment_id)}
              >
                <div className="w-48 min-w-[12rem] flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full flex-shrink-0 ${
                      isActive ? (circuit.is_dedicated ? 'bg-blue-400' : 'bg-green-400') : 'bg-gray-700'
                    }`}
                  />
                  <span className={`text-sm truncate ${isActive ? 'text-gray-200' : 'text-gray-400'}`}>
                    {circuit.name}
                  </span>
                  {circuit.is_dedicated && circuit.device_type && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/50 text-blue-400 flex-shrink-0">
                      {circuit.device_type}
                    </span>
                  )}
                </div>
                <div className="flex-1 h-3 bg-gray-800/50 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${barColor}`}
                    style={{ width: `${Math.max(pct, 1)}%`, opacity: circuit.energy_today_kwh > 0.01 ? 0.7 : 0.1 }}
                  />
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className={`text-xs font-mono w-14 text-right ${isActive ? 'text-gray-300' : 'text-gray-600'}`}>
                    {isActive ? formatPower(circuit.power_w) : '--'}
                  </span>
                  <span className="text-xs text-gray-500 w-16 text-right">
                    {circuit.energy_today_kwh > 0.01 ? `${circuit.energy_today_kwh.toFixed(1)} kWh` : '--'}
                  </span>
                </div>
              </div>

              {/* Detected devices pills */}
              {!circuit.is_dedicated && devices.length > 0 && !isExpanded && (
                <div className="flex flex-wrap gap-1 pl-12 pb-1 pt-0.5">
                  {devices.slice(0, 4).map((d, i) => (
                    <span
                      key={i}
                      className={`text-[10px] px-1.5 py-0.5 rounded border ${confidenceColor(d.confidence)}`}
                    >
                      {d.name.replace(/_/g, ' ')} ~{formatPower(d.power_w)}
                    </span>
                  ))}
                  {devices.length > 4 && (
                    <span className="text-[10px] text-gray-600">+{devices.length - 4} more</span>
                  )}
                </div>
              )}

              {/* Expanded detail panel */}
              {isExpanded && (
                <div className="ml-6 mr-3 mb-2 mt-1 p-3 rounded-lg bg-gray-800/40 border border-gray-800 text-xs space-y-2">
                  {/* Energy */}
                  <div className="flex gap-6">
                    <div>
                      <span className="text-gray-500">Today:</span>{' '}
                      <span className="text-gray-300">{circuit.energy_today_kwh.toFixed(1)} kWh</span>{' '}
                      <span className="text-green-500">${circuit.cost_today.toFixed(2)}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">Month:</span>{' '}
                      <span className="text-gray-300">{circuit.energy_month_kwh.toFixed(1)} kWh</span>{' '}
                      <span className="text-green-500">${circuit.cost_month.toFixed(2)}</span>
                    </div>
                    {circuit.always_on_w > 0 && (
                      <div>
                        <span className="text-gray-500">Always on:</span>{' '}
                        <span className="text-amber-400">{formatPower(circuit.always_on_w)}</span>
                      </div>
                    )}
                  </div>

                  {/* Temporal info */}
                  {t && t.total_sessions > 0 && (
                    <div className="space-y-1">
                      <div className="flex gap-4">
                        <span className="text-gray-500">
                          {t.total_sessions} sessions, {t.total_hours_on.toFixed(0)}h on ({(t.duty_cycle * 100).toFixed(1)}% duty)
                        </span>
                      </div>
                      {t.has_cycling && t.cycle_period_min && (
                        <div className="flex items-center gap-2">
                          <span className="px-1.5 py-0.5 rounded bg-purple-900/40 text-purple-400 border border-purple-800">
                            CYCLES
                          </span>
                          <span className="text-gray-400">
                            every {Math.round(t.cycle_period_min)}min
                            {t.cycle_on_min ? `, ON ${Math.round(t.cycle_on_min)}min` : ''}
                            {t.cycle_regularity !== null ? `, ${Math.round(t.cycle_regularity * 100)}% regular` : ''}
                          </span>
                        </div>
                      )}
                      {t.peak_hours.length > 0 && (
                        <div>
                          <span className="text-gray-500">Peak hours: </span>
                          <span className="text-gray-400">
                            {t.peak_hours.map(h => `${h}:00`).join(', ')}
                          </span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Correlations */}
                  {corrs.length > 0 && (
                    <div>
                      <span className="text-gray-500">Correlated with: </span>
                      {corrs.map((c, i) => (
                        <span key={i} className="text-cyan-400">
                          {c.name} ({Math.round(c.score * 100)}%)
                          {i < corrs.length - 1 ? ', ' : ''}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Detected devices (full list when expanded) */}
                  {devices.length > 0 && (
                    <div>
                      <span className="text-gray-500">Detected power states: </span>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {devices.map((d, i) => (
                          <span
                            key={i}
                            className={`px-1.5 py-0.5 rounded border ${confidenceColor(d.confidence)}`}
                          >
                            {d.name.replace(/_/g, ' ')} ~{formatPower(d.power_w)} ({Math.round(d.confidence * 100)}%)
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
