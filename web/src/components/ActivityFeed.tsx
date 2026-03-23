import type { PowerEvent } from '../lib/api'

function formatTime(ts: string): string {
  const d = new Date(ts)
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'America/New_York' })
}

function formatPower(watts: number): string {
  const abs = Math.abs(watts)
  return abs >= 1000 ? `${(abs / 1000).toFixed(1)} kW` : `${Math.round(abs)} W`
}

export default function ActivityFeed({ events }: { events: PowerEvent[] }) {
  const recent = events.slice(0, 20)

  if (!recent.length) {
    return (
      <div className="text-gray-500 text-sm py-4 text-center">
        No recent activity
      </div>
    )
  }

  return (
    <div className="space-y-1">
      {recent.map((ev, i) => (
        <div
          key={i}
          className="flex items-center justify-between py-1.5 px-3 rounded-lg hover:bg-gray-900/40 text-sm"
        >
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                ev.event_type === 'on' ? 'bg-green-500' : 'bg-red-500'
              }`}
            />
            <span className="text-gray-300">{ev.circuit_name}</span>
            <span className="text-gray-500">
              {ev.event_type === 'on' ? 'turned on' : 'turned off'}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-gray-400 font-mono text-xs">
              {ev.event_type === 'on' ? '+' : '-'}{formatPower(ev.delta_w)}
            </span>
            <span className="text-gray-500 text-xs">{formatTime(ev.timestamp)}</span>
          </div>
        </div>
      ))}
    </div>
  )
}
