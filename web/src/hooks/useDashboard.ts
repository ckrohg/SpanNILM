import { useCallback, useEffect, useRef, useState } from 'react'
import { DashboardData, fetchDashboard } from '../lib/api'
import type { DateRange } from '../lib/api'

export function useDashboard(period: DateRange = 'today') {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true) // Only true on initial load
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const hasLoadedOnce = useRef(false)

  const refresh = useCallback(() => {
    // Only show full loading state on first load — subsequent refreshes are silent
    if (!hasLoadedOnce.current) {
      setLoading(true)
    }
    setError(null)
    fetchDashboard(period)
      .then((d) => {
        setData(d)
        setLastUpdated(new Date())
        hasLoadedOnce.current = true
      })
      .catch((e) => {
        // Only set error if we have no data yet
        if (!hasLoadedOnce.current) {
          setError(e.message)
        }
      })
      .finally(() => setLoading(false))
  }, [period])

  useEffect(() => {
    // Reset for new period
    hasLoadedOnce.current = false
    setLoading(true)
    refresh()
    const interval = setInterval(refresh, 30000)
    return () => clearInterval(interval)
  }, [refresh])

  return { data, loading, error, refresh, lastUpdated }
}
