import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listIncidents, resolveIncident, reloadTopology } from '../api/client'
import { IncidentCard } from '../components/IncidentCard'
import { useIncidentWebSocket } from '../hooks/useWebSocket'

const STATUS_FILTERS = [
  { label: 'OPEN',      value: 'OPEN' as const },
  { label: 'FLAPPING', value: 'FLAPPING' as const },
  { label: 'RESOLVED', value: 'RESOLVED' as const },
  { label: '全て',     value: undefined },
]

export function IncidentList() {
  const [statusFilter, setStatusFilter] = useState<string | undefined>('OPEN')
  const qc = useQueryClient()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['incidents', statusFilter],
    queryFn: () => listIncidents(statusFilter),
    refetchInterval: 30_000,
  })

  const resolve = useMutation({
    mutationFn: resolveIncident,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['incidents'] }),
  })

  const reload = useMutation({
    mutationFn: reloadTopology,
  })

  // 新規インシデントが WebSocket で通知されたら一覧を再取得
  useIncidentWebSocket(() => {
    void qc.invalidateQueries({ queryKey: ['incidents'] })
  })

  return (
    <div className="mx-auto max-w-3xl p-4">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">インシデント一覧</h1>
        <div className="flex items-center gap-2">
          {reload.isSuccess && (
            <span className="text-xs text-green-600">
              再読み込み完了 ({reload.data?.nodes}ノード / {reload.data?.edges}エッジ)
            </span>
          )}
          {reload.isError && (
            <span className="text-xs text-red-500">再読み込み失敗</span>
          )}
          <button
            onClick={() => reload.mutate()}
            disabled={reload.isPending}
            className="rounded border px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50"
            title="yang_topology.yaml を再読み込みしてグラフを更新します"
          >
            {reload.isPending ? '読み込み中…' : 'トポロジーを再読み込み'}
          </button>
        </div>
      </div>

      {/* ステータスフィルター */}
      <div className="mb-4 flex gap-2">
        {STATUS_FILTERS.map(({ label, value }) => (
          <button
            key={label}
            onClick={() => setStatusFilter(value)}
            className={`rounded px-3 py-1 text-sm font-medium transition-colors ${
              statusFilter === value
                ? 'bg-blue-500 text-white'
                : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {isLoading && <p className="text-gray-500">読み込み中…</p>}
      {isError && <p className="text-red-500">データ取得に失敗しました</p>}

      <div className="flex flex-col gap-3">
        {data?.incidents.map((inc) => (
          <IncidentCard
            key={inc.incident_id}
            incident={inc}
            onResolve={
              inc.status === 'OPEN' ? (id) => resolve.mutate(id) : undefined
            }
          />
        ))}
        {data?.incidents.length === 0 && (
          <p className="py-10 text-center text-gray-500">インシデントなし</p>
        )}
      </div>
    </div>
  )
}
