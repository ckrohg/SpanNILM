import { useEffect, useState } from 'react'
import { getSettings, updateSettings, type Settings as SettingsType, type TOUSchedule } from '../lib/api'

const US_TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
]

const TIMEZONE_LABELS: Record<string, string> = {
  'America/New_York': 'Eastern (ET)',
  'America/Chicago': 'Central (CT)',
  'America/Denver': 'Mountain (MT)',
  'America/Los_Angeles': 'Pacific (PT)',
  'America/Anchorage': 'Alaska (AKT)',
  'Pacific/Honolulu': 'Hawaii (HT)',
}

const DEFAULT_TOU: TOUSchedule = {
  enabled: false,
  peak: { start: 14, end: 19, rate: 0.28, weekdays_only: true },
  off_peak: { start: 21, end: 9, rate: 0.10 },
  mid_peak: { start: 9, end: 14, rate: 0.18 },
}

function formatHour(h: number): string {
  if (h === 0) return '12 AM'
  if (h === 12) return '12 PM'
  if (h < 12) return `${h} AM`
  return `${h - 12} PM`
}

const HOURS = Array.from({ length: 24 }, (_, i) => i)

export default function Settings() {
  const [settings, setSettings] = useState<SettingsType>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Local form state
  const [rate, setRate] = useState('')
  const [timezone, setTimezone] = useState('')
  const [currency, setCurrency] = useState('')
  const [solarPayment, setSolarPayment] = useState('')
  const [solarAnnualKwh, setSolarAnnualKwh] = useState('')
  const [netMetering, setNetMetering] = useState('yes')

  // TOU state
  const [billingMode, setBillingMode] = useState<'flat' | 'tou'>('flat')
  const [tou, setTou] = useState<TOUSchedule>(DEFAULT_TOU)
  const [touDirty, setTouDirty] = useState(false)

  // Save status per field
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  const [saved, setSaved] = useState<Record<string, boolean>>({})

  useEffect(() => {
    getSettings()
      .then((s) => {
        setSettings(s)
        setRate(s.electricity_rate || '0.14')
        setTimezone(s.timezone || 'America/New_York')
        setCurrency(s.currency || 'USD')
        setSolarPayment(s.solar_monthly_payment || '')
        setSolarAnnualKwh(s.solar_annual_kwh || '')
        setNetMetering(s.net_metering || 'yes')

        // Load TOU schedule
        if (s.tou_schedule) {
          try {
            const parsed = JSON.parse(s.tou_schedule) as TOUSchedule
            setTou(parsed)
            setBillingMode(parsed.enabled ? 'tou' : 'flat')
          } catch {
            // ignore parse errors
          }
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async (key: string, value: string) => {
    setSaving((prev) => ({ ...prev, [key]: true }))
    setSaved((prev) => ({ ...prev, [key]: false }))
    try {
      const updated = await updateSettings({ [key]: value })
      setSettings(updated)
      setSaved((prev) => ({ ...prev, [key]: true }))
      setTimeout(() => setSaved((prev) => ({ ...prev, [key]: false })), 2000)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving((prev) => ({ ...prev, [key]: false }))
    }
  }

  const handleSaveTou = async () => {
    const schedule: TOUSchedule = {
      ...tou,
      enabled: billingMode === 'tou',
    }
    const value = JSON.stringify(schedule)
    setSaving((prev) => ({ ...prev, tou_schedule: true }))
    setSaved((prev) => ({ ...prev, tou_schedule: false }))
    try {
      const updated = await updateSettings({ tou_schedule: value })
      setSettings(updated)
      setTouDirty(false)
      setSaved((prev) => ({ ...prev, tou_schedule: true }))
      setTimeout(() => setSaved((prev) => ({ ...prev, tou_schedule: false })), 2000)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving((prev) => ({ ...prev, tou_schedule: false }))
    }
  }

  const updateTouField = (
    period: 'peak' | 'off_peak' | 'mid_peak',
    field: string,
    value: number | boolean
  ) => {
    setTou((prev) => ({
      ...prev,
      [period]: {
        ...prev[period],
        [field]: value,
      },
    }))
    setTouDirty(true)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-400">
        Loading settings...
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

  const rateDirty = rate !== (settings.electricity_rate || '0.14')
  const timezoneDirty = timezone !== (settings.timezone || 'America/New_York')
  const currencyDirty = currency !== (settings.currency || 'USD')
  const solarPaymentDirty = solarPayment !== (settings.solar_monthly_payment || '')
  const solarKwhDirty = solarAnnualKwh !== (settings.solar_annual_kwh || '')
  const netMeteringDirty = netMetering !== (settings.net_metering || 'yes')

  // Check if billing mode changed relative to saved state
  const savedTouEnabled = (() => {
    try {
      if (settings.tou_schedule) {
        return JSON.parse(settings.tou_schedule).enabled === true
      }
    } catch { /* ignore */ }
    return false
  })()
  const billingModeDirty = (billingMode === 'tou') !== savedTouEnabled || touDirty

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold mb-1">Settings</h2>
        <p className="text-sm text-gray-500">
          Configure electricity rate, timezone, and other preferences.
        </p>
      </div>

      {/* Electricity Rate */}
      <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-700 dark:text-gray-300 block mb-2">
          Electricity Rate {billingMode === 'tou' ? '(fallback)' : ''}
        </label>
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-xs">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">
              $
            </span>
            <input
              type="number"
              step="0.01"
              min="0"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg pl-7 pr-16 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">
              /kWh
            </span>
          </div>
          <button
            onClick={() => handleSave('electricity_rate', rate)}
            disabled={!rateDirty || saving.electricity_rate}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              rateDirty
                ? 'bg-blue-600 hover:bg-blue-500 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed'
            }`}
          >
            {saving.electricity_rate ? 'Saving...' : saved.electricity_rate ? 'Saved' : 'Save'}
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-2">
          {billingMode === 'tou'
            ? 'Used as fallback when a time period doesn\'t match any TOU rate.'
            : 'Used to calculate energy costs on the dashboard.'}
        </p>
      </div>

      {/* TOU Billing Section */}
      <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-700 dark:text-gray-300 block mb-3">
          Billing Mode
        </label>
        <div className="flex items-center gap-2 mb-4">
          <button
            onClick={() => { setBillingMode('flat'); setTouDirty(true) }}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              billingMode === 'flat'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            Flat Rate
          </button>
          <button
            onClick={() => { setBillingMode('tou'); setTouDirty(true) }}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              billingMode === 'tou'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            Time-of-Use
          </button>
        </div>

        {billingMode === 'tou' && (
          <div className="space-y-4">
            {/* Peak */}
            <div className="bg-red-900/10 border border-red-900/30 rounded-lg p-3">
              <div className="text-xs font-medium text-red-400 uppercase mb-2">Peak Rate</div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div>
                  <label className="text-[10px] text-gray-500 block mb-1">Start</label>
                  <select
                    value={tou.peak?.start ?? 14}
                    onChange={(e) => updateTouField('peak', 'start', parseInt(e.target.value))}
                    className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  >
                    {HOURS.map((h) => (
                      <option key={h} value={h}>{formatHour(h)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 block mb-1">End</label>
                  <select
                    value={tou.peak?.end ?? 19}
                    onChange={(e) => updateTouField('peak', 'end', parseInt(e.target.value))}
                    className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  >
                    {HOURS.map((h) => (
                      <option key={h} value={h}>{formatHour(h)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 block mb-1">Rate ($/kWh)</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={tou.peak?.rate ?? 0.28}
                    onChange={(e) => updateTouField('peak', 'rate', parseFloat(e.target.value) || 0)}
                    className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 block mb-1">Days</label>
                  <select
                    value={tou.peak?.weekdays_only ? 'weekdays' : 'all'}
                    onChange={(e) => updateTouField('peak', 'weekdays_only', e.target.value === 'weekdays')}
                    className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  >
                    <option value="weekdays">Weekdays only</option>
                    <option value="all">All days</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Off-Peak */}
            <div className="bg-green-900/10 border border-green-900/30 rounded-lg p-3">
              <div className="text-xs font-medium text-green-400 uppercase mb-2">Off-Peak Rate</div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <div>
                  <label className="text-[10px] text-gray-500 block mb-1">Start</label>
                  <select
                    value={tou.off_peak?.start ?? 21}
                    onChange={(e) => updateTouField('off_peak', 'start', parseInt(e.target.value))}
                    className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  >
                    {HOURS.map((h) => (
                      <option key={h} value={h}>{formatHour(h)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 block mb-1">End</label>
                  <select
                    value={tou.off_peak?.end ?? 9}
                    onChange={(e) => updateTouField('off_peak', 'end', parseInt(e.target.value))}
                    className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  >
                    {HOURS.map((h) => (
                      <option key={h} value={h}>{formatHour(h)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 block mb-1">Rate ($/kWh)</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={tou.off_peak?.rate ?? 0.10}
                    onChange={(e) => updateTouField('off_peak', 'rate', parseFloat(e.target.value) || 0)}
                    className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  />
                </div>
              </div>
            </div>

            {/* Mid-Peak */}
            <div className="bg-yellow-900/10 border border-yellow-900/30 rounded-lg p-3">
              <div className="text-xs font-medium text-yellow-400 uppercase mb-2">Mid-Peak Rate</div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <div>
                  <label className="text-[10px] text-gray-500 block mb-1">Start</label>
                  <select
                    value={tou.mid_peak?.start ?? 9}
                    onChange={(e) => updateTouField('mid_peak', 'start', parseInt(e.target.value))}
                    className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  >
                    {HOURS.map((h) => (
                      <option key={h} value={h}>{formatHour(h)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 block mb-1">End</label>
                  <select
                    value={tou.mid_peak?.end ?? 14}
                    onChange={(e) => updateTouField('mid_peak', 'end', parseInt(e.target.value))}
                    className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  >
                    {HOURS.map((h) => (
                      <option key={h} value={h}>{formatHour(h)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 block mb-1">Rate ($/kWh)</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    value={tou.mid_peak?.rate ?? 0.18}
                    onChange={(e) => updateTouField('mid_peak', 'rate', parseFloat(e.target.value) || 0)}
                    className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2 py-1.5 text-xs focus:border-blue-500 focus:outline-none"
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="flex items-center gap-3 mt-4">
          <button
            onClick={handleSaveTou}
            disabled={!billingModeDirty || saving.tou_schedule}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              billingModeDirty
                ? 'bg-blue-600 hover:bg-blue-500 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed'
            }`}
          >
            {saving.tou_schedule ? 'Saving...' : saved.tou_schedule ? 'Saved' : 'Save Billing Mode'}
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-2">
          {billingMode === 'tou'
            ? 'Energy costs will be calculated using time-of-use rates based on the time each bucket falls in.'
            : 'All energy is billed at the flat rate above.'}
        </p>
      </div>

      {/* Timezone */}
      <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-700 dark:text-gray-300 block mb-2">
          Timezone
        </label>
        <div className="flex items-center gap-3">
          <select
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className="flex-1 max-w-xs bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          >
            {US_TIMEZONES.map((tz) => (
              <option key={tz} value={tz}>
                {TIMEZONE_LABELS[tz] || tz}
              </option>
            ))}
          </select>
          <button
            onClick={() => handleSave('timezone', timezone)}
            disabled={!timezoneDirty || saving.timezone}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              timezoneDirty
                ? 'bg-blue-600 hover:bg-blue-500 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed'
            }`}
          >
            {saving.timezone ? 'Saving...' : saved.timezone ? 'Saved' : 'Save'}
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-2">
          Determines "today" and "this month" boundaries for energy calculations.
        </p>
      </div>

      {/* Currency */}
      <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-700 dark:text-gray-300 block mb-2">
          Currency
        </label>
        <div className="flex items-center gap-3">
          <select
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="flex-1 max-w-xs bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          >
            <option value="USD">USD ($)</option>
          </select>
          <button
            onClick={() => handleSave('currency', currency)}
            disabled={!currencyDirty || saving.currency}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              currencyDirty
                ? 'bg-blue-600 hover:bg-blue-500 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed'
            }`}
          >
            {saving.currency ? 'Saving...' : saved.currency ? 'Saved' : 'Save'}
          </button>
        </div>
      </div>

      {/* Solar Quote Section */}
      <div className="pt-2">
        <h3 className="text-base font-semibold mb-1">Solar Quote</h3>
        <p className="text-sm text-gray-500 mb-4">
          Enter your solar quote details to see projected savings on the dashboard.
        </p>
      </div>

      {/* Monthly Payment */}
      <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-700 dark:text-gray-300 block mb-2">
          Monthly Solar Payment
        </label>
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-xs">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">$</span>
            <input
              type="number"
              step="1"
              min="0"
              value={solarPayment}
              onChange={(e) => setSolarPayment(e.target.value)}
              placeholder="e.g. 189"
              className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg pl-7 pr-12 py-2 text-sm focus:border-yellow-500 focus:outline-none"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">/mo</span>
          </div>
          <button
            onClick={() => handleSave('solar_monthly_payment', solarPayment)}
            disabled={!solarPaymentDirty || saving.solar_monthly_payment}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              solarPaymentDirty
                ? 'bg-yellow-600 hover:bg-yellow-500 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed'
            }`}
          >
            {saving.solar_monthly_payment ? 'Saving...' : saved.solar_monthly_payment ? 'Saved' : 'Save'}
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-2">
          Your fixed monthly payment for the solar lease/PPA/loan.
        </p>
      </div>

      {/* Annual Production */}
      <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-700 dark:text-gray-300 block mb-2">
          Estimated Annual Solar Production
        </label>
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-xs">
            <input
              type="number"
              step="100"
              min="0"
              value={solarAnnualKwh}
              onChange={(e) => setSolarAnnualKwh(e.target.value)}
              placeholder="e.g. 12000"
              className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 pr-16 py-2 text-sm focus:border-yellow-500 focus:outline-none"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">kWh/yr</span>
          </div>
          <button
            onClick={() => handleSave('solar_annual_kwh', solarAnnualKwh)}
            disabled={!solarKwhDirty || saving.solar_annual_kwh}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              solarKwhDirty
                ? 'bg-yellow-600 hover:bg-yellow-500 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed'
            }`}
          >
            {saving.solar_annual_kwh ? 'Saving...' : saved.solar_annual_kwh ? 'Saved' : 'Save'}
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-2">
          From your solar quote — the total kWh the system is expected to produce per year.
        </p>
      </div>

      {/* Net Metering */}
      <div className="bg-white dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-700 dark:text-gray-300 block mb-2">
          Net Metering
        </label>
        <div className="flex items-center gap-3">
          <select
            value={netMetering}
            onChange={(e) => setNetMetering(e.target.value)}
            className="flex-1 max-w-xs bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-yellow-500 focus:outline-none"
          >
            <option value="yes">Yes — I get credited for excess production</option>
            <option value="no">No — excess production is not credited</option>
          </select>
          <button
            onClick={() => handleSave('net_metering', netMetering)}
            disabled={!netMeteringDirty || saving.net_metering}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              netMeteringDirty
                ? 'bg-yellow-600 hover:bg-yellow-500 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed'
            }`}
          >
            {saving.net_metering ? 'Saving...' : saved.net_metering ? 'Saved' : 'Save'}
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-2">
          With net metering, excess solar production is credited to your bill at the retail rate.
          Without it, you only save on electricity you use while solar is producing.
        </p>
      </div>
    </div>
  )
}
