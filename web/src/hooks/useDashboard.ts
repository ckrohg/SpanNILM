import { useCallback, useEffect, useState } from 'react'
import { DashboardData, fetchDashboard } from '../lib/api'

export function useDashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const refresh = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchDashboard()
      .then((d) => {
        setData(d)
        setLastUpdated(new Date())
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    refresh()
    // Auto-refresh every 30 seconds
    const interval = setInterval(refresh, 30000)
    return () => clearInterval(interval)
  }, [refresh])

  return { data, loading, error, refresh, lastUpdated }
}
