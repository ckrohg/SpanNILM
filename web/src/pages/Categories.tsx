import { useState, useMemo } from 'react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
  PieChart,
  Pie,
  Cell,
} from 'recharts'
import type { CircuitPower, DashboardData, TimelineBucket, DateRange } from '../lib/api'
import DateRangePicker from '../components/DateRangePicker'

type Category = 'HVAC' | 'EV Charging' | 'Kitchen' | 'Laundry' | 'Water' | 'Lighting & Outlets' | 'Other'

const CATEGORY_META: Record<Category, { icon: string; color: string; border: string; bg: string; text: string }> = {
  'HVAC':              { icon: '\u2744\uFE0F', color: '#3b82f6', border: 'border-blue-500',   bg: 'bg-blue-500/10',   text: 'text-blue-400' },
  'EV Charging':       { icon: '\u26A1',       color: '#22c55e', border: 'border-green-500',  bg: 'bg-green-500/10',  text: 'text-green-400' },
  'Kitchen':           { icon: '\uD83C\uDF73', color: '#f97316', border: 'border-orange-500', bg: 'bg-orange-500/10', text: 'text-orange-400' },
  'Laundry':           { icon: '\uD83E\uDDFA', color: '#a855f7', border: 'border-purple-500', bg: 'bg-purple-500/10', text: 'text-purple-400' },
  'Water':             { icon: '\uD83D\uDCA7', color: '#06b6d4', border: 'border-cyan-500',   bg: 'bg-cyan-500/10',   text: 'text-cyan-400' },
  'Lighting & Outlets':{ icon: '\uD83D\uDCA1', color: '#eab308', border: 'border-yellow-500', bg: 'bg-yellow-500/10', text: 'text-yellow-400' },
  'Other':             { icon: '\uD83D\uDD0C', color: '#6b7280', border: 'border-gray-500',   bg: 'bg-gray-500/10',   text: 'text-gray-400' },
}

const CATEGORY_ORDER: Category[] = [
  'HVAC', 'EV Charging', 'Kitchen', 'Laundry', 'Water', 'Lighting & Outlets', 'Other',
]

function categorizeCircuit(circuit: CircuitPower): Category {
  const name = (circuit.name + ' ' + (circuit.device_type || '')).toLowerCase()
  if (/mini.?split|heat.?pump|air.?water|hydronic|hvac|compressor|glycol|zone.?pump/.test(name)) return 'HVAC'
  if (/ev.?charg/.test(name)) return 'EV Charging'
  if (/range|oven|stove|dishwasher|refrigerator|fridge|microwave/.test(name)) return 'Kitchen'
  if (/dryer|washer|laundry/.test(name) && !/dish/.test(name)) return 'Laundry'
  if (/well.?pump|water.?heater|buffer.?tank|hot.?water/.test(name)) return 'Water'
  if (/light|outlet|lamp/.test(name)) return 'Lighting & Outlets'
  return 'Other'
}

/** Map a circuit name to its category (used for timeline bucketing). */
function categorizeCircuitName(name: string): Category {
  const n = name.toLowerCase()
  if (/mini.?split|heat.?pump|air.?water|hydronic|hvac|compressor|glycol|zone.?pump/.test(n)) return 'HVAC'
  if (/ev.?charg/.test(n)) return 'EV Charging'
  if (/range|oven|stove|dishwasher|refrigerator|fridge|microwave/.test(n)) return 'Kitchen'
  if (/dryer|washer|laundry/.test(n) && !/dish/.test(n)) return 'Laundry'
  if (/well.?pump|water.?heater|buffer.?tank|hot.?water/.test(n)) return 'Water'
  if (/light|outlet|lamp/.test(n)) return 'Lighting & Outlets'
  return 'Other'
}

function formatPower(w: number): string {
  if (w >= 1000) return `${(w / 1000).toFixed(1)} kW`
  return `${Math.round(w)} W`
}

function formatEnergy(kwh: number): string {
  if (kwh >= 100) return `${Math.round(kwh)} kWh`
  if (kwh >= 10) return `${kwh.toFixed(1)} kWh`
  return `${kwh.toFixed(2)} kWh`
}

function formatTime(ts: string): string {
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

interface CategoryData {
  category: Category
  circuits: CircuitPower[]
  totalPowerW: number
  totalEnergyTodayKwh: number
  totalEnergyMonthKwh: number
  totalAlwaysOnW: number
  totalCostMonth: number
}

const PERIOD_LABELS: Record<DateRange, string> = {
  today: 'Today',
  yesterday: 'Yesterday',
  '7d': 'Last 7 Days',
  '30d': 'Last 30 Days',
  month: 'This Month',
  year: 'This Year',
  '365d': 'Last 365 Days',
}

interface Props {
  data: DashboardData
  dateRange?: DateRange
  onDateRangeChange?: (range: DateRange) => void
}

function EnergyBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="w-full h-2 bg-gray-200 dark:bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.max(1, pct)}%`, backgroundColor: color }}
      />
    </div>
  )
}

function CategoryCard({ data, totalEnergyMonth }: { data: CategoryData; totalEnergyMonth: number }) {
  const [expanded, setExpanded] = useState(false)
  const meta = CATEGORY_META[data.category]
  const pctOfTotal = totalEnergyMonth > 0 ? (data.totalEnergyMonthKwh / totalEnergyMonth) * 100 : 0
  const isActive = data.totalPowerW > 5

  return (
    <div
      className={`rounded-xl bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800 overflow-hidden cursor-pointer
        hover:border-gray-300 dark:hover:border-gray-700 transition-all duration-200 border-l-4 ${meta.border}`}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="p-4">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2.5">
            <span className="text-xl">{meta.icon}</span>
            <div>
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{data.category}</h3>
              <span className="text-[10px] text-gray-500">{data.circuits.length} circuit{data.circuits.length !== 1 ? 's' : ''}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {isActive && (
              <span className="relative flex h-2.5 w-2.5">
                <span
                  className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-50"
                  style={{ backgroundColor: meta.color }}
                />
                <span
                  className="relative inline-flex rounded-full h-2.5 w-2.5"
                  style={{ backgroundColor: meta.color }}
                />
              </span>
            )}
            <span className="text-lg font-mono font-bold text-gray-900 dark:text-white">
              {formatPower(data.totalPowerW)}
            </span>
          </div>
        </div>

        {/* Energy stats */}
        <div className="grid grid-cols-2 gap-3 mb-3 text-xs">
          <div>
            <div className="text-gray-500">Today</div>
            <div className="text-gray-800 dark:text-gray-200 font-medium">{formatEnergy(data.totalEnergyTodayKwh)}</div>
          </div>
          <div>
            <div className="text-gray-500">This Month</div>
            <div className="text-gray-800 dark:text-gray-200 font-medium">{formatEnergy(data.totalEnergyMonthKwh)}</div>
          </div>
        </div>

        {/* % of total bar */}
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <EnergyBar pct={pctOfTotal} color={meta.color} />
          </div>
          <span className="text-[10px] text-gray-500 w-10 text-right">{pctOfTotal.toFixed(1)}%</span>
        </div>

        {data.totalAlwaysOnW > 5 && (
          <div className="mt-2 text-[10px] text-gray-500">
            Always on: {formatPower(data.totalAlwaysOnW)}
          </div>
        )}
      </div>

      {/* Expanded: circuit list */}
      {expanded && (
        <div className="border-t border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950/40">
          <div className="divide-y divide-gray-200 dark:divide-gray-800/50">
            {data.circuits
              .sort((a, b) => b.energy_month_kwh - a.energy_month_kwh)
              .map((c) => (
                <div key={c.equipment_id} className="px-4 py-2.5 flex items-center justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="text-xs text-gray-700 dark:text-gray-300 truncate">{c.name}</div>
                    <div className="text-[10px] text-gray-500 flex gap-3 mt-0.5">
                      <span>Today: {formatEnergy(c.energy_today_kwh)}</span>
                      <span>Month: {formatEnergy(c.energy_month_kwh)}</span>
                      {c.always_on_w > 5 && <span>Always on: {formatPower(c.always_on_w)}</span>}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                    {c.power_w > 5 && (
                      <span className="relative flex h-1.5 w-1.5">
                        <span
                          className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-50"
                          style={{ backgroundColor: meta.color }}
                        />
                        <span
                          className="relative inline-flex rounded-full h-1.5 w-1.5"
                          style={{ backgroundColor: meta.color }}
                        />
                      </span>
                    )}
                    <span className="text-xs font-mono text-gray-700 dark:text-gray-200">{formatPower(c.power_w)}</span>
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Expand indicator */}
      <div className="flex justify-center pb-1.5">
        <svg
          className={`w-4 h-4 text-gray-600 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </div>
  )
}

// ─── Timeline Tooltip ──────────────────────────────────────────────

interface TimelineTooltipItem {
  name: string
  value: number
  color: string
  dataKey: string
}

function CategoryTimelineTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: TimelineTooltipItem[]
  label?: string
}) {
  if (!active || !payload || !payload.length) return null

  const items = payload
    .filter((p) => p.value > 0)
    .sort((a, b) => b.value - a.value)

  const total = items.reduce((sum, p) => sum + p.value, 0)

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 shadow-xl text-xs max-w-[260px]">
      <div className="text-gray-400 mb-1.5 font-medium">{label}</div>
      <div className="space-y-0.5">
        {items.map((item) => (
          <div key={item.dataKey} className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-1.5 min-w-0">
              <div
                className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
                style={{ backgroundColor: item.color }}
              />
              <span className="text-gray-300 truncate">{item.name}</span>
            </div>
            <span className="text-white font-mono tabular-nums flex-shrink-0">
              {formatPower(item.value)}
            </span>
          </div>
        ))}
      </div>
      <div className="border-t border-gray-700 mt-1.5 pt-1.5 flex justify-between">
        <span className="text-gray-400">Total</span>
        <span className="text-white font-mono font-bold">{formatPower(total)}</span>
      </div>
    </div>
  )
}

// ─── Category Timeline Chart ────────────────────────────────────────

function CategoryTimeline({ timeline }: { timeline: TimelineBucket[] }) {
  const { chartData, categories, colorMap } = useMemo(() => {
    // For each timeline bucket, sum circuit power by category
    const catsPresent = new Set<Category>()

    const data = timeline.map((bucket) => {
      const point: Record<string, number | string> = {
        time: formatTime(bucket.timestamp),
        timestamp: bucket.timestamp,
      }

      const catSums: Record<Category, number> = {
        'HVAC': 0, 'EV Charging': 0, 'Kitchen': 0, 'Laundry': 0,
        'Water': 0, 'Lighting & Outlets': 0, 'Other': 0,
      }

      for (const [circuitName, power] of Object.entries(bucket.circuits)) {
        const cat = categorizeCircuitName(circuitName)
        catSums[cat] += power
      }

      for (const cat of CATEGORY_ORDER) {
        const val = Math.max(0, Math.round(catSums[cat]))
        point[cat] = val
        if (val > 0) catsPresent.add(cat)
      }

      return point
    })

    const activeCats = CATEGORY_ORDER.filter((c) => catsPresent.has(c))
    const colors: Record<string, string> = {}
    for (const cat of activeCats) {
      colors[cat] = CATEGORY_META[cat].color
    }

    return { chartData: data, categories: activeCats, colorMap: colors }
  }, [timeline])

  if (!timeline.length) {
    return (
      <div className="h-48 sm:h-64 rounded-xl bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 flex items-center justify-center text-gray-500">
        No timeline data
      </div>
    )
  }

  return (
    <div className="rounded-xl bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 p-2 sm:p-4">
      <div className="h-56 sm:h-72">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <defs>
              {categories.map((cat) => (
                <linearGradient key={cat} id={`cat-fill-${cat.replace(/[^a-zA-Z0-9]/g, '_')}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={colorMap[cat]} stopOpacity={0.7} />
                  <stop offset="100%" stopColor={colorMap[cat]} stopOpacity={0.5} />
                </linearGradient>
              ))}
            </defs>
            <XAxis
              dataKey="time"
              stroke="#4b5563"
              fontSize={10}
              tickLine={false}
              axisLine={{ stroke: '#374151' }}
              interval="preserveStartEnd"
              minTickGap={60}
            />
            <YAxis
              stroke="#4b5563"
              fontSize={10}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => formatPower(v)}
              width={52}
            />
            <Tooltip
              content={<CategoryTimelineTooltip />}
              cursor={{ stroke: '#6b7280', strokeWidth: 1, strokeDasharray: '4 4' }}
            />
            <Legend
              wrapperStyle={{ fontSize: '10px', paddingTop: '8px' }}
              iconType="square"
              iconSize={8}
              formatter={(value: string) => (
                <span className="text-gray-400 text-[10px]">{value}</span>
              )}
            />
            {categories.map((cat) => (
              <Area
                key={cat}
                type="monotone"
                dataKey={cat}
                stackId="1"
                stroke={colorMap[cat]}
                strokeWidth={0.5}
                fill={`url(#cat-fill-${cat.replace(/[^a-zA-Z0-9]/g, '_')})`}
                fillOpacity={1}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ─── Monthly Bill by Category ───────────────────────────────────────

function CategoryBillProjection({ data, categoryData }: { data: DashboardData; categoryData: CategoryData[] }) {
  const projection = data.bill_projection
  if (!projection) return null

  const totalCostMonth = categoryData.reduce((s, d) => s + d.totalCostMonth, 0)

  // Scale each category's month cost to projected total
  const scaleFactor = totalCostMonth > 0 ? projection.projected_monthly_cost / totalCostMonth : 1
  const projectedCategories = categoryData
    .map((d) => ({
      category: d.category,
      projectedCost: d.totalCostMonth * scaleFactor,
      pct: totalCostMonth > 0 ? (d.totalCostMonth / totalCostMonth) * 100 : 0,
    }))
    .filter((d) => d.projectedCost > 0.01)
    .sort((a, b) => b.projectedCost - a.projectedCost)

  const progressPct = (projection.days_elapsed / (projection.days_elapsed + projection.days_remaining)) * 100

  return (
    <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-3 sm:p-5">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between mb-3 sm:mb-4 gap-1 sm:gap-0">
        <div>
          <h3 className="text-[10px] sm:text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">
            Projected Monthly Bill by Category
          </h3>
          <div className="text-2xl sm:text-3xl font-mono font-bold text-gray-900 dark:text-white">
            ${projection.projected_monthly_cost.toFixed(0)}
          </div>
          <div className="text-xs sm:text-sm text-gray-500 mt-0.5">
            {projection.projected_monthly_kwh.toFixed(0)} kWh projected
          </div>
        </div>
        <div className="text-left sm:text-right text-[10px] sm:text-xs text-gray-500">
          <div>{projection.daily_avg_kwh.toFixed(1)} kWh/day avg</div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="mb-3 sm:mb-4">
        <div className="flex justify-between text-[10px] sm:text-[11px] text-gray-500 mb-1">
          <span>Day {projection.days_elapsed}</span>
          <span>{projection.days_remaining} days left</span>
        </div>
        <div className="h-1.5 sm:h-2 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full bg-blue-500/80 transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Category cost bars */}
      <div>
        <h4 className="text-[10px] text-gray-600 uppercase tracking-wider mb-2">
          Cost by Category
        </h4>
        <div className="space-y-1.5">
          {projectedCategories.map((d) => {
            const meta = CATEGORY_META[d.category]
            return (
              <div key={d.category} className="flex items-center gap-1.5 sm:gap-2">
                <span className="text-sm flex-shrink-0 w-5">{meta.icon}</span>
                <span className="text-[10px] sm:text-xs text-gray-400 w-20 sm:w-32 min-w-[5rem] sm:min-w-[8rem] truncate">
                  {d.category}
                </span>
                <div className="flex-1 h-1.5 sm:h-2 bg-gray-200/60 dark:bg-gray-800/60 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${d.pct}%`, backgroundColor: meta.color + 'aa' }}
                  />
                </div>
                <span className="text-[10px] sm:text-[11px] font-mono text-green-500/80 w-10 sm:w-12 text-right">
                  ${d.projectedCost.toFixed(0)}
                </span>
                <span className="text-[10px] sm:text-[11px] font-mono text-gray-600 w-8 sm:w-10 text-right">
                  {d.pct.toFixed(0)}%
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ─── Usage Trends by Category ───────────────────────────────────────

interface CategoryTrend {
  category: Category
  currentKwh: number
  previousKwh: number
  changePct: number
  direction: 'up' | 'down' | 'stable'
}

function CategoryUsageTrends({ data, categoryData }: { data: DashboardData; categoryData: CategoryData[] }) {
  const trends = data.trends
  if (trends.length === 0) return null

  // Build a map from circuit name to category
  const circuitCategoryMap = new Map<string, Category>()
  for (const c of data.circuits) {
    circuitCategoryMap.set(c.name, categorizeCircuit(c))
  }

  // Aggregate trends by category
  const catTrendsMap = new Map<Category, { current: number; previous: number }>()
  for (const t of trends) {
    const cat = circuitCategoryMap.get(t.circuit_name) || 'Other'
    const existing = catTrendsMap.get(cat) || { current: 0, previous: 0 }
    existing.current += t.current_period_kwh
    existing.previous += t.previous_period_kwh
    catTrendsMap.set(cat, existing)
  }

  const categoryTrends: CategoryTrend[] = []
  for (const [cat, vals] of catTrendsMap) {
    const changePct = vals.previous > 0
      ? ((vals.current - vals.previous) / vals.previous) * 100
      : vals.current > 0 ? 100 : 0
    const direction: 'up' | 'down' | 'stable' =
      changePct > 5 ? 'up' : changePct < -5 ? 'down' : 'stable'
    categoryTrends.push({
      category: cat,
      currentKwh: vals.current,
      previousKwh: vals.previous,
      changePct,
      direction,
    })
  }

  // Sort: up first then down, by absolute change
  categoryTrends.sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct))

  const up = categoryTrends.filter((t) => t.direction === 'up')
  const down = categoryTrends.filter((t) => t.direction === 'down')
  const stable = categoryTrends.filter((t) => t.direction === 'stable')

  return (
    <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
      <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
        Category Trends (vs last week)
      </h3>
      <div className="space-y-1.5">
        {up.map((t) => {
          const meta = CATEGORY_META[t.category]
          return (
            <div key={t.category} className="flex items-center gap-2">
              <span className="text-red-400 text-sm w-5 flex-shrink-0">&#x2191;</span>
              <span className="text-sm flex-shrink-0 w-5">{meta.icon}</span>
              <span className="text-sm text-gray-700 dark:text-gray-300 flex-1 truncate">{t.category}</span>
              <span className="text-sm font-mono text-red-400 flex-shrink-0">
                +{Math.round(t.changePct)}%
              </span>
              <span className="text-[11px] text-gray-600 flex-shrink-0 w-28 text-right">
                {t.previousKwh.toFixed(1)} &rarr; {t.currentKwh.toFixed(1)} kWh
              </span>
            </div>
          )
        })}
        {down.map((t) => {
          const meta = CATEGORY_META[t.category]
          return (
            <div key={t.category} className="flex items-center gap-2">
              <span className="text-green-400 text-sm w-5 flex-shrink-0">&#x2193;</span>
              <span className="text-sm flex-shrink-0 w-5">{meta.icon}</span>
              <span className="text-sm text-gray-700 dark:text-gray-300 flex-1 truncate">{t.category}</span>
              <span className="text-sm font-mono text-green-400 flex-shrink-0">
                {Math.round(t.changePct)}%
              </span>
              <span className="text-[11px] text-gray-600 flex-shrink-0 w-28 text-right">
                {t.previousKwh.toFixed(1)} &rarr; {t.currentKwh.toFixed(1)} kWh
              </span>
            </div>
          )
        })}
        {stable.map((t) => {
          const meta = CATEGORY_META[t.category]
          return (
            <div key={t.category} className="flex items-center gap-2">
              <span className="text-gray-500 text-sm w-5 flex-shrink-0">=</span>
              <span className="text-sm flex-shrink-0 w-5">{meta.icon}</span>
              <span className="text-sm text-gray-700 dark:text-gray-300 flex-1 truncate">{t.category}</span>
              <span className="text-sm font-mono text-gray-500 flex-shrink-0">
                {t.changePct > 0 ? '+' : ''}{Math.round(t.changePct)}%
              </span>
              <span className="text-[11px] text-gray-600 flex-shrink-0 w-28 text-right">
                {t.previousKwh.toFixed(1)} &rarr; {t.currentKwh.toFixed(1)} kWh
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Energy Summary by Category ─────────────────────────────────────

function CategoryEnergySummary({ categoryData }: { categoryData: CategoryData[] }) {
  const sorted = [...categoryData].sort((a, b) => b.totalEnergyMonthKwh - a.totalEnergyMonthKwh)
  const maxMonth = sorted.length > 0 ? sorted[0].totalEnergyMonthKwh : 1

  return (
    <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-3 sm:p-5">
      <h3 className="text-[10px] sm:text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
        Energy by Category
      </h3>
      <div className="space-y-3">
        {sorted.map((d) => {
          const meta = CATEGORY_META[d.category]
          const barPct = maxMonth > 0 ? (d.totalEnergyMonthKwh / maxMonth) * 100 : 0
          return (
            <div key={d.category}>
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm">{meta.icon}</span>
                  <span className="text-xs text-gray-700 dark:text-gray-300">{d.category}</span>
                </div>
                <div className="flex items-center gap-3 text-xs">
                  <div>
                    <span className="text-gray-500">Today: </span>
                    <span className="font-mono text-gray-800 dark:text-gray-200">{formatEnergy(d.totalEnergyTodayKwh)}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Month: </span>
                    <span className="font-mono text-gray-800 dark:text-gray-200">{formatEnergy(d.totalEnergyMonthKwh)}</span>
                  </div>
                </div>
              </div>
              <div className="h-2 bg-gray-200 dark:bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.max(1, barPct)}%`, backgroundColor: meta.color }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Cost Donut Chart ───────────────────────────────────────────────

function CategoryCostDonut({ categoryData }: { categoryData: CategoryData[] }) {
  const donutData = categoryData
    .filter((d) => d.totalCostMonth > 0)
    .sort((a, b) => b.totalCostMonth - a.totalCostMonth)
    .map((d) => ({
      name: d.category,
      cost: d.totalCostMonth,
      color: CATEGORY_META[d.category].color,
      icon: CATEGORY_META[d.category].icon,
    }))

  const totalCost = donutData.reduce((s, d) => s + d.cost, 0)

  if (donutData.length === 0) return null

  return (
    <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
      <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
        Monthly Cost by Category
      </h3>

      <div className="flex flex-col sm:flex-row items-center gap-6">
        {/* Donut chart */}
        <div className="relative w-48 h-48 flex-shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={donutData}
                dataKey="cost"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                paddingAngle={1}
                strokeWidth={0}
              >
                {donutData.map((entry, i) => (
                  <Cell key={i} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1f2937',
                  border: '1px solid #374151',
                  borderRadius: '0.5rem',
                  fontSize: '11px',
                }}
                formatter={(value: number, name: string) => [
                  `$${value.toFixed(2)}`,
                  name,
                ]}
              />
            </PieChart>
          </ResponsiveContainer>
          {/* Center label */}
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <span className="text-lg font-mono font-bold text-gray-900 dark:text-white">
              ${totalCost.toFixed(0)}
            </span>
            <span className="text-[10px] text-gray-500">/month</span>
          </div>
        </div>

        {/* Legend */}
        <div className="flex-1 space-y-1.5 overflow-hidden w-full">
          {donutData.map((d) => {
            const pct = totalCost > 0 ? (d.cost / totalCost) * 100 : 0
            return (
              <div key={d.name} className="flex items-center gap-2">
                <span className="text-sm flex-shrink-0">{d.icon}</span>
                <span
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: d.color }}
                />
                <span className="text-xs text-gray-700 dark:text-gray-300 truncate flex-1">
                  {d.name}
                </span>
                <span className="text-xs font-mono text-green-500/80 flex-shrink-0">
                  ${d.cost.toFixed(2)}
                </span>
                <span className="text-[11px] font-mono text-gray-600 w-10 text-right flex-shrink-0">
                  {pct.toFixed(0)}%
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ─── Main Component ─────────────────────────────────────────────────

export default function Categories({ data, dateRange = 'today', onDateRangeChange }: Props) {
  const { circuits } = data

  const categoryData = useMemo(() => {
    const grouped: Record<Category, CircuitPower[]> = {
      'HVAC': [], 'EV Charging': [], 'Kitchen': [], 'Laundry': [],
      'Water': [], 'Lighting & Outlets': [], 'Other': [],
    }

    for (const circuit of circuits) {
      const cat = categorizeCircuit(circuit)
      grouped[cat].push(circuit)
    }

    const result: CategoryData[] = CATEGORY_ORDER
      .filter((cat) => grouped[cat].length > 0)
      .map((cat) => {
        const circs = grouped[cat]
        return {
          category: cat,
          circuits: circs,
          totalPowerW: circs.reduce((s, c) => s + c.power_w, 0),
          totalEnergyTodayKwh: circs.reduce((s, c) => s + c.energy_today_kwh, 0),
          totalEnergyMonthKwh: circs.reduce((s, c) => s + c.energy_month_kwh, 0),
          totalAlwaysOnW: circs.reduce((s, c) => s + c.always_on_w, 0),
          totalCostMonth: circs.reduce((s, c) => s + c.cost_month, 0),
        }
      })

    // Sort by monthly energy (highest first)
    result.sort((a, b) => b.totalEnergyMonthKwh - a.totalEnergyMonthKwh)
    return result
  }, [circuits])

  const totalEnergyMonth = categoryData.reduce((s, d) => s + d.totalEnergyMonthKwh, 0)
  const totalPowerNow = categoryData.reduce((s, d) => s + d.totalPowerW, 0)

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Date Range Picker */}
      {onDateRangeChange && (
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <DateRangePicker value={dateRange} onChange={onDateRangeChange} />
        </div>
      )}

      {/* Summary header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Energy Categories — {PERIOD_LABELS[dateRange]}</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {categoryData.length} categories across {circuits.length} circuits
          </p>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <div>
            <span className="text-gray-500">Now: </span>
            <span className="font-mono font-bold text-gray-900 dark:text-white">{formatPower(totalPowerNow)}</span>
          </div>
          <div>
            <span className="text-gray-500">Month: </span>
            <span className="font-mono font-bold text-gray-900 dark:text-white">{formatEnergy(totalEnergyMonth)}</span>
          </div>
        </div>
      </div>

      {/* Category cards grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {categoryData.map((d) => (
          <CategoryCard
            key={d.category}
            data={d}
            totalEnergyMonth={totalEnergyMonth}
          />
        ))}
      </div>

      {/* Category Timeline */}
      <section>
        <h2 className="text-sm font-medium text-gray-400 mb-2">
          Power Timeline by Category
        </h2>
        <CategoryTimeline timeline={data.timeline} />
      </section>

      {/* Bill Projection + Usage Trends */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">
        <CategoryBillProjection data={data} categoryData={categoryData} />
        <CategoryUsageTrends data={data} categoryData={categoryData} />
      </div>

      {/* Energy Summary by Category */}
      <section>
        <h2 className="text-sm font-medium text-gray-400 mb-2">
          Energy Summary
        </h2>
        <CategoryEnergySummary categoryData={categoryData} />
      </section>

      {/* Cost Donut */}
      <section>
        <CategoryCostDonut categoryData={categoryData} />
      </section>
    </div>
  )
}
