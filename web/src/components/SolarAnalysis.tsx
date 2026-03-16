import { useEffect, useState } from 'react'
import type { DashboardData } from '../lib/api'
import { getSettings } from '../lib/api'

interface Props {
  data: DashboardData
}

const SOLAR_START_HOUR = 10
const SOLAR_END_HOUR = 15

export default function SolarAnalysis({ data }: Props) {
  const [solarPayment, setSolarPayment] = useState(0)
  const [solarAnnualKwh, setSolarAnnualKwh] = useState(0)
  const [netMetering, setNetMetering] = useState(true)

  useEffect(() => {
    getSettings().then((s) => {
      setSolarPayment(parseFloat(s.solar_monthly_payment || '0'))
      setSolarAnnualKwh(parseFloat(s.solar_annual_kwh || '0'))
      setNetMetering(s.net_metering !== 'no')
    }).catch(() => {})
  }, [])

  const { timeline, electricity_rate, bill_projection, tou_schedule } = data

  if (timeline.length === 0) return null

  const rate = electricity_rate || 0.14
  const hasTou = tou_schedule?.enabled === true

  // Calculate effective solar rate — solar production during peak hours is worth more
  let solarEffectiveRate = rate
  if (hasTou && tou_schedule) {
    // Solar peak production (10am-3pm) typically overlaps with mid-peak or peak
    // Weight the rate by approximate solar production distribution
    const peakRate = tou_schedule.peak?.rate ?? rate
    const midPeakRate = tou_schedule.mid_peak?.rate ?? rate
    const offPeakRate = tou_schedule.off_peak?.rate ?? rate
    // ~80% of solar production is during mid-peak/peak hours, ~20% off-peak edges
    solarEffectiveRate = peakRate * 0.3 + midPeakRate * 0.5 + offPeakRate * 0.2
  }
  const hasQuote = solarPayment > 0 && solarAnnualKwh > 0

  // Usage analysis from timeline
  let solarHoursW = 0
  let totalW = 0
  let solarBuckets = 0
  let totalBuckets = 0

  for (const bucket of timeline) {
    const hour = new Date(bucket.timestamp).getHours()
    totalW += bucket.total_w
    totalBuckets++
    if (hour >= SOLAR_START_HOUR && hour < SOLAR_END_HOUR) {
      solarHoursW += bucket.total_w
      solarBuckets++
    }
  }

  const daysElapsed = bill_projection?.days_elapsed ?? 15
  const dailyAvgKwh = bill_projection?.daily_avg_kwh ?? (data.total_energy_month_kwh / Math.max(daysElapsed, 1))
  const annualUsageKwh = dailyAvgKwh * 365
  const currentAnnualCost = annualUsageKwh * rate
  const currentMonthlyCost = dailyAvgKwh * 30 * rate

  // Daytime usage fraction
  const daytimeFraction = totalW > 0 ? solarHoursW / totalW : 0.35
  const daytimeKwhPerDay = dailyAvgKwh * daytimeFraction

  // If user has a solar quote, show the real financials
  if (hasQuote) {
    const solarDailyKwh = solarAnnualKwh / 365
    const solarMonthlyKwh = solarAnnualKwh / 12
    const annualPayment = solarPayment * 12

    // How much of the solar production offsets usage?
    let annualSavingsFromSolar: number
    let remainingGridKwh: number

    // Use effective solar rate (accounts for TOU value of solar production)
    const effectiveRate = hasTou ? solarEffectiveRate : rate

    if (netMetering) {
      // Net metering: all production counts at retail rate, even excess
      const effectiveOffset = Math.min(solarAnnualKwh, annualUsageKwh)
      annualSavingsFromSolar = effectiveOffset * effectiveRate
      // If solar > usage, excess is credited but capped at annual usage
      if (solarAnnualKwh > annualUsageKwh) {
        annualSavingsFromSolar = annualUsageKwh * effectiveRate // bill goes to $0
      }
      remainingGridKwh = Math.max(0, annualUsageKwh - solarAnnualKwh)
    } else {
      // No net metering: only save on what you use during solar hours
      const usableSolar = Math.min(solarDailyKwh, daytimeKwhPerDay)
      annualSavingsFromSolar = usableSolar * 365 * effectiveRate
      remainingGridKwh = annualUsageKwh - (usableSolar * 365)
    }

    const remainingGridCost = remainingGridKwh * rate
    const totalWithSolar = annualPayment + (remainingGridCost > 0 ? remainingGridCost : 0)
    const netAnnualSavings = currentAnnualCost - totalWithSolar
    const netMonthlySavings = netAnnualSavings / 12

    const solarOffsetPct = Math.round((solarAnnualKwh / annualUsageKwh) * 100)
    const breakevenMonths = netMonthlySavings > 0 ? 0 : Math.ceil(Math.abs(netAnnualSavings) / (annualSavingsFromSolar / 12))

    return (
      <div className="bg-gray-900/50 border border-yellow-900/30 rounded-xl p-5">
        <h3 className="text-xs font-medium text-yellow-400 uppercase tracking-wide mb-4">
          Solar Quote Analysis
        </h3>

        {/* Big savings number */}
        <div className="text-center mb-5">
          <div className={`text-4xl font-mono font-bold ${netMonthlySavings >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {netMonthlySavings >= 0 ? '+' : ''}{netMonthlySavings < 0 ? '-' : ''}${Math.abs(netMonthlySavings).toFixed(0)}
          </div>
          <div className="text-sm text-gray-400 mt-1">
            {netMonthlySavings >= 0 ? 'estimated monthly savings' : 'estimated monthly increase'}
          </div>
        </div>

        {/* Comparison table */}
        <div className="grid grid-cols-2 gap-4 mb-5">
          <div className="bg-gray-800/40 rounded-lg p-3 border border-gray-800/50">
            <div className="text-[10px] text-gray-500 uppercase mb-1">Without Solar</div>
            <div className="text-xl font-mono font-bold text-white">${currentMonthlyCost.toFixed(0)}<span className="text-sm text-gray-500">/mo</span></div>
            <div className="text-[10px] text-gray-600 mt-1">${currentAnnualCost.toFixed(0)}/year</div>
            <div className="text-[10px] text-gray-600">{annualUsageKwh.toFixed(0)} kWh/yr from grid</div>
          </div>
          <div className="bg-yellow-900/10 rounded-lg p-3 border border-yellow-800/30">
            <div className="text-[10px] text-yellow-500 uppercase mb-1">With Solar</div>
            <div className="text-xl font-mono font-bold text-white">${(totalWithSolar / 12).toFixed(0)}<span className="text-sm text-gray-500">/mo</span></div>
            <div className="text-[10px] text-gray-600 mt-1">${totalWithSolar.toFixed(0)}/year total</div>
            <div className="text-[10px] text-gray-500">${solarPayment}/mo solar + ${(remainingGridCost / 12).toFixed(0)}/mo grid</div>
          </div>
        </div>

        {/* Details */}
        <div className="space-y-2 text-xs">
          <div className="flex justify-between py-1 border-b border-gray-800/30">
            <span className="text-gray-500">Solar production</span>
            <span className="text-gray-300">{solarAnnualKwh.toLocaleString()} kWh/yr ({solarMonthlyKwh.toFixed(0)}/mo)</span>
          </div>
          <div className="flex justify-between py-1 border-b border-gray-800/30">
            <span className="text-gray-500">Your usage</span>
            <span className="text-gray-300">{annualUsageKwh.toFixed(0)} kWh/yr ({dailyAvgKwh.toFixed(0)} kWh/day)</span>
          </div>
          <div className="flex justify-between py-1 border-b border-gray-800/30">
            <span className="text-gray-500">Solar offset</span>
            <span className={solarOffsetPct >= 100 ? 'text-green-400' : 'text-yellow-400'}>{solarOffsetPct}% of usage</span>
          </div>
          <div className="flex justify-between py-1 border-b border-gray-800/30">
            <span className="text-gray-500">Net metering</span>
            <span className="text-gray-300">{netMetering ? 'Yes — excess credited' : 'No — excess lost'}</span>
          </div>
          {hasTou && (
            <div className="flex justify-between py-1 border-b border-gray-800/30">
              <span className="text-gray-500">TOU solar value</span>
              <span className="text-yellow-400">${solarEffectiveRate.toFixed(3)}/kWh avg (peak hours worth more)</span>
            </div>
          )}
          <div className="flex justify-between py-1 border-b border-gray-800/30">
            <span className="text-gray-500">Electricity saved</span>
            <span className="text-green-400">${annualSavingsFromSolar.toFixed(0)}/yr</span>
          </div>
          <div className="flex justify-between py-1 border-b border-gray-800/30">
            <span className="text-gray-500">Solar cost</span>
            <span className="text-gray-300">${annualPayment.toFixed(0)}/yr (${solarPayment}/mo)</span>
          </div>
          <div className="flex justify-between py-1 font-medium">
            <span className="text-gray-400">Net annual savings</span>
            <span className={netAnnualSavings >= 0 ? 'text-green-400' : 'text-red-400'}>
              {netAnnualSavings >= 0 ? '+' : ''}${netAnnualSavings.toFixed(0)}/yr
            </span>
          </div>
        </div>

        {/* Insight */}
        <div className="mt-4 bg-gray-800/30 rounded-lg px-4 py-3 border border-gray-800/50">
          <p className="text-xs text-gray-400 leading-relaxed">
            {netMonthlySavings >= 0 ? (
              <>
                This solar quote would save you <span className="text-green-400 font-medium">${netAnnualSavings.toFixed(0)}/year</span>.
                {solarOffsetPct >= 100 && netMetering && ' Your system produces more than you use — with net metering, your electricity bill drops to near zero.'}
                {solarOffsetPct < 100 && ` The system covers ${solarOffsetPct}% of your usage. You'd still buy ${remainingGridKwh.toFixed(0)} kWh/yr from the grid.`}
              </>
            ) : (
              <>
                At current usage, this solar quote would cost <span className="text-red-400 font-medium">${Math.abs(netAnnualSavings).toFixed(0)}/year more</span> than
                your current electricity bill. {!netMetering && 'Enabling net metering could improve this — excess daytime production would be credited.'}
                {netMetering && solarOffsetPct < 50 && 'The system may be undersized for your usage. A larger system might be more cost-effective.'}
              </>
            )}
          </p>
        </div>
      </div>
    )
  }

  // No quote — show generic analysis
  const dailyGenEstimate = 35 // 10kW system conservative New England
  const overallOffsetPct = Math.min(100, Math.round((dailyGenEstimate / dailyAvgKwh) * 100))
  const estimatedAnnualSavings = Math.min(dailyGenEstimate * 365, annualUsageKwh) * rate

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-5">
      <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-4">
        Solar Readiness
      </h3>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-4">
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Daytime Usage</div>
          <div className="text-xl font-mono font-bold text-white">{Math.round(daytimeFraction * 100)}%</div>
          <div className="text-[10px] text-gray-600">10am-3pm ({daytimeKwhPerDay.toFixed(1)} kWh/day)</div>
        </div>
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Est. Offset (10kW)</div>
          <div className="text-xl font-mono font-bold text-yellow-400">{overallOffsetPct}%</div>
          <div className="text-[10px] text-gray-600">of total usage</div>
        </div>
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Est. Savings</div>
          <div className="text-xl font-mono font-bold text-green-400">${estimatedAnnualSavings.toFixed(0)}</div>
          <div className="text-[10px] text-gray-600">per year</div>
        </div>
      </div>
      <div className="bg-yellow-900/10 border border-yellow-800/30 rounded-lg px-4 py-3">
        <p className="text-xs text-yellow-400/80">
          Have a solar quote? Go to <span className="font-medium text-yellow-300">Settings</span> and enter your monthly payment and estimated annual production to see a detailed cost comparison.
        </p>
      </div>
    </div>
  )
}
