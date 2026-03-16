import { useEffect, useState } from 'react'
import {
  Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ComposedChart, Cell,
} from 'recharts'
import type { AnnualForecastData } from '../lib/api'
import { fetchForecast } from '../lib/api'

function formatCurrency(n: number): string {
  return `$${Math.round(n).toLocaleString()}`
}

export default function AnnualForecast() {
  const [forecast, setForecast] = useState<AnnualForecastData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchForecast()
      .then(setForecast)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
        <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-4">
          Annual Energy Forecast
        </h3>
        <div className="flex items-center justify-center py-8 text-gray-500 text-sm">
          Loading forecast...
        </div>
      </div>
    )
  }

  if (error || !forecast) {
    return (
      <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
        <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-4">
          Annual Energy Forecast
        </h3>
        <div className="text-red-400 text-sm">
          {error || 'Failed to load forecast data'}
        </div>
      </div>
    )
  }

  const { months, has_solar_quote } = forecast

  // Chart data
  const chartData = months.map((m) => ({
    name: m.month_name.substring(0, 3),
    usage: Math.round(m.usage_kwh),
    solar: Math.round(m.solar_production_kwh),
    temp: m.avg_temp_f,
    isActual: m.is_actual,
    priorYear: m.prior_year_kwh != null ? Math.round(m.prior_year_kwh) : null,
    method: m.method,
  }))

  const actualCount = months.filter((m) => m.is_actual).length
  const projectedCount = 12 - actualCount

  return (
    <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wide">
          Annual Energy Forecast
        </h3>
        <span className="text-[10px] text-gray-600">
          {actualCount} actual / {projectedCount} projected months
        </span>
      </div>

      {/* Big annual totals */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Annual Usage</div>
          <div className="text-lg font-mono font-bold text-gray-900 dark:text-white">
            {Math.round(forecast.annual_usage_kwh).toLocaleString()} kWh
          </div>
        </div>
        <div>
          <div className="text-[10px] text-gray-500 uppercase mb-0.5">Cost (No Solar)</div>
          <div className="text-lg font-mono font-bold text-gray-900 dark:text-white">
            {formatCurrency(forecast.annual_cost_without_solar)}
          </div>
        </div>
        {has_solar_quote && (
          <>
            <div>
              <div className="text-[10px] text-gray-500 uppercase mb-0.5">Cost (With Solar)</div>
              <div className="text-lg font-mono font-bold text-gray-900 dark:text-white">
                {formatCurrency(forecast.annual_cost_with_solar)}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-gray-500 uppercase mb-0.5">Annual Savings</div>
              <div className={`text-lg font-mono font-bold ${forecast.annual_savings >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {forecast.annual_savings >= 0 ? '+' : ''}{formatCurrency(forecast.annual_savings)}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Chart */}
      <div className="h-72 mb-4">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
            <YAxis
              yAxisId="kwh"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickFormatter={(v: number) => `${v}`}
              label={{ value: 'kWh', angle: -90, position: 'insideLeft', fill: '#6b7280', fontSize: 10 }}
            />
            <YAxis
              yAxisId="temp"
              orientation="right"
              tick={{ fill: '#9ca3af', fontSize: 11 }}
              tickFormatter={(v: number) => `${v}°`}
              domain={[0, 100]}
              label={{ value: '°F', angle: 90, position: 'insideRight', fill: '#6b7280', fontSize: 10 }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#111827',
                border: '1px solid #374151',
                borderRadius: '8px',
                fontSize: '12px',
              }}
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null
                const entry = chartData.find((d) => d.name === label)
                return (
                  <div className="bg-gray-900 border border-gray-700 rounded-lg p-3 text-xs shadow-xl">
                    <div className="font-medium text-gray-200 mb-1.5">{label}</div>
                    {payload.map((p, i) => (
                      <div key={i} className="flex justify-between gap-4">
                        <span style={{ color: p.color }}>
                          {p.name === 'usage' ? 'Usage' : p.name === 'solar' ? 'Solar' : p.name === 'temp' ? 'Temp' : p.name}
                        </span>
                        <span className="font-mono text-gray-700 dark:text-gray-300">
                          {p.name === 'temp' ? `${p.value}°F` : `${p.value?.toLocaleString()} kWh`}
                        </span>
                      </div>
                    ))}
                    {entry?.priorYear != null && (
                      <div className="flex justify-between gap-4 mt-1.5 pt-1.5 border-t border-gray-300 dark:border-gray-700">
                        <span className="text-gray-500">Last year</span>
                        <span className="font-mono text-gray-400">
                          {entry.priorYear.toLocaleString()} kWh
                          {entry.usage > 0 && (
                            <span className={entry.usage > entry.priorYear ? ' text-red-400' : ' text-green-400'}>
                              {' '}({entry.usage > entry.priorYear ? '+' : ''}{Math.round((entry.usage - entry.priorYear) / entry.priorYear * 100)}%)
                            </span>
                          )}
                        </span>
                      </div>
                    )}
                    {!entry?.isActual && !entry?.priorYear && (
                      <div className="mt-1.5 pt-1.5 border-t border-gray-300 dark:border-gray-700 text-gray-600 italic">
                        No prior year data available
                      </div>
                    )}
                    {!entry?.isActual && (
                      <div className="mt-1 text-gray-600 italic">
                        {entry?.method === 'degree_day_regression' ? 'Projected via degree-day model' : 'Estimated'}
                      </div>
                    )}
                  </div>
                )
              }}
            />
            <Legend
              wrapperStyle={{ fontSize: '11px' }}
              formatter={(value: string) => {
                if (value === 'usage') return 'Energy Usage'
                if (value === 'solar') return 'Solar Production'
                if (value === 'temp') return 'Outdoor Temp'
                return value
              }}
            />
            <Bar
              yAxisId="kwh"
              dataKey="usage"
              radius={[3, 3, 0, 0]}
              maxBarSize={40}
            >
              {chartData.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={entry.isActual ? '#22c55e' : '#3b82f6'}
                  fillOpacity={entry.isActual ? 0.7 : 0.35}
                  stroke={entry.isActual ? '#22c55e' : '#3b82f6'}
                  strokeWidth={entry.isActual ? 0 : 1.5}
                  strokeDasharray={entry.isActual ? undefined : '4 2'}
                />
              ))}
            </Bar>
            {has_solar_quote && (
              <Bar
                yAxisId="kwh"
                dataKey="solar"
                fill="#eab308"
                fillOpacity={0.5}
                radius={[3, 3, 0, 0]}
                maxBarSize={40}
              />
            )}
            <Line
              yAxisId="temp"
              type="monotone"
              dataKey="temp"
              stroke="#f97316"
              strokeWidth={2}
              dot={{ r: 3, fill: '#f97316' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Legend for bar colors */}
      <div className="flex items-center gap-4 text-[10px] text-gray-500 mb-4">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded-sm bg-green-500/70 inline-block" /> Actual data
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded-sm border border-blue-500 border-dashed bg-blue-500/20 inline-block" /> Projected
        </span>
        {has_solar_quote && (
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-sm bg-yellow-500/50 inline-block" /> Solar production
          </span>
        )}
      </div>

      {/* Monthly table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 uppercase text-[10px] border-b border-gray-200 dark:border-gray-800">
              <th className="text-left py-2 pr-2">Month</th>
              <th className="text-right py-2 px-2">Usage</th>
              <th className="text-right py-2 px-2">Temp</th>
              <th className="text-right py-2 px-2">HDD</th>
              <th className="text-right py-2 px-2">Method</th>
              <th className="text-right py-2 px-2">Cost</th>
              {has_solar_quote && (
                <>
                  <th className="text-right py-2 px-2">Solar</th>
                  <th className="text-right py-2 px-2">W/ Solar</th>
                  <th className="text-right py-2 px-2">Savings</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {months.map((m) => (
              <tr
                key={m.month}
                className={`border-b border-gray-200 dark:border-gray-800/50 ${m.is_actual ? '' : 'text-gray-500'}`}
              >
                <td className="py-1.5 pr-2">
                  <span className="text-gray-700 dark:text-gray-300">{m.month_name.substring(0, 3)}</span>
                  {!m.is_actual && (
                    <span className="ml-1 text-[9px] text-blue-400/60 italic">est</span>
                  )}
                </td>
                <td className="text-right py-1.5 px-2 font-mono text-gray-700 dark:text-gray-300">
                  {Math.round(m.usage_kwh).toLocaleString()}
                </td>
                <td className="text-right py-1.5 px-2 font-mono text-orange-400/70">
                  {m.avg_temp_f}°
                </td>
                <td className="text-right py-1.5 px-2 font-mono text-gray-500">
                  {m.hdd > 0 ? m.hdd.toFixed(0) : '-'}
                </td>
                <td className="text-right py-1.5 px-2">
                  <span className={`text-[9px] px-1 py-0.5 rounded ${
                    m.method === 'actual' ? 'bg-green-900/30 text-green-400' :
                    m.method === 'scaled_partial' ? 'bg-yellow-900/30 text-yellow-400' :
                    'bg-blue-900/30 text-blue-400'
                  }`}>
                    {m.method === 'actual' ? `${m.data_days}d actual` :
                     m.method === 'scaled_partial' ? `${m.data_days}d scaled` :
                     'projected'}
                  </span>
                </td>
                <td className="text-right py-1.5 px-2 font-mono text-gray-700 dark:text-gray-300">
                  ${Math.round(m.cost_without_solar)}
                </td>
                {has_solar_quote && (
                  <>
                    <td className="text-right py-1.5 px-2 font-mono text-yellow-400/70">
                      {Math.round(m.solar_production_kwh).toLocaleString()}
                    </td>
                    <td className="text-right py-1.5 px-2 font-mono text-gray-700 dark:text-gray-300">
                      ${Math.round(m.cost_with_solar)}
                    </td>
                    <td className={`text-right py-1.5 px-2 font-mono ${m.savings >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {m.savings >= 0 ? '+' : ''}${Math.round(m.savings)}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-gray-300 dark:border-gray-700 font-medium">
              <td className="py-2 pr-2 text-gray-700 dark:text-gray-300">Annual</td>
              <td className="text-right py-2 px-2 font-mono text-gray-900 dark:text-white">
                {Math.round(forecast.annual_usage_kwh).toLocaleString()}
              </td>
              <td className="text-right py-2 px-2 font-mono text-gray-600">--</td>
              <td className="text-right py-2 px-2 font-mono text-gray-600">--</td>
              <td className="text-right py-2 px-2 font-mono text-gray-600">--</td>
              <td className="text-right py-2 px-2 font-mono text-gray-900 dark:text-white">
                {formatCurrency(forecast.annual_cost_without_solar)}
              </td>
              {has_solar_quote && (
                <>
                  <td className="text-right py-2 px-2 font-mono text-yellow-400/70">
                    --
                  </td>
                  <td className="text-right py-2 px-2 font-mono text-gray-900 dark:text-white">
                    {formatCurrency(forecast.annual_cost_with_solar)}
                  </td>
                  <td className={`text-right py-2 px-2 font-mono font-bold ${forecast.annual_savings >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {forecast.annual_savings >= 0 ? '+' : ''}{formatCurrency(forecast.annual_savings)}
                  </td>
                </>
              )}
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Solar savings highlight */}
      {has_solar_quote && forecast.annual_savings > 0 && (
        <div className="mt-4 bg-green-900/15 border border-green-800/30 rounded-lg px-4 py-3">
          <p className="text-xs text-green-400/90 leading-relaxed">
            Projected annual savings with solar: <span className="font-bold text-green-400">{formatCurrency(forecast.annual_savings)}/year</span>
            {' '}({formatCurrency(forecast.annual_savings / 12)}/month).
            Solar payment of ${forecast.solar_monthly_payment}/mo is included.
          </p>
        </div>
      )}

      {!has_solar_quote && (
        <div className="mt-4 bg-yellow-900/10 border border-yellow-800/30 rounded-lg px-4 py-3">
          <p className="text-xs text-yellow-400/80">
            Have a solar quote? Go to <span className="font-medium text-yellow-300">Settings</span> and enter your monthly payment and estimated annual production to see projected savings for each month.
          </p>
        </div>
      )}

      {/* Methodology explanation */}
      <details className="mt-4 text-xs">
        <summary className="text-gray-500 cursor-pointer hover:text-gray-400 transition-colors">
          How is this forecast calculated?
        </summary>
        <div className="mt-2 bg-gray-100 dark:bg-gray-800/30 border border-gray-200 dark:border-gray-800/50 rounded-lg px-4 py-3 space-y-2">
          <p className="text-gray-400 leading-relaxed">{forecast.methodology}</p>
          {forecast.regression_formula && (
            <p className="text-gray-500 font-mono text-[11px] bg-gray-50 dark:bg-gray-900/50 px-3 py-1.5 rounded">
              {forecast.regression_formula}
            </p>
          )}
          <p className="text-gray-500">
            {forecast.data_months} months with actual data. Months with fewer than 80% of days are scaled proportionally.
            Temperature data uses historical New England (Boston area) averages.
          </p>
        </div>
      </details>
    </div>
  )
}
