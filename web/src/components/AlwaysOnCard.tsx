interface Props {
  alwaysOnW: number
  totalPowerW: number
  totalEnergyTodayKwh: number
}

function formatPower(w: number): string {
  if (w >= 1000) return `${(w / 1000).toFixed(1)} kW`
  return `${Math.round(w)} W`
}

export default function AlwaysOnCard({ alwaysOnW, totalPowerW, totalEnergyTodayKwh }: Props) {
  const pctOfPower = totalPowerW > 0 ? Math.round((alwaysOnW / totalPowerW) * 100) : 0
  // Rough estimate: always-on energy = always_on_w * hours_so_far_today / 1000
  const hoursToday = new Date().getHours() + new Date().getMinutes() / 60
  const alwaysOnKwh = hoursToday > 0 ? (alwaysOnW * hoursToday) / 1000 : 0
  const pctOfEnergy = totalEnergyTodayKwh > 0
    ? Math.round((alwaysOnKwh / totalEnergyTodayKwh) * 100)
    : 0

  return (
    <div className="bg-amber-900/20 border border-amber-800/40 rounded-xl px-4 py-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs text-amber-400/70 uppercase tracking-wide font-medium mb-1">
            Always On
          </div>
          <div className="text-2xl font-mono font-bold text-amber-300">
            {formatPower(alwaysOnW)}
          </div>
        </div>
        <div className="text-right">
          <div className="text-sm text-amber-400/80 font-mono">
            {pctOfPower}% of current
          </div>
          <div className="text-xs text-gray-500">
            ~{alwaysOnKwh.toFixed(1)} kWh today ({pctOfEnergy}%)
          </div>
        </div>
      </div>
    </div>
  )
}
