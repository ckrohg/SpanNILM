import { useEffect, useState } from 'react'
import { AnalysisResponse, runAnalysis } from '../lib/api'

export function useAnalysis(hoursBack = 24) {
  const [data, setData] = useState<AnalysisResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    runAnalysis(hoursBack)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [hoursBack])

  return { data, loading, error }
}
