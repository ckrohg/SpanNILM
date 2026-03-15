import { useEffect, useState } from 'react'
import { DashboardData, fetchDashboard } from '../lib/api'

export function useDashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = () => {
    setLoading(true)
    setError(null)
    fetchDashboard()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    refresh()
    // Auto-refresh every 60 seconds
    const interval = setInterval(refresh, 60000)
    return () => clearInterval(interval)
  }, [])

  return { data, loading, error, refresh }
}
