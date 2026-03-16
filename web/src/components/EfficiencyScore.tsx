import type { DashboardData } from '../lib/api'

interface Props {
  data: DashboardData
}

function computeScore(data: DashboardData): {
  score: number
  alwaysOnRatio: number
  peakToAvgRatio: number
  trendScore: number
  alwaysOnSavings: number
} {
  // 1. Always-on ratio (0-40 points): lower always-on % is better
  const alwaysOnRatio = data.total_power_w > 0
    ? data.always_on_w / data.total_power_w
    : 0
  // 0% always-on = 40pts, 50%+ = 0pts
  const alwaysOnScore = Math.max(0, 40 * (1 - alwaysOnRatio / 0.5))

  // 2. Peak-to-average ratio (0-30 points): lower is better (more consistent usage)
  // Use timeline data to find peak vs average
  let peakW = 0
  let sumW = 0
  const bucketCount = data.timeline.length || 1
  for (const bucket of data.timeline) {
    if (bucket.total_w > peakW) peakW = bucket.total_w
    sumW += bucket.total_w
  }
  const avgW = sumW / bucketCount
  const peakToAvgRatio = avgW > 0 ? peakW / avgW : 1
  // ratio of 1 (perfectly flat) = 30pts, ratio of 5+ = 0pts
  const peakAvgScore = Math.max(0, 30 * (1 - (peakToAvgRatio - 1) / 4))

  // 3. Usage trend (0-30 points): improving (down) trends are better
  let trendScore = 15 // neutral baseline
  if (data.trends.length > 0) {
    const avgChange = data.trends.reduce((sum, t) => sum + t.change_pct, 0) / data.trends.length
    // -20% avg change = 30pts, +20% = 0pts
    trendScore = Math.max(0, Math.min(30, 15 - avgChange * 0.75))
  }

  const score = Math.round(alwaysOnScore + peakAvgScore + trendScore)

  // Estimate savings from reducing always-on by half
  const hoursPerMonth = 730
  const rate = data.electricity_rate || 0.25
  const alwaysOnSavings = (data.always_on_w / 2 / 1000) * hoursPerMonth * rate

  return {
    score: Math.max(0, Math.min(100, score)),
    alwaysOnRatio,
    peakToAvgRatio,
    trendScore,
    alwaysOnSavings,
  }
}

function scoreColor(score: number): string {
  if (score >= 80) return 'text-green-400'
  if (score >= 50) return 'text-yellow-400'
  return 'text-red-400'
}

function scoreBgColor(score: number): string {
  if (score >= 80) return 'bg-green-500'
  if (score >= 50) return 'bg-yellow-500'
  return 'bg-red-500'
}

function scoreRingColor(score: number): string {
  if (score >= 80) return '#4ade80'
  if (score >= 50) return '#facc15'
  return '#f87171'
}

export default function EfficiencyScore({ data }: Props) {
  const { score, alwaysOnRatio, alwaysOnSavings } = computeScore(data)

  const alwaysOnPct = Math.round(alwaysOnRatio * 100)
  const circumference = 2 * Math.PI * 40
  const strokeDashoffset = circumference * (1 - score / 100)

  return (
    <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl px-4 py-3">
      <div className="flex items-center gap-5">
        {/* Circular gauge */}
        <div className="relative w-24 h-24 flex-shrink-0">
          <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
            {/* Background ring */}
            <circle
              cx="50" cy="50" r="40"
              fill="none"
              stroke="#1f2937"
              strokeWidth="8"
            />
            {/* Score ring */}
            <circle
              cx="50" cy="50" r="40"
              fill="none"
              stroke={scoreRingColor(score)}
              strokeWidth="8"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
              className="transition-all duration-1000"
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className={`text-2xl font-mono font-bold ${scoreColor(score)}`}>
              {score}
            </span>
            <span className="text-[9px] text-gray-500 uppercase">score</span>
          </div>
        </div>

        {/* Details */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide">
              Efficiency Score
            </h3>
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
              score >= 80
                ? 'bg-green-900/40 text-green-400'
                : score >= 50
                  ? 'bg-yellow-900/40 text-yellow-400'
                  : 'bg-red-900/40 text-red-400'
            }`}>
              {score >= 80 ? 'Good' : score >= 50 ? 'Fair' : 'Needs Work'}
            </span>
          </div>

          <p className="text-xs text-gray-400 leading-relaxed">
            Your always-on power is{' '}
            <span className={`font-mono font-medium ${alwaysOnPct > 30 ? 'text-amber-400' : 'text-gray-700 dark:text-gray-300'}`}>
              {alwaysOnPct}%
            </span>
            {' '}of total usage.
            {alwaysOnSavings > 1 && (
              <span>
                {' '}Reducing standby loads could save{' '}
                <span className="font-mono text-green-400">
                  ${alwaysOnSavings.toFixed(0)}/mo
                </span>.
              </span>
            )}
          </p>

          {/* Mini breakdown bar */}
          <div className="mt-2 flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden flex">
              <div
                className={`h-full ${scoreBgColor(score)} opacity-60`}
                style={{ width: `${score}%` }}
              />
            </div>
            <span className="text-[10px] text-gray-600 font-mono">{score}/100</span>
          </div>
        </div>
      </div>
    </div>
  )
}
