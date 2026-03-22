import { useCallback, useEffect, useRef, useState } from 'react'
import { DashboardData, fetchDashboard } from '../lib/api'
import type { DateRange } from '../lib/api'

export function useDashboard(period: DateRange = 'today') {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const isFetching = useRef(false)

  const refresh = useCallback(() => {
    // Don't show loading spinner if we already have data — keep it visible
    // Only show skeleton on very first load (data === null)
    if (!data) {
      setLoading(true)
    }

    if (isFetching.current) return // prevent concurrent fetches
    isFetching.current = true

    fetchDashboard(period)
      .then((d) => {
        setData(d)
        setLastUpdated(new Date())
        setError(null)
      })
      .catch((e) => {
        // Only show error if we have no data at all
        if (!data) {
          setError(e.message)
        }
      })
      .finally(() => {
        setLoading(false)
        isFetching.current = false
      })
  }, [period, data])

  useEffect(() => {
    // Fetch immediately on period change — old data stays visible until new arrives
    refresh()
    const interval = setInterval(refresh, 30000)
    return () => clearInterval(interval)
  }, [period]) // eslint-disable-line react-hooks/exhaustive-deps

  return { data, loading, error, refresh, lastUpdated }
}
