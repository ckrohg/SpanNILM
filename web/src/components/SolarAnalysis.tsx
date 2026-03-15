import type { DashboardData } from '../lib/api'

interface Props {
  data: DashboardData
}

// Conservative New England average: 10kW system generates ~35 kWh/day
const SYSTEM_SIZE_KW = 10
const DAILY_GENERATION_KWH = 35
const SOLAR_START_HOUR = 10
const SOLAR_END_HOUR = 15

export default function SolarAnalysis({ data }: Props) {
  const { timeline, electricity_rate, total_energy_month_kwh, bill_projection } = data

  if (timeline.length === 0) return null

  // Sum power during solar hours (10am-3pm) vs total across timeline
  let solarHoursWh = 0
  let totalWh = 0
  let solarBucketCount = 0
  let totalBucketCount = 0

  for (const bucket of timeline) {
    const hour = new Date(bucket.timestamp).getHours()
    const bucketWh = bucket.total_w // power for this bucket period
    totalWh += bucketWh
    totalBucketCount++

    if (hour >= SOLAR_START_HOUR && hour < SOLAR_END_HOUR) {
      solarHoursWh += bucketWh
      solarBucketCount++
    }
  }

  // Average daily usage from bill projection or month data
  const daysElapsed = bill_projection?.days_elapsed ?? 1
  const dailyAvgKwh = bill_projection?.daily_avg_kwh
    ?? (total_energy_month_kwh / Math.max(daysElapsed, 1))

  // Daytime usage fraction
  const daytimeFraction = totalWh > 0 ? solarHoursWh / totalWh : 0
  const daytimeKwhPerDay = dailyAvgKwh * daytimeFraction

  // Solar match: what % of daytime usage could solar cover
  const solarMatchPct = daytimeKwhPerDay > 0
    ? Math.min(100, Math.round((DAILY_GENERATION_KWH / daytimeKwhPerDay) * 100))
    : 0

  // Overall offset: what % of total daily usage could be covered
  const overallOffsetPct = dailyAvgKwh > 0
    ? Math.min(100, Math.round((DAILY_GENERATION_KWH / dailyAvgKwh) * 100))
    : 0

  // Annual savings estimate
  const rate = electricity_rate || 0.25
  const annualGenerationKwh = DAILY_GENERATION_KWH * 365
  const annualUsageKwh = dailyAvgKwh * 365
  const usableGenerationKwh = Math.min(annualGenerationKwh, annualUsageKwh)
  const annualSavings = usableGenerationKwh * rate

  // Average solar hours power
  const avgDaytimePowerW = solarBucketCount > 0
    ? Math.round(solarHoursWh / solarBucketCount)
    : 0

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-5">
      <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-4">
        Solar Readiness Analysis
      </h3>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-5">
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Solar Match</div>
          <div className="text-2xl font-mono font-bold text-yellow-400">
            {solarMatchPct}%
          </div>
          <div className="text-[10px] text-gray-600">of daytime usage</div>
        </div>
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Total Offset</div>
          <div className="text-2xl font-mono font-bold text-white">
            {overallOffsetPct}%
          </div>
          <div className="text-[10px] text-gray-600">of all usage</div>
        </div>
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Annual Savings</div>
          <div className="text-2xl font-mono font-bold text-green-400">
            ${annualSavings.toFixed(0)}
          </div>
          <div className="text-[10px] text-gray-600">at ${rate.toFixed(2)}/kWh</div>
        </div>
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Daytime Avg</div>
          <div className="text-2xl font-mono font-bold text-white">
            {avgDaytimePowerW >= 1000
              ? `${(avgDaytimePowerW / 1000).toFixed(1)} kW`
              : `${avgDaytimePowerW} W`
            }
          </div>
          <div className="text-[10px] text-gray-600">10am-3pm avg</div>
        </div>
      </div>

      {/* Usage profile bar */}
      <div className="mb-4">
        <div className="flex justify-between text-[10px] text-gray-600 mb-1">
          <span>Peak solar hours (10am-3pm)</span>
          <span>{Math.round(daytimeFraction * 100)}% of daily usage</span>
        </div>
        <div className="h-3 bg-gray-800 rounded-full overflow-hidden flex">
          <div
            className="h-full bg-yellow-500/60 rounded-l-full"
            style={{ width: `${Math.round(daytimeFraction * 100)}%` }}
          />
          <div
            className="h-full bg-gray-700/60 rounded-r-full"
            style={{ width: `${100 - Math.round(daytimeFraction * 100)}%` }}
          />
        </div>
        <div className="flex justify-between text-[10px] mt-0.5">
          <span className="text-yellow-500/70">Daytime: {daytimeKwhPerDay.toFixed(1)} kWh/day</span>
          <span className="text-gray-600">Night: {(dailyAvgKwh - daytimeKwhPerDay).toFixed(1)} kWh/day</span>
        </div>
      </div>

      {/* System estimate */}
      <div className="bg-gray-800/30 rounded-lg px-4 py-3 border border-gray-800/50">
        <p className="text-xs text-gray-400 leading-relaxed">
          A <span className="text-white font-medium">{SYSTEM_SIZE_KW} kW system</span> in New England
          would generate ~{DAILY_GENERATION_KWH} kWh/day on average, offsetting{' '}
          <span className="text-yellow-400 font-mono font-medium">~{overallOffsetPct}%</span>
          {' '}of your total usage and saving an estimated{' '}
          <span className="text-green-400 font-mono font-medium">${annualSavings.toFixed(0)}/year</span>.
        </p>
      </div>
    </div>
  )
}
