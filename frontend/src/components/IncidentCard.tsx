import { Link } from 'react-router-dom'
import type { Incident } from '../types'

interface Props {
  incident: Incident
  onResolve?: (id: string) => void
}

type StatusBadge = { label: string; cls: string }
type ConditionBadge = { label: string; cls: string }

function confidenceLabel(value: number | null) {
  if (value === null) return 'RCA -'
  return `RCA ${Math.round(value * 100)}%`
}

function getStatusBadge(incident: Incident): StatusBadge {
  if (incident.status === 'OPEN')
    return { label: 'オープン', cls: 'bg-red-100 text-red-700' }
  return { label: 'クローズ済', cls: 'bg-gray-200 text-gray-600' }
}

function getConditionBadge(incident: Incident): ConditionBadge {
  if (incident.condition === 'RECOVERED')
    return { label: '復旧済', cls: 'bg-emerald-100 text-emerald-700' }
  if (incident.condition === 'RECOVERING')
    return { label: '復旧確認中', cls: 'bg-sky-100 text-sky-700' }
  if (incident.condition === 'DEGRADED')
    return { label: '部分復旧', cls: 'bg-yellow-100 text-yellow-700' }
  if (incident.recurrence_count > 0)
    return { label: `再発 (${incident.recurrence_count + 1}回目)`, cls: 'bg-orange-100 text-orange-700' }
  return { label: '障害継続中', cls: 'bg-red-100 text-red-700' }
}

export function IncidentCard({ incident, onResolve }: Props) {
  const isOpen = incident.status === 'OPEN'
  const status = getStatusBadge(incident)
  const condition = getConditionBadge(incident)
  const impactCount = incident.rca_explanation.impact_objects.length
  const childCount = incident.child_incident_ids.length
  const bgpSessionImpacts = incident.rca_explanation.impact_objects.filter((objectId) => objectId.startsWith('BGPSession:'))
  const isBgpImpact = incident.relationship_type === 'impact' && incident.root_cause_object?.startsWith('BGPSession:')

  const cardCls = {
    OPEN:     incident.recurrence_count > 0
                ? 'border-orange-300 bg-orange-50'
                : 'border-red-300 bg-red-50',
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
        <div className="flex shrink-0 flex-wrap justify-end gap-1">
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${status.cls}`}>
            {status.label}
          </span>
          {isOpen && (
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${condition.cls}`}>
              {condition.label}
            </span>
          )}
          {isBgpImpact && (
            <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700">
              BGP影響
            </span>
          )}
        </div>
      </div>

      <p className="mt-1 text-sm text-gray-700">
        <span className="font-medium">根本原因:</span>{' '}
        <span className="text-red-600 font-medium">{incident.root_cause_object ?? incident.root_cause_node}</span>
      </p>
      <p className="mt-0.5 truncate text-sm text-gray-600">
        <span className="font-medium">イベント:</span> {incident.primary_event}
      </p>

      {incident.parent_incident_id && (
        <p className="mt-1 text-xs text-gray-600">
          親インシデント:{' '}
          <Link to={`/incidents/${incident.parent_incident_id}`} className="text-blue-600 hover:underline">
            {incident.parent_incident_id}
          </Link>
        </p>
      )}

      {bgpSessionImpacts.length > 0 && (
        <div className="mt-2 border-l-2 border-sky-300 pl-2 text-sm text-sky-900">
          <span className="font-medium">BGP影響:</span>{' '}
          {bgpSessionImpacts.join(', ')}
        </div>
      )}

      <div className="mt-2 flex flex-wrap gap-3 text-xs text-gray-500">
        <span>影響ノード: {incident.secondary_nodes.length}</span>
        {impactCount > 0 && <span>影響オブジェクト: {impactCount}</span>}
        {childCount > 0 && <span>子インシデント: {childCount}</span>}
        <span>ログ数: {incident.raw_log_count}</span>
        <span>{confidenceLabel(incident.rca_explanation.confidence)}</span>
        <span>受信時刻: {new Date(incident.created_at).toLocaleString('ja-JP', { hour12: false })}</span>
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
