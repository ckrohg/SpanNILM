import type { DeviceCluster } from '../lib/api'

function getDeviceName(device: DeviceCluster): string {
  return device.label || device.matches[0]?.device_name || `Unknown #${device.cluster_id}`
}

function getCategory(device: DeviceCluster): string {
  return device.matches[0]?.category || 'Unknown'
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color =
    pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-500'

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-400 w-8 text-right">{pct}%</span>
    </div>
  )
}

export default function DeviceCard({ device }: { device: DeviceCluster }) {
  const name = getDeviceName(device)
  const category = getCategory(device)
  const topMatch = device.matches[0]
  const power = device.is_on ? device.current_power_w : device.mean_power_w
  const powerStr = power >= 1000 ? `${(power / 1000).toFixed(1)} kW` : `${Math.round(power)} W`

  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4 hover:border-gray-700 transition-colors">
      <div className="flex items-start justify-between mb-2">
        <div>
          <h3 className="font-medium text-sm">{name}</h3>
          <p className="text-xs text-gray-500">{device.circuit_name}</p>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-mono">{powerStr}</span>
          <span
            className={`w-2 h-2 rounded-full ${device.is_on ? 'bg-green-500' : 'bg-gray-600'}`}
          />
        </div>
      </div>

      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs px-2 py-0.5 rounded-full bg-gray-800 text-gray-400">
          {category}
        </span>
        <span className="text-xs text-gray-500">
          {device.observation_count} observations
        </span>
        {device.mean_duration_s && (
          <span className="text-xs text-gray-500">
            ~{Math.round(device.mean_duration_s / 60)} min avg
          </span>
        )}
      </div>

      {topMatch && <ConfidenceBar value={topMatch.confidence} />}
    </div>
  )
}
