import { useEffect, useState } from 'react'
import {
  CircuitConfig,
  getCircuitConfigs,
  updateCircuitConfig,
} from '../lib/api'

const DEVICE_TYPES = [
  'HVAC Compressor',
  'HVAC Fan',
  'Heat Pump',
  'Mini Split',
  'Water Heater',
  'EV Charger',
  'Well Pump',
  'Pool Pump',
  'Refrigerator',
  'Oven / Range',
  'Dryer',
  'Washer',
  'Dishwasher',
  'Garage Door Opener',
  'Space Heater',
  'Sump Pump',
  'Other',
]

function CircuitRow({
  circuit,
  onSave,
}: {
  circuit: CircuitConfig
  onSave: (id: string, isDedicated: boolean, deviceType: string | null, label: string | null) => void
}) {
  const [isDedicated, setIsDedicated] = useState(circuit.is_dedicated)
  const [deviceType, setDeviceType] = useState(circuit.dedicated_device_type || '')
  const [label, setLabel] = useState(circuit.user_label || '')
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  const hasChanged =
    isDedicated !== circuit.is_dedicated ||
    deviceType !== (circuit.dedicated_device_type || '') ||
    label !== (circuit.user_label || '')

  useEffect(() => {
    setDirty(hasChanged)
  }, [hasChanged])

  const handleSave = async () => {
    setSaving(true)
    await onSave(
      circuit.equipment_id,
      isDedicated,
      isDedicated ? deviceType || null : null,
      label || null
    )
    setSaving(false)
    setDirty(false)
  }

  return (
    <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="font-medium text-sm">{circuit.name}</h3>
          {circuit.circuit_number && (
            <p className="text-xs text-gray-600 mt-0.5 font-mono">
              {circuit.circuit_number}
            </p>
          )}
        </div>
        {dirty && (
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-1 text-xs rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 transition-colors"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        )}
      </div>

      {/* Label */}
      <div className="mb-3">
        <label className="text-xs text-gray-500 block mb-1">Custom Label</label>
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={circuit.name}
          className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>

      {/* Dedicated toggle */}
      <div className="flex items-center gap-3 mb-3">
        <label className="text-xs text-gray-500">Circuit type:</label>
        <button
          onClick={() => { setIsDedicated(false); setDeviceType('') }}
          className={`px-3 py-1 text-xs rounded-lg transition-colors ${
            !isDedicated
              ? 'bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white'
              : 'bg-gray-100 dark:bg-gray-800/50 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          }`}
        >
          Shared
        </button>
        <button
          onClick={() => setIsDedicated(true)}
          className={`px-3 py-1 text-xs rounded-lg transition-colors ${
            isDedicated
              ? 'bg-blue-600/30 text-blue-400 border border-blue-600/50'
              : 'bg-gray-100 dark:bg-gray-800/50 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          }`}
        >
          Dedicated
        </button>
      </div>

      {/* Device type selector (only when dedicated) */}
      {isDedicated && (
        <div>
          <label className="text-xs text-gray-500 block mb-1">
            What device is on this circuit?
          </label>
          <select
            value={deviceType}
            onChange={(e) => setDeviceType(e.target.value)}
            className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          >
            <option value="">Select device type...</option>
            {DEVICE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          {isDedicated && deviceType && (
            <p className="text-xs text-green-500/70 mt-1">
              All power on this circuit will be attributed to {deviceType}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default function Circuits() {
  const [circuits, setCircuits] = useState<CircuitConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getCircuitConfigs()
      .then(setCircuits)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async (
    equipmentId: string,
    isDedicated: boolean,
    deviceType: string | null,
    userLabel: string | null
  ) => {
    const updated = await updateCircuitConfig(equipmentId, {
      is_dedicated: isDedicated,
      dedicated_device_type: deviceType,
      user_label: userLabel,
    })
    setCircuits((prev) =>
      prev.map((c) => (c.equipment_id === equipmentId ? updated : c))
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-400">
        Loading circuits...
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-800 rounded-xl p-4 text-red-300">
        {error}
      </div>
    )
  }

  const dedicated = circuits.filter((c) => c.is_dedicated)
  const shared = circuits.filter((c) => !c.is_dedicated)

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold mb-1">Circuits</h2>
        <p className="text-sm text-gray-500">
          Mark circuits as dedicated (single device) to skip disaggregation and improve detection accuracy.
        </p>
      </div>

      {dedicated.length > 0 && (
        <section>
          <h3 className="text-xs font-medium text-blue-400 uppercase tracking-wide mb-3">
            Dedicated ({dedicated.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {dedicated.map((c) => (
              <CircuitRow key={c.equipment_id} circuit={c} onSave={handleSave} />
            ))}
          </div>
        </section>
      )}

      <section>
        <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
          {dedicated.length > 0 ? `Shared (${shared.length})` : `All Circuits (${circuits.length})`}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {shared.map((c) => (
            <CircuitRow key={c.equipment_id} circuit={c} onSave={handleSave} />
          ))}
        </div>
      </section>
    </div>
  )
}
