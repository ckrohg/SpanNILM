import { useState, useEffect } from 'react'
import type { Anomaly } from '../lib/api'

interface Props {
  anomalies: Anomaly[]
}

const STORAGE_KEY = 'spannilm_dismissed_anomalies'

function getDismissedIds(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return new Set(JSON.parse(raw))
  } catch { /* ignore */ }
  return new Set()
}

function saveDismissedIds(ids: Set<string>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]))
}

function anomalyId(a: Anomaly): string {
  return `${a.anomaly_type}:${a.circuit_name}:${a.timestamp.slice(0, 10)}`
}

const SEVERITY_STYLES: Record<string, { border: string; bg: string; icon: string; iconColor: string }> = {
  alert: {
    border: 'border-red-700/60',
    bg: 'bg-red-950/40 dark:bg-red-950/40 bg-red-50',
    icon: '!',
    iconColor: 'text-red-400 bg-red-900/60',
  },
  warning: {
    border: 'border-orange-700/60',
    bg: 'bg-orange-950/40 dark:bg-orange-950/40 bg-orange-50',
    icon: '!',
    iconColor: 'text-orange-400 bg-orange-900/60',
  },
  info: {
    border: 'border-yellow-700/60',
    bg: 'bg-yellow-950/30 dark:bg-yellow-950/30 bg-yellow-50',
    icon: 'i',
    iconColor: 'text-yellow-400 bg-yellow-900/60',
  },
}

const TYPE_ICONS: Record<string, string> = {
  high_energy: '\u26A1',
  extended_run: '\u23F1',
  baseline_shift: '\u2197',
  missing_device: '\u2753',
  cost_spike: '\uD83D\uDCB0',
}

export default function Anomalies({ anomalies }: Props) {
  const [dismissed, setDismissed] = useState<Set<string>>(getDismissedIds)

  useEffect(() => {
    saveDismissedIds(dismissed)
  }, [dismissed])

  const visible = anomalies.filter((a) => !dismissed.has(anomalyId(a)))

  if (visible.length === 0) return null

  function dismiss(a: Anomaly) {
    setDismissed((prev) => {
      const next = new Set(prev)
      next.add(anomalyId(a))
      return next
    })
  }

  return (
    <section>
      <h2 className="text-sm font-medium text-gray-400 mb-2">
        Anomalies ({visible.length})
      </h2>
      <div className="space-y-2">
        {visible.map((a) => {
          const style = SEVERITY_STYLES[a.severity] || SEVERITY_STYLES.info
          const typeIcon = TYPE_ICONS[a.anomaly_type] || '!'
          return (
            <div
              key={anomalyId(a)}
              className={`border rounded-xl p-3 sm:p-4 ${style.border} ${style.bg}`}
            >
              <div className="flex items-start gap-3">
                <div
                  className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold flex-shrink-0 ${style.iconColor}`}
                >
                  {typeIcon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm font-medium text-gray-800 dark:text-gray-200">
                      {a.title}
                    </span>
                    <span className="text-[10px] text-gray-500 dark:text-gray-500 uppercase tracking-wide">
                      {a.circuit_name}
                    </span>
                  </div>
                  <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed">
                    {a.description}
                  </p>
                  <div className="flex items-center gap-3 mt-1.5 text-[11px] text-gray-500">
                    <span>
                      Actual: <span className="font-mono font-medium text-gray-700 dark:text-gray-300">{a.value}</span>
                    </span>
                    <span>
                      Expected: <span className="font-mono font-medium text-gray-700 dark:text-gray-300">{a.expected}</span>
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => dismiss(a)}
                  className="text-gray-500 hover:text-gray-300 p-1 rounded transition-colors flex-shrink-0"
                  title="Dismiss"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
