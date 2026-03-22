import { useEffect, useRef, useState } from 'react'
import { DashboardData, fetchDashboard } from '../lib/api'
import type { DateRange } from '../lib/api'

export function useDashboard(period: DateRange = 'today') {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const fetchId = useRef(0) // tracks which fetch is current (prevents stale responses)

  useEffect(() => {
    // Increment fetch ID — any in-flight requests with older IDs will be ignored
    const thisId = ++fetchId.current

    // Only show skeleton if we have NO data at all (first ever load)
    if (!data) {
      setLoading(true)
    }

    fetchDashboard(period)
      .then((d) => {
        // Only apply if this is still the current fetch (not superseded by a newer period change)
        if (fetchId.current === thisId) {
          setData(d)
          setLastUpdated(new Date())
          setError(null)
          setLoading(false)
        }
      })
      .catch((e) => {
        if (fetchId.current === thisId) {
          if (!data) setError(e.message)
          setLoading(false)
        }
      })

    // Auto-refresh every 30 seconds
    const interval = setInterval(() => {
      const refreshId = ++fetchId.current
      fetchDashboard(period)
        .then((d) => {
          if (fetchId.current === refreshId) {
            setData(d)
            setLastUpdated(new Date())
          }
        })
        .catch(() => {}) // silent failure on background refresh
    }, 30000)

    return () => clearInterval(interval)
  }, [period]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => {
    const thisId = ++fetchId.current
    fetchDashboard(period)
      .then((d) => {
        if (fetchId.current === thisId) {
          setData(d)
          setLastUpdated(new Date())
          setError(null)
        }
      })
      .catch(() => {})
  }

  return { data, loading, error, refresh, lastUpdated }
}
