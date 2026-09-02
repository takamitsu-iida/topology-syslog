import { Link } from 'react-router-dom'
import type { Incident } from '../types'

interface Props {
  incident: Incident
  onResolve?: (id: string) => void
}

type StateBadge = { label: string; cls: string }

function confidenceLabel(value: number | null) {
  if (value === null) return 'RCA -'
  return `RCA ${Math.round(value * 100)}%`
}

function getStateBadge(incident: Incident): StateBadge {
  if (incident.condition === 'RECOVERED')
    return { label: '復旧済', cls: 'bg-emerald-100 text-emerald-700' }
  if (incident.condition === 'RECOVERING')
    return { label: '復旧確認中', cls: 'bg-sky-100 text-sky-700' }
  if (incident.condition === 'DEGRADED')
    return { label: '部分復旧', cls: 'bg-yellow-100 text-yellow-700' }
  if (incident.condition === 'FLAPPING')
    return { label: 'フラッピング', cls: 'bg-amber-100 text-amber-700' }
  if (incident.status === 'CLOSED' || incident.status === 'RESOLVED')
    return { label: 'クローズ済', cls: 'bg-gray-200 text-gray-600' }
  if (incident.recurrence_count > 0)
    return { label: `再発 (${incident.recurrence_count + 1}回目)`, cls: 'bg-orange-100 text-orange-700' }
  return { label: '新規発生', cls: 'bg-red-100 text-red-700' }
}

export function IncidentCard({ incident, onResolve }: Props) {
  const isOpen = incident.status === 'OPEN'
  const state = getStateBadge(incident)

  const cardCls = {
    OPEN:     incident.recurrence_count > 0
                ? 'border-orange-300 bg-orange-50'
                : 'border-red-300 bg-red-50',
    FLAPPING: 'border-amber-300 bg-amber-50',
    RESOLVED: 'border-gray-200 bg-gray-50',
    CLOSED: 'border-gray-200 bg-gray-50',
  }[incident.status] ?? 'border-gray-200 bg-gray-50'

  return (
    <div className={`rounded-lg border p-4 shadow-sm transition-colors ${cardCls}`}>
      <div className="flex items-start justify-between gap-2">
        <Link
          to={`/incidents/${incident.incident_id}`}
          className="text-base font-semibold hover:underline"
        >
          {incident.incident_id}
        </Link>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${state.cls}`}>
          {state.label}
        </span>
      </div>

      <p className="mt-1 text-sm text-gray-700">
        <span className="font-medium">根本原因:</span>{' '}
        <span className="text-red-600 font-medium">{incident.root_cause_node}</span>
      </p>
      <p className="mt-0.5 truncate text-sm text-gray-600">
        <span className="font-medium">イベント:</span> {incident.primary_event}
      </p>

      <div className="mt-2 flex flex-wrap gap-3 text-xs text-gray-500">
        <span>影響ノード: {incident.secondary_nodes.length}</span>
        <span>ログ数: {incident.raw_log_count}</span>
        <span>{confidenceLabel(incident.rca_explanation.confidence)}</span>
        <span>{new Date(incident.created_at).toLocaleString('ja-JP')}</span>
      </div>

      {isOpen && onResolve && (
        <button
          onClick={() => onResolve(incident.incident_id)}
          className="mt-3 rounded bg-blue-500 px-3 py-1 text-sm text-white hover:bg-blue-600 active:bg-blue-700"
        >
          解決済みにする
        </button>
      )}
    </div>
  )
}
