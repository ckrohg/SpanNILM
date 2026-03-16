import { useState } from 'react'
import type { CircuitPower, DetectedDevice } from '../lib/api'
import { setDeviceName, suggestDeviceNames, type DeviceSuggestion } from '../lib/api'

function formatPower(w: number): string {
  if (w >= 1000) return `${(w / 1000).toFixed(1)} kW`
  return `${Math.round(w)} W`
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

    return (
      <div key={key} className="rounded-lg bg-gray-50 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-800/50 overflow-hidden">
        <div className="flex items-center gap-3 px-3 py-2.5">
          {item.device.template_curve && item.device.template_curve.length > 0 && (
            <MiniSparkline curve={item.device.template_curve} />
          )}
          <div className="flex-1 min-w-0">
            <div className="text-sm text-gray-800 dark:text-gray-200 font-medium">{item.device.name}</div>
            <div className="text-[10px] text-gray-500">
              {item.circuit.name} · ~{formatPower(item.device.power_w)} · {item.device.session_count} sessions · {Math.round(item.device.confidence * 100)}% confidence
            </div>
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            <button
              onClick={() => handleConfirm(item)}
              className="px-2.5 py-1 text-[11px] rounded bg-green-900/40 text-green-400 border border-green-800/50 hover:bg-green-800/50 transition-colors"
            >
              ✓ Yes, correct
            </button>
            <button
              onClick={() => setConfirming(isConfirmingThis ? null : key)}
              className="px-2.5 py-1 text-[11px] rounded bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 border border-yellow-300 dark:border-yellow-800/50 hover:bg-yellow-200 dark:hover:bg-yellow-800/40 transition-colors"
            >
              Not quite right
            </button>
            <button
              onClick={() => handleSelectSuggestion(item, '[SUPPRESSED] I don\'t have this')}
              className="px-2.5 py-1 text-[11px] rounded bg-gray-100 dark:bg-gray-800/50 text-gray-500 border border-gray-300 dark:border-gray-700/50 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
            >
              Don't have this
            </button>
          </div>
        </div>

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
