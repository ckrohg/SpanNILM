import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import type { PowerEvent } from '../lib/api'

interface TimelinePoint {
  time: string
  power: number
}

function eventsToTimeline(events: PowerEvent[]): TimelinePoint[] {
  if (!events.length) return []

  // Sort chronologically and build cumulative power over time
  const sorted = [...events].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  )

  let currentPower = 0
  const points: TimelinePoint[] = []

  for (const ev of sorted) {
    currentPower += ev.delta_w
    if (currentPower < 0) currentPower = 0
    const date = new Date(ev.timestamp)
    points.push({
      time: date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'America/New_York' }),
      power: Math.round(currentPower),
    })
  }

  return points
}

export default function PowerTimeline({ events }: { events: PowerEvent[] }) {
  const data = eventsToTimeline(events)

  if (!data.length) {
    return (
      <div className="h-48 rounded-xl bg-gray-900/50 border border-gray-800 flex items-center justify-center text-gray-500">
        No timeline data
      </div>
    )
  }

  return (
    <div className="h-48 rounded-xl bg-gray-900/50 border border-gray-800 p-4">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id="powerGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="time"
            stroke="#4b5563"
            fontSize={10}
            tickLine={false}
          />
          <YAxis
            stroke="#4b5563"
            fontSize={10}
            tickLine={false}
            tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}kW` : `${v}W`)}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: '0.5rem',
              fontSize: '12px',
            }}
            formatter={(value: number) => [`${value}W`, 'Power']}
          />
          <Area
            type="stepAfter"
            dataKey="power"
            stroke="#3b82f6"
            fill="url(#powerGrad)"
            strokeWidth={1.5}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
