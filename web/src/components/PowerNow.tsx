import { useState } from 'react'
import type { CircuitPower, DeviceSuggestion } from '../lib/api'
import { suggestDeviceNames, setDeviceName } from '../lib/api'

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

interface NamingModalProps {
  equipmentId: string
  clusterId: number
  currentName: string
  onClose: () => void
  onNameSet: (name: string) => void
}

function NamingModal({ equipmentId, clusterId, currentName, onClose, onNameSet }: NamingModalProps) {
  const [suggestions, setSuggestions] = useState<DeviceSuggestion[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [customName, setCustomName] = useState('')
  const [saving, setSaving] = useState(false)
  const [hasFetched, setHasFetched] = useState(false)

  const fetchSuggestions = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await suggestDeviceNames(equipmentId, clusterId)
      setSuggestions(result)
      setHasFetched(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to get suggestions')
    } finally {
      setLoading(false)
    }
  }

  const saveName = async (name: string) => {
    setSaving(true)
    try {
      await setDeviceName(equipmentId, clusterId, name)
      onNameSet(name)
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to save name')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-700 rounded-xl max-w-md w-full p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Name this device</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <p className="text-sm text-gray-400">
          Current: <span className="text-gray-300">{currentName}</span>
        </p>

        {/* AI Suggestions */}
        {!hasFetched && !loading && (
          <button
            onClick={fetchSuggestions}
            className="w-full px-4 py-2.5 text-sm rounded-lg bg-purple-900/50 border border-purple-700/50 text-purple-300 hover:bg-purple-800/50 transition-colors flex items-center justify-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Ask AI for suggestions
          </button>
        )}

        {loading && (
          <div className="flex items-center justify-center py-4 text-gray-400 text-sm gap-2">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Analyzing power pattern...
          </div>
        )}

        {suggestions.length > 0 && (
          <div className="space-y-2">
            <div className="text-[10px] text-gray-500 uppercase tracking-wider">AI Suggestions</div>
            {suggestions.map((s, i) => (
              <button
                key={i}
                onClick={() => saveName(s.name)}
                disabled={saving}
                className="w-full text-left px-3 py-2.5 rounded-lg bg-gray-100 dark:bg-gray-800/60 border border-gray-300 dark:border-gray-700/50 hover:border-emerald-600/50 hover:bg-gray-800 transition-colors group"
              >
                <div className="text-sm text-gray-800 dark:text-gray-200 group-hover:text-emerald-600 dark:group-hover:text-emerald-300 transition-colors">
                  {s.name}
                </div>
                <div className="text-[11px] text-gray-500 mt-0.5">{s.reasoning}</div>
              </button>
            ))}
          </div>
        )}

        {error && (
          <div className="text-xs text-red-400 bg-red-900/20 border border-red-800/50 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        {/* Custom name input */}
        <div className="space-y-2">
          <div className="text-[10px] text-gray-500 uppercase tracking-wider">Custom Name</div>
          <div className="flex gap-2">
            <input
              type="text"
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              placeholder="Type a custom name..."
              className="flex-1 px-3 py-2 text-sm rounded-lg bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:border-emerald-600 transition-colors"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && customName.trim()) {
                  saveName(customName.trim())
                }
              }}
            />
            <button
              onClick={() => customName.trim() && saveName(customName.trim())}
              disabled={!customName.trim() || saving}
              className="px-4 py-2 text-sm rounded-lg bg-emerald-700 text-white hover:bg-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Save
            </button>
          </div>
        </div>

        {/* Quick actions */}
        <div className="flex flex-col gap-2 pt-1">
          <div className="flex gap-2">
            <button
              onClick={() => saveName('Unidentified device')}
              disabled={saving}
              className="flex-1 px-3 py-2 text-xs rounded-lg bg-gray-100 dark:bg-gray-800/60 border border-gray-300 dark:border-gray-700/50 text-gray-400 hover:text-gray-200 hover:border-gray-600 transition-colors"
            >
              I don't know what this is
            </button>
            <button
              onClick={() => saveName('Not a real device')}
              disabled={saving}
              className="flex-1 px-3 py-2 text-xs rounded-lg bg-gray-100 dark:bg-gray-800/60 border border-gray-300 dark:border-gray-700/50 text-gray-400 hover:text-red-400 hover:border-red-800 transition-colors"
            >
              This isn't a device
            </button>
          </div>
          <button
            onClick={() => saveName('[SUPPRESSED] I don\'t have this')}
            disabled={saving}
            className="w-full px-3 py-2 text-xs rounded-lg bg-orange-900/20 border border-orange-800/40 text-orange-400/80 hover:text-orange-300 hover:border-orange-700 transition-colors"
          >
            I don't have one of these — stop detecting it
          </button>
        </div>
      </div>
    </div>
  )
}

interface PowerNowProps {
  circuits: CircuitPower[]
  onCircuitClick?: (equipmentId: string) => void
  onDeviceClick?: (equipmentId: string, clusterId: number) => void
}

export default function PowerNow({ circuits, onCircuitClick, onDeviceClick }: PowerNowProps) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [namingTarget, setNamingTarget] = useState<{
    equipmentId: string
    clusterId: number
    name: string
  } | null>(null)
  const [renamedDevices, setRenamedDevices] = useState<Record<string, string>>({})

  const sorted = [...circuits].sort((a, b) => b.energy_today_kwh - a.energy_today_kwh)
  const maxEnergy = sorted[0]?.energy_today_kwh || 1

  if (!sorted.length) {
    return (
      <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-6 text-gray-500 text-center">
        No circuit data
      </div>
    )
  }

  return (
    <>
      <div className="space-y-1">
        {sorted.map((circuit) => {
          const pct = maxEnergy > 0 ? (circuit.energy_today_kwh / maxEnergy) * 100 : 0
          const isActive = circuit.power_w > 5
          const isExpanded = expanded === circuit.equipment_id
          const devices = circuit.detected_devices || []
          const t = circuit.temporal
          const corrs = circuit.correlations || []

          return (
            <div key={circuit.equipment_id} className="bg-gray-50 dark:bg-gray-900/40 rounded-lg border border-gray-200 dark:border-gray-800/50 overflow-hidden">
              {/* Circuit header row */}
              <div
                className="flex items-center gap-2 sm:gap-3 px-2.5 sm:px-4 py-2 sm:py-2.5 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800/30 transition-colors"
                onClick={() => setExpanded(isExpanded ? null : circuit.equipment_id)}
              >
                <span
                  className={`w-2 h-2 sm:w-2.5 sm:h-2.5 rounded-full flex-shrink-0 ${
                    isActive ? 'bg-green-400' : 'bg-gray-700'
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 sm:gap-2">
                    <span className={`text-xs sm:text-sm font-medium truncate max-w-[120px] sm:max-w-none ${isActive ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 dark:text-gray-400'}`}>
                      {circuit.name}
                    </span>
                    {circuit.is_dedicated && circuit.device_type && (
                      <span className="text-[9px] sm:text-[10px] px-1 sm:px-1.5 py-0.5 rounded bg-blue-900/60 text-blue-300 flex-shrink-0 border border-blue-800/50 hidden sm:inline">
                        {circuit.device_type}
                      </span>
                    )}
                  </div>
                  {/* Energy bar */}
                  <div className="mt-1 h-1 sm:h-1.5 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${circuit.is_dedicated ? 'bg-blue-500' : 'bg-emerald-500'}`}
                      style={{ width: `${Math.max(pct, 0.5)}%`, opacity: circuit.energy_today_kwh > 0.01 ? 0.8 : 0.1 }}
                    />
                  </div>
                </div>
                <div className="flex items-center gap-2 sm:gap-4 flex-shrink-0 text-right">
                  <span className={`text-xs sm:text-sm font-mono ${isActive ? 'text-gray-800 dark:text-gray-200' : 'text-gray-400 dark:text-gray-600'}`}>
                    {isActive ? formatPower(circuit.power_w) : '--'}
                  </span>
                  <span className="text-[10px] sm:text-xs text-gray-500 w-12 sm:w-16 hidden sm:block">
                    {circuit.energy_today_kwh > 0.01 ? `${circuit.energy_today_kwh.toFixed(1)} kWh` : '--'}
                  </span>
                  {onCircuitClick && (
                    <button
                      onClick={(e) => { e.stopPropagation(); onCircuitClick(circuit.equipment_id) }}
                      className="p-1 text-gray-600 hover:text-gray-300 transition-colors hidden sm:block"
                      title="View details"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </button>
                  )}
                  <svg
                    className={`w-3.5 h-3.5 sm:w-4 sm:h-4 text-gray-600 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                    fill="none" viewBox="0 0 24 24" stroke="currentColor"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </div>

              {/* Expanded: nested devices + details */}
              {isExpanded && (
                <div className="border-t border-gray-200 dark:border-gray-800/50 bg-gray-50 dark:bg-gray-950/50">
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
                        const deviceKey = `${circuit.equipment_id}-${i}`
                        const displayName = renamedDevices[deviceKey] || d.name
                        return (
                          <div key={i} className={`pl-3 sm:pl-5 py-2 text-xs border-b border-gray-800/30 last:border-0 ${d.suppressed_on_other_circuit ? 'opacity-60' : ''}`}>
                            <div className="flex items-center gap-2 sm:gap-3">
                              {hasShapeData && <MiniSparkline curve={d.template_curve!} />}
                              <span
                                className={`text-gray-800 dark:text-gray-200 font-medium flex-1 ${onDeviceClick ? 'cursor-pointer hover:text-emerald-300 transition-colors' : ''}`}
                                onClick={(e) => {
                                  if (onDeviceClick) {
                                    e.stopPropagation()
                                    onDeviceClick(circuit.equipment_id, i)
                                  }
                                }}
                              >
                                {displayName.replace(/_/g, ' ')}
                                {d.user_confirmed && (
                                  <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-green-900/40 text-green-400 border border-green-800/40" title="User confirmed">confirmed</span>
                                )}
                                {d.suppressed_on_other_circuit && (
                                  <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-orange-900/30 text-orange-400 border border-orange-800/40" title="This device type was suppressed on another circuit">suppressed elsewhere</span>
                                )}
                              </span>
                              <span className="text-gray-500 font-mono">~{formatPower(d.power_w)}</span>
                            </div>
                            {/* Feedback buttons */}
                            <div className="flex items-center gap-2 mt-1.5 pl-0 sm:pl-[84px]">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  // Confirm = save current name as user-confirmed
                                  setDeviceName(circuit.equipment_id, i, displayName)
                                    .then(() => {
                                      setRenamedDevices(prev => ({ ...prev, [deviceKey]: displayName + ' ✓' }))
                                      setTimeout(() => setRenamedDevices(prev => ({ ...prev, [deviceKey]: displayName })), 2000)
                                    })
                                }}
                                className="px-2 py-0.5 rounded text-[10px] bg-green-900/30 text-green-400 border border-green-800/50 hover:bg-green-800/40 transition-colors"
                                title="Confirm this is correct"
                              >
                                ✓ Correct
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setNamingTarget({
                                    equipmentId: circuit.equipment_id,
                                    clusterId: i,
                                    name: displayName,
                                  })
                                }}
                                className="px-2 py-0.5 rounded text-[10px] bg-yellow-900/30 text-yellow-400 border border-yellow-800/50 hover:bg-yellow-800/40 transition-colors"
                                title="This is wrong — rename it"
                              >
                                ✗ Wrong
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setDeviceName(circuit.equipment_id, i, 'Unknown device')
                                    .then(() => setRenamedDevices(prev => ({ ...prev, [deviceKey]: 'Unknown device' })))
                                }}
                                className="px-2 py-0.5 rounded text-[10px] bg-gray-800/50 text-gray-500 border border-gray-700/50 hover:bg-gray-700/40 transition-colors"
                                title="Not a real device"
                              >
                                Not a device
                              </button>
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
                                  <span className="text-gray-600">{d.num_phases} power stages</span>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}

                  {/* Stats */}
                  <div className="px-4 py-2 border-t border-gray-200 dark:border-gray-800/30 text-xs space-y-1.5">
                    <div className="flex gap-6 text-gray-500 dark:text-gray-400">
                      <span>Today: <span className="text-gray-700 dark:text-gray-300">{circuit.energy_today_kwh.toFixed(1)} kWh</span> <span className="text-green-500">${circuit.cost_today.toFixed(2)}</span></span>
                      <span>Month: <span className="text-gray-700 dark:text-gray-300">{circuit.energy_month_kwh.toFixed(1)} kWh</span> <span className="text-green-500">${circuit.cost_month.toFixed(2)}</span></span>
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

      {/* Naming modal */}
      {namingTarget && (
        <NamingModal
          equipmentId={namingTarget.equipmentId}
          clusterId={namingTarget.clusterId}
          currentName={namingTarget.name}
          onClose={() => setNamingTarget(null)}
          onNameSet={(name) => {
            const key = `${namingTarget.equipmentId}-${namingTarget.clusterId}`
            setRenamedDevices((prev) => ({ ...prev, [key]: name }))
          }}
        />
      )}
    </>
  )
}
