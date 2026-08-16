import { Link } from 'react-router-dom'
import type { Incident } from '../types'

interface Props {
  incident: Incident
  onResolve?: (id: string) => void
}

export function IncidentCard({ incident, onResolve }: Props) {
  const isOpen = incident.status === 'OPEN'

  return (
    <div
      className={`rounded-lg border p-4 shadow-sm transition-colors ${
        isOpen ? 'border-red-300 bg-red-50' : 'border-gray-200 bg-gray-50'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <Link
          to={`/incidents/${incident.incident_id}`}
          className="text-base font-semibold hover:underline"
        >
          {incident.incident_id}
        </Link>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
            isOpen ? 'bg-red-100 text-red-700' : 'bg-gray-200 text-gray-600'
          }`}
        >
          {incident.status}
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
