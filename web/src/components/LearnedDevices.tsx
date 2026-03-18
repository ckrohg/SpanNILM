import { useState } from 'react'
import type { CircuitPower, DetectedDevice } from '../lib/api'
import { setDeviceName, suggestDeviceNames, type DeviceSuggestion } from '../lib/api'

function formatPower(w: number): string {
  if (w >= 1000) return `${(w / 1000).toFixed(1)} kW`
  return `${Math.round(w)} W`
}

function formatDuration(min: number): string {
  if (min >= 1440) return `${(min / 1440).toFixed(1)} days`
  if (min >= 60) return `${(min / 60).toFixed(1)}h`
  return `${Math.round(min)}min`
}

function MiniSparkline({ curve }: { curve: number[] }) {
  const w = 60
  const h = 16
  const points = curve
    .map((v, i) => {
      const x = (i / (curve.length - 1)) * w
      const y = h - v * (h - 2) - 1
      return `${x},${y}`
    })
    .join(' ')
  return (
    <svg width={w} height={h} className="flex-shrink-0">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-emerald-500/70" />
    </svg>
  )
}

interface DeviceWithCircuit {
  device: DetectedDevice
  circuit: CircuitPower
  deviceIndex: number
}

interface Props {
  circuits: CircuitPower[]
}

export default function LearnedDevices({ circuits }: Props) {
  const [confirming, setConfirming] = useState<string | null>(null)
  const [expandedDetail, setExpandedDetail] = useState<string | null>(null)
  const [suggestions, setSuggestions] = useState<Record<string, DeviceSuggestion[]>>({})
  const [loadingSuggestions, setLoadingSuggestions] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set())

  // Collect all detected devices across shared circuits
  const allDevices: DeviceWithCircuit[] = []
  for (const circuit of circuits) {
    if (circuit.is_dedicated) continue
    for (let i = 0; i < (circuit.detected_devices?.length || 0); i++) {
      const d = circuit.detected_devices[i]
      // Skip already confirmed, suppressed, or very low confidence
      if (d.user_confirmed) continue
      if (d.name.includes('[SUPPRESSED]') || d.name === 'Not a real device' || d.name === 'Unidentified device') continue
      // Skip histogram-state devices (no template curve = not real shape detection)
      if (!d.template_curve || d.template_curve.length === 0) continue
      allDevices.push({ device: d, circuit, deviceIndex: i })
    }
  }

  // Deduplicate: if same device name appears multiple times on same circuit,
  // keep only the one with highest session count (it's likely the same device
  // detected at different power levels, not multiple identical devices)
  const seen = new Map<string, DeviceWithCircuit>()
  for (const item of allDevices) {
    const key = `${item.circuit.equipment_id}::${item.device.name}`
    const existing = seen.get(key)
    if (!existing || item.device.session_count > existing.device.session_count) {
      seen.set(key, item)
    }
  }
  const deduplicated = Array.from(seen.values())

  // Sort: high confidence first
  deduplicated.sort((a, b) => b.device.confidence - a.device.confidence)

  // Split into high confidence (ready for review) and learning
  const readyForReview = deduplicated.filter(d => d.device.confidence >= 0.7)
  const stillLearning = deduplicated.filter(d => d.device.confidence >= 0.3 && d.device.confidence < 0.7)

  if (readyForReview.length === 0 && stillLearning.length === 0) return null

  const handleConfirm = async (item: DeviceWithCircuit) => {
    const key = `${item.circuit.equipment_id}-${item.deviceIndex}`
    await setDeviceName(item.circuit.equipment_id, item.deviceIndex, item.device.name)
    setConfirmed(prev => new Set(prev).add(key))
  }

  const handleGetSuggestions = async (item: DeviceWithCircuit) => {
    const key = `${item.circuit.equipment_id}-${item.deviceIndex}`
    setLoadingSuggestions(key)
    try {
      const result = await suggestDeviceNames(item.circuit.equipment_id, item.deviceIndex)
      setSuggestions(prev => ({ ...prev, [key]: result }))
    } catch { /* ignore */ }
    setLoadingSuggestions(null)
  }

  const handleSelectSuggestion = async (item: DeviceWithCircuit, name: string) => {
    const key = `${item.circuit.equipment_id}-${item.deviceIndex}`
    await setDeviceName(item.circuit.equipment_id, item.deviceIndex, name)
    setConfirmed(prev => new Set(prev).add(key))
    setConfirming(null)
  }

  const renderDevice = (item: DeviceWithCircuit) => {
    const key = `${item.circuit.equipment_id}-${item.deviceIndex}`
    const isConfirmed = confirmed.has(key)
    const isConfirmingThis = confirming === key
    const deviceSuggestions = suggestions[key]
    const isLoadingSugs = loadingSuggestions === key

    if (isConfirmed) {
      return (
        <div key={key} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-green-900/10 border border-green-800/20">
          <span className="text-green-400 text-xs">✓ Confirmed</span>
          <span className="text-sm text-gray-700 dark:text-gray-300">{item.device.name}</span>
          <span className="text-xs text-gray-600">on {item.circuit.name}</span>
        </div>
      )
    }

    const isDetailExpanded = expandedDetail === key
    const d = item.device
    const energyPerDay = d.session_count > 0 && d.avg_duration_min > 0
      ? (d.power_w * d.avg_duration_min / 60) * (d.session_count / 30) / 1000 // rough kWh/day from 30 days
      : 0
    const costPerMonth = energyPerDay * 30 * (circuits[0]?.cost_today / Math.max(circuits[0]?.energy_today_kwh || 1, 0.01) || 0.34)

    return (
      <div key={key} className="rounded-lg bg-gray-50 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-800/50 overflow-hidden">
        {/* Header — clickable for detail */}
        <div
          className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800/30 transition-colors"
          onClick={() => setExpandedDetail(isDetailExpanded ? null : key)}
        >
          {d.template_curve && d.template_curve.length > 0 && (
            <MiniSparkline curve={d.template_curve} />
          )}
          <div className="flex-1 min-w-0">
            <div className="text-sm text-gray-800 dark:text-gray-200 font-medium">{d.name}</div>
            <div className="text-[10px] text-gray-500">
              {item.circuit.name} · ~{formatPower(d.power_w)} · {d.session_count} sessions · {Math.round(d.confidence * 100)}% confidence
            </div>
          </div>
          <svg className={`w-4 h-4 text-gray-500 transition-transform flex-shrink-0 ${isDetailExpanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>

        {/* Expanded consumption profile */}
        {isDetailExpanded && (
          <div className="border-t border-gray-200 dark:border-gray-800/50 px-3 py-3 bg-gray-100/50 dark:bg-gray-950/30">
            {/* Key stats grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
              <div>
                <div className="text-[9px] text-gray-500 uppercase">Avg Power</div>
                <div className="text-sm font-mono text-gray-800 dark:text-gray-200">{formatPower(d.power_w)}</div>
              </div>
              <div>
                <div className="text-[9px] text-gray-500 uppercase">Sessions</div>
                <div className="text-sm font-mono text-gray-800 dark:text-gray-200">{d.session_count} total</div>
              </div>
              <div>
                <div className="text-[9px] text-gray-500 uppercase">Avg Duration</div>
                <div className="text-sm font-mono text-gray-800 dark:text-gray-200">{formatDuration(d.avg_duration_min)}</div>
              </div>
              <div>
                <div className="text-[9px] text-gray-500 uppercase">Energy/Session</div>
                <div className="text-sm font-mono text-gray-800 dark:text-gray-200">{d.energy_per_session_wh.toFixed(0)} Wh</div>
              </div>
            </div>

            {/* Behavioral characteristics */}
            <div className="flex flex-wrap gap-2 mb-3">
              {d.is_cycling && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 border border-purple-300 dark:border-purple-800/40">
                  Cycling pattern
                </span>
              )}
              {d.num_phases > 2 && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 border border-blue-300 dark:border-blue-800/40">
                  {d.num_phases} power stages
                </span>
              )}
              {d.power_w < 50 && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-200 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
                  Low power / standby
                </span>
              )}
              {d.avg_duration_min > 120 && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border border-amber-300 dark:border-amber-800/40">
                  Long-running ({formatDuration(d.avg_duration_min)} avg)
                </span>
              )}
              {d.avg_duration_min < 10 && d.avg_duration_min > 0 && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 border border-red-300 dark:border-red-800/40">
                  Brief bursts ({formatDuration(d.avg_duration_min)})
                </span>
              )}
            </div>

            {/* Estimated cost impact */}
            {energyPerDay > 0.01 && (
              <div className="text-[10px] text-gray-500 mb-3">
                Est. ~{energyPerDay.toFixed(1)} kWh/day · ~{(energyPerDay * 30).toFixed(0)} kWh/month · ~${costPerMonth.toFixed(1)}/month
              </div>
            )}

            {/* Action buttons */}
            <div className="flex items-center gap-1.5">
              <button
                onClick={(e) => { e.stopPropagation(); handleConfirm(item) }}
                className="px-2.5 py-1 text-[11px] rounded bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400 border border-green-300 dark:border-green-800/50 hover:bg-green-200 dark:hover:bg-green-800/50 transition-colors"
              >
                ✓ Yes, correct
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setConfirming(isConfirmingThis ? null : key) }}
                className="px-2.5 py-1 text-[11px] rounded bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 border border-yellow-300 dark:border-yellow-800/50 hover:bg-yellow-200 dark:hover:bg-yellow-800/40 transition-colors"
              >
                Not quite right
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleSelectSuggestion(item, '[SUPPRESSED] I don\'t have this') }}
                className="px-2.5 py-1 text-[11px] rounded bg-gray-100 dark:bg-gray-800/50 text-gray-500 border border-gray-300 dark:border-gray-700/50 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
              >
                Don't have this
              </button>
            </div>
          </div>
        )}

        {/* Rename / suggestions panel */}
        {isConfirmingThis && (
          <div className="border-t border-gray-200 dark:border-gray-800/50 px-3 py-2.5 bg-gray-50 dark:bg-gray-950/50 space-y-2">
            {!deviceSuggestions && !isLoadingSugs && (
              <button
                onClick={() => handleGetSuggestions(item)}
                className="w-full px-3 py-2 text-xs rounded-lg bg-purple-900/30 border border-purple-700/40 text-purple-300 hover:bg-purple-800/40 transition-colors"
              >
                Ask AI for better suggestions
              </button>
            )}
            {isLoadingSugs && (
              <div className="text-xs text-gray-400 text-center py-2">Analyzing power pattern...</div>
            )}
            {deviceSuggestions && (
              <div className="space-y-1">
                {deviceSuggestions.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => handleSelectSuggestion(item, s.name)}
                    className="w-full text-left px-3 py-2 rounded-lg bg-gray-100 dark:bg-gray-800/40 border border-gray-300 dark:border-gray-700/40 hover:border-emerald-600/40 transition-colors"
                  >
                    <div className="text-xs text-gray-800 dark:text-gray-200">{s.name}</div>
                    <div className="text-[10px] text-gray-500 mt-0.5">{s.reasoning}</div>
                  </button>
                ))}
              </div>
            )}
            <input
              type="text"
              placeholder="Or type the correct name..."
              className="w-full px-3 py-1.5 text-xs rounded-lg bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:border-emerald-600"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.target as HTMLInputElement).value.trim()) {
                  handleSelectSuggestion(item, (e.target as HTMLInputElement).value.trim())
                }
              }}
            />
          </div>
        )}
      </div>
    )
  }

  return (
    <section>
      <h2 className="text-sm font-medium text-gray-400 mb-2">
        Learned Devices
      </h2>
      <div className="space-y-4">
        {readyForReview.length > 0 && (
          <div>
            <div className="text-[10px] text-emerald-400/70 uppercase tracking-wider mb-2 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              Ready for review ({readyForReview.length})
            </div>
            <div className="space-y-1.5">
              {readyForReview.map(renderDevice)}
            </div>
          </div>
        )}

        {stillLearning.length > 0 && (
          <div>
            <div className="text-[10px] text-yellow-400/70 uppercase tracking-wider mb-2 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-yellow-400/60" />
              Still learning ({stillLearning.length})
            </div>
            <div className="space-y-1.5">
              {stillLearning.slice(0, 5).map(renderDevice)}
              {stillLearning.length > 5 && (
                <div className="text-xs text-gray-600 text-center py-1">
                  +{stillLearning.length - 5} more devices still being identified...
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
