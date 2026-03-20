import { useState, useMemo } from 'react'
import type { CircuitPower, DetectedDevice, DeviceSuggestion } from '../lib/api'
import { setDeviceName, suggestDeviceNames } from '../lib/api'

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

// --- Device type grid for visual picker ---

interface DeviceType {
  name: string
  icon: string
  category: string
}

const DEVICE_TYPES: DeviceType[] = [
  // Cooling
  { name: "Refrigerator", icon: "\u{1F9CA}", category: "Cooling" },
  { name: "Chest Freezer", icon: "\u{2744}\u{FE0F}", category: "Cooling" },
  { name: "Mini Fridge", icon: "\u{1F9CA}", category: "Cooling" },
  { name: "Wine Cooler", icon: "\u{1F377}", category: "Cooling" },
  { name: "Dehumidifier", icon: "\u{1F4A7}", category: "Cooling" },
  { name: "Window AC", icon: "\u{1F300}", category: "Cooling" },
  // Heating
  { name: "Space Heater", icon: "\u{1F525}", category: "Heating" },
  { name: "Water Heater", icon: "\u{1F6BF}", category: "Heating" },
  { name: "Heat Lamp", icon: "\u{1F4A1}", category: "Heating" },
  { name: "Stock Tank Heater", icon: "\u{1F525}", category: "Heating" },
  // Motors & Pumps
  { name: "Sump Pump", icon: "\u{2B06}\u{FE0F}", category: "Motors" },
  { name: "Well Pump", icon: "\u{1F4A7}", category: "Motors" },
  { name: "Circulation Pump", icon: "\u{1F504}", category: "Motors" },
  { name: "Garage Door", icon: "\u{1F697}", category: "Motors" },
  { name: "Ceiling Fan", icon: "\u{1F300}", category: "Motors" },
  { name: "Exhaust Fan", icon: "\u{1F4A8}", category: "Motors" },
  // Electronics
  { name: "Computer", icon: "\u{1F4BB}", category: "Electronics" },
  { name: "TV / Entertainment", icon: "\u{1F4FA}", category: "Electronics" },
  { name: "Gaming Console", icon: "\u{1F3AE}", category: "Electronics" },
  { name: "Router / Network", icon: "\u{1F4E1}", category: "Electronics" },
  { name: "Server", icon: "\u{1F5A5}\u{FE0F}", category: "Electronics" },
  // Kitchen
  { name: "Coffee Maker", icon: "\u{2615}", category: "Kitchen" },
  { name: "Toaster", icon: "\u{1F35E}", category: "Kitchen" },
  { name: "Microwave", icon: "\u{1F4E1}", category: "Kitchen" },
  // Lighting
  { name: "LED Lighting", icon: "\u{1F4A1}", category: "Lighting" },
  { name: "Outdoor Lights", icon: "\u{1F3EE}", category: "Lighting" },
  // Other
  { name: "Iron", icon: "\u{1F454}", category: "Other" },
  { name: "Vacuum", icon: "\u{1F9F9}", category: "Other" },
  { name: "Hair Dryer", icon: "\u{1F487}", category: "Other" },
  { name: "Aquarium", icon: "\u{1F420}", category: "Other" },
  { name: "Power Tools", icon: "\u{1F527}", category: "Other" },
  { name: "EV Charger", icon: "\u{1F50C}", category: "Other" },
]

const CATEGORIES = [...new Set(DEVICE_TYPES.map(d => d.category))]

// --- Consumption pattern helpers ---

function getPatternLabel(d: DetectedDevice): string {
  if (d.is_cycling) return 'cycling'
  if (d.avg_duration_min > 120) return 'sustained'
  if (d.avg_duration_min < 10 && d.avg_duration_min > 0) return 'brief'
  return 'intermittent'
}

function getFrequency(d: DetectedDevice): string {
  if (d.session_count <= 0) return ''
  const perDay = d.session_count / 30 // assumes 30 days of data
  if (perDay >= 1) return `${perDay.toFixed(1)}x/day`
  return `${(perDay * 7).toFixed(1)}x/week`
}

// --- Visual device type picker ---

interface DeviceTypePickerProps {
  onSelect: (name: string) => void
  onAskAI: () => void
  onDismiss: () => void
  aiSuggestions: DeviceSuggestion[] | null
  aiLoading: boolean
  aiReasoning: string | null
}

function DeviceTypePicker({ onSelect, onAskAI, onDismiss, aiSuggestions, aiLoading, aiReasoning }: DeviceTypePickerProps) {
  const [search, setSearch] = useState('')
  const [customName, setCustomName] = useState('')

  const filtered = useMemo(() => {
    if (!search.trim()) return DEVICE_TYPES
    const q = search.toLowerCase()
    return DEVICE_TYPES.filter(d =>
      d.name.toLowerCase().includes(q) || d.category.toLowerCase().includes(q)
    )
  }, [search])

  const groupedByCategory = useMemo(() => {
    const groups: Record<string, DeviceType[]> = {}
    for (const cat of CATEGORIES) {
      const items = filtered.filter(d => d.category === cat)
      if (items.length > 0) groups[cat] = items
    }
    return groups
  }, [filtered])

  return (
    <div className="border-t border-gray-200 dark:border-gray-800/50 px-3 py-3 bg-gray-50 dark:bg-gray-950/50 space-y-3">
      {/* AI reasoning banner */}
      {aiReasoning && (
        <div className="text-[11px] text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800/40 rounded-lg px-3 py-2">
          <span className="font-medium">AI reasoning:</span> {aiReasoning}
        </div>
      )}

      {/* AI suggestions row */}
      {aiSuggestions && aiSuggestions.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[10px] text-purple-500 uppercase tracking-wider">AI Suggestions</div>
          <div className="flex flex-wrap gap-1.5">
            {aiSuggestions.map((s, i) => (
              <button
                key={i}
                onClick={() => onSelect(s.name)}
                className="px-3 py-1.5 text-xs rounded-lg bg-purple-50 dark:bg-purple-900/30 border border-purple-200 dark:border-purple-700/40 text-purple-700 dark:text-purple-300 hover:bg-purple-100 dark:hover:bg-purple-800/40 hover:border-purple-400 dark:hover:border-purple-600 transition-colors"
                title={s.reasoning}
              >
                {s.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Search + Ask AI row */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter device types..."
            className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:border-emerald-600 transition-colors"
          />
        </div>
        {!aiSuggestions && !aiLoading && (
          <button
            onClick={onAskAI}
            className="px-3 py-1.5 text-xs rounded-lg bg-purple-100 dark:bg-purple-900/30 border border-purple-300 dark:border-purple-700/40 text-purple-700 dark:text-purple-300 hover:bg-purple-200 dark:hover:bg-purple-800/40 transition-colors whitespace-nowrap flex items-center gap-1.5"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Ask AI
          </button>
        )}
        {aiLoading && (
          <div className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-400">
            <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Analyzing...
          </div>
        )}
      </div>

      {/* Device type grid by category */}
      <div className="max-h-64 overflow-y-auto space-y-2.5 pr-1">
        {Object.entries(groupedByCategory).map(([category, devices]) => (
          <div key={category}>
            <div className="text-[9px] text-gray-500 uppercase tracking-wider mb-1.5">{category}</div>
            <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-1.5">
              {devices.map((dt) => (
                <button
                  key={dt.name}
                  onClick={() => onSelect(dt.name)}
                  className="flex flex-col items-center gap-0.5 px-2 py-2 rounded-lg bg-white dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700/50 hover:border-emerald-500 dark:hover:border-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-colors group"
                >
                  <span className="text-xl leading-none group-hover:scale-110 transition-transform">{dt.icon}</span>
                  <span className="text-[9px] text-gray-600 dark:text-gray-400 group-hover:text-emerald-700 dark:group-hover:text-emerald-300 text-center leading-tight transition-colors">{dt.name}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="text-xs text-gray-500 text-center py-3">No matching device types</div>
        )}
      </div>

      {/* Custom name input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={customName}
          onChange={(e) => setCustomName(e.target.value)}
          placeholder="Or type a custom name..."
          className="flex-1 px-3 py-1.5 text-xs rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-600 focus:outline-none focus:border-emerald-600 transition-colors"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && customName.trim()) {
              onSelect(customName.trim())
            }
          }}
        />
        {customName.trim() && (
          <button
            onClick={() => onSelect(customName.trim())}
            className="px-3 py-1.5 text-xs rounded-lg bg-emerald-700 text-white hover:bg-emerald-600 transition-colors"
          >
            Save
          </button>
        )}
      </div>

      {/* Quick actions */}
      <div className="flex gap-2">
        <button
          onClick={() => onSelect('Unidentified device')}
          className="flex-1 px-2.5 py-1.5 text-[10px] rounded-lg bg-gray-100 dark:bg-gray-800/60 border border-gray-300 dark:border-gray-700/50 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
        >
          I don't know
        </button>
        <button
          onClick={onDismiss}
          className="px-2.5 py-1.5 text-[10px] rounded-lg bg-gray-100 dark:bg-gray-800/40 border border-gray-300 dark:border-gray-700/50 text-gray-500 hover:text-gray-300 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// --- Main component ---

interface DeviceWithCircuit {
  device: DetectedDevice
  circuit: CircuitPower
  deviceIndex: number
}

interface Props {
  circuits: CircuitPower[]
}

export default function LearnedDevices({ circuits }: Props) {
  const [pickingDevice, setPickingDevice] = useState<string | null>(null)
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
  // keep only the one with highest session count
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

  const handleSelectName = async (item: DeviceWithCircuit, name: string) => {
    const key = `${item.circuit.equipment_id}-${item.deviceIndex}`
    await setDeviceName(item.circuit.equipment_id, item.deviceIndex, name)
    setConfirmed(prev => new Set(prev).add(key))
    setPickingDevice(null)
  }

  const renderDevice = (item: DeviceWithCircuit) => {
    const key = `${item.circuit.equipment_id}-${item.deviceIndex}`
    const isConfirmed = confirmed.has(key)
    const isPickingThis = pickingDevice === key
    const deviceSuggestions = suggestions[key] || null
    const isLoadingSugs = loadingSuggestions === key
    const d = item.device

    if (isConfirmed) {
      return (
        <div key={key} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-green-900/10 border border-green-800/20">
          <span className="text-green-400 text-xs">Confirmed</span>
          <span className="text-sm text-gray-700 dark:text-gray-300">{d.name}</span>
          <span className="text-xs text-gray-600">on {item.circuit.name}</span>
        </div>
      )
    }

    const isDetailExpanded = expandedDetail === key
    const pattern = getPatternLabel(d)
    const freq = getFrequency(d)

    // Pick first AI suggestion reasoning as overall reasoning
    const aiReasoning = deviceSuggestions && deviceSuggestions.length > 0
      ? deviceSuggestions[0].reasoning
      : null

    return (
      <div key={key} className="rounded-lg bg-gray-50 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-800/50 overflow-hidden">
        {/* Header with inline consumption badges */}
        <div
          className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800/30 transition-colors"
          onClick={() => setExpandedDetail(isDetailExpanded ? null : key)}
        >
          {d.template_curve && d.template_curve.length > 0 && (
            <MiniSparkline curve={d.template_curve} />
          )}
          <div className="flex-1 min-w-0">
            <div className="text-sm text-gray-800 dark:text-gray-200 font-medium">{d.name}</div>
            <div className="text-[10px] text-gray-500 mb-1">
              {item.circuit.name} · {Math.round(d.confidence * 100)}% confidence
            </div>
            {/* Inline consumption badges -- always visible */}
            <div className="flex flex-wrap gap-1.5">
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800/40 font-mono">
                {formatPower(d.power_w)}
              </span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${
                pattern === 'cycling'
                  ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 border-purple-300 dark:border-purple-800/40'
                  : pattern === 'sustained'
                    ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-300 dark:border-amber-800/40'
                    : pattern === 'brief'
                      ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 border-red-300 dark:border-red-800/40'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-300 dark:border-gray-700'
              }`}>
                {pattern}
              </span>
              {d.avg_duration_min > 0 && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 border border-blue-300 dark:border-blue-800/40 font-mono">
                  {formatDuration(d.avg_duration_min)} avg
                </span>
              )}
              {freq && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 border border-gray-300 dark:border-gray-700 font-mono">
                  {freq}
                </span>
              )}
            </div>
          </div>
          <svg className={`w-4 h-4 text-gray-500 transition-transform flex-shrink-0 ${isDetailExpanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>

        {/* Expanded detail panel */}
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
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-1.5">
              <button
                onClick={(e) => { e.stopPropagation(); handleConfirm(item) }}
                className="px-2.5 py-1 text-[11px] rounded bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-400 border border-green-300 dark:border-green-800/50 hover:bg-green-200 dark:hover:bg-green-800/50 transition-colors"
              >
                Yes, correct
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setPickingDevice(isPickingThis ? null : key) }}
                className={`px-2.5 py-1 text-[11px] rounded border transition-colors ${
                  isPickingThis
                    ? 'bg-yellow-200 dark:bg-yellow-800/50 text-yellow-800 dark:text-yellow-300 border-yellow-400 dark:border-yellow-600'
                    : 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 border-yellow-300 dark:border-yellow-800/50 hover:bg-yellow-200 dark:hover:bg-yellow-800/40'
                }`}
              >
                Not quite right
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleSelectName(item, '[SUPPRESSED] I don\'t have this') }}
                className="px-2.5 py-1 text-[11px] rounded bg-gray-100 dark:bg-gray-800/50 text-gray-500 border border-gray-300 dark:border-gray-700/50 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
              >
                Don't have this
              </button>
            </div>
          </div>
        )}

        {/* Visual device type picker */}
        {isPickingThis && (
          <DeviceTypePicker
            onSelect={(name) => handleSelectName(item, name)}
            onAskAI={() => handleGetSuggestions(item)}
            onDismiss={() => setPickingDevice(null)}
            aiSuggestions={deviceSuggestions}
            aiLoading={isLoadingSugs}
            aiReasoning={aiReasoning}
          />
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
