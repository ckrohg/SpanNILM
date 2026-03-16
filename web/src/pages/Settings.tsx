import { useEffect, useState } from 'react'
import { getSettings, updateSettings, type Settings as SettingsType } from '../lib/api'

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

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold mb-1">Settings</h2>
        <p className="text-sm text-gray-500">
          Configure electricity rate, timezone, and other preferences.
        </p>
      </div>

      {/* Electricity Rate */}
      <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-300 block mb-2">
          Electricity Rate
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
              className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-7 pr-16 py-2 text-sm focus:border-blue-500 focus:outline-none"
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
                : 'bg-gray-800 text-gray-600 cursor-not-allowed'
            }`}
          >
            {saving.electricity_rate ? 'Saving...' : saved.electricity_rate ? 'Saved' : 'Save'}
          </button>
        </div>
        <p className="text-xs text-gray-600 mt-2">
          Used to calculate energy costs on the dashboard.
        </p>
      </div>

      {/* Timezone */}
      <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-300 block mb-2">
          Timezone
        </label>
        <div className="flex items-center gap-3">
          <select
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className="flex-1 max-w-xs bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
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
                : 'bg-gray-800 text-gray-600 cursor-not-allowed'
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
      <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-300 block mb-2">
          Currency
        </label>
        <div className="flex items-center gap-3">
          <select
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="flex-1 max-w-xs bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          >
            <option value="USD">USD ($)</option>
          </select>
          <button
            onClick={() => handleSave('currency', currency)}
            disabled={!currencyDirty || saving.currency}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              currencyDirty
                ? 'bg-blue-600 hover:bg-blue-500 text-white'
                : 'bg-gray-800 text-gray-600 cursor-not-allowed'
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
      <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-300 block mb-2">
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
              className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-7 pr-12 py-2 text-sm focus:border-yellow-500 focus:outline-none"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">/mo</span>
          </div>
          <button
            onClick={() => handleSave('solar_monthly_payment', solarPayment)}
            disabled={!solarPaymentDirty || saving.solar_monthly_payment}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              solarPaymentDirty
                ? 'bg-yellow-600 hover:bg-yellow-500 text-white'
                : 'bg-gray-800 text-gray-600 cursor-not-allowed'
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
      <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-300 block mb-2">
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
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 pr-16 py-2 text-sm focus:border-yellow-500 focus:outline-none"
            />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">kWh/yr</span>
          </div>
          <button
            onClick={() => handleSave('solar_annual_kwh', solarAnnualKwh)}
            disabled={!solarKwhDirty || saving.solar_annual_kwh}
            className={`px-4 py-2 text-sm rounded-lg transition-colors ${
              solarKwhDirty
                ? 'bg-yellow-600 hover:bg-yellow-500 text-white'
                : 'bg-gray-800 text-gray-600 cursor-not-allowed'
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
      <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4">
        <label className="text-sm font-medium text-gray-300 block mb-2">
          Net Metering
        </label>
        <div className="flex items-center gap-3">
          <select
            value={netMetering}
            onChange={(e) => setNetMetering(e.target.value)}
            className="flex-1 max-w-xs bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-yellow-500 focus:outline-none"
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
                : 'bg-gray-800 text-gray-600 cursor-not-allowed'
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
