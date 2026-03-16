import { useCallback, useEffect, useState } from 'react'
import { DashboardData, fetchDashboard } from '../lib/api'
import type { DateRange } from '../lib/api'

export function useDashboard(period: DateRange = 'today') {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const refresh = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchDashboard(period)
      .then((d) => {
        setData(d)
        setLastUpdated(new Date())
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [period])

  useEffect(() => {
    refresh()
    // Auto-refresh every 30 seconds
    const interval = setInterval(refresh, 30000)
    return () => clearInterval(interval)
  }, [refresh])

  return { data, loading, error, refresh, lastUpdated }
}
