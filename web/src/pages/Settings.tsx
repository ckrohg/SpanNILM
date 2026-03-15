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
    </div>
  )
}
