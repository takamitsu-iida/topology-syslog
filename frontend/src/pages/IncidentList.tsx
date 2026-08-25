import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listIncidents, resolveIncident, reloadTopology, getFilterPatterns, reloadFilter } from '../api/client'
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
  const [showPatterns, setShowPatterns] = useState(false)
  const qc = useQueryClient()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['incidents', statusFilter],
    queryFn: () => listIncidents(statusFilter),
    refetchInterval: 30_000,
  })

  const { data: filterData } = useQuery({
    queryKey: ['filter/patterns'],
    queryFn: getFilterPatterns,
    enabled: showPatterns,
  })

  const resolve = useMutation({
    mutationFn: resolveIncident,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['incidents'] }),
  })

  const reload = useMutation({
    mutationFn: reloadTopology,
  })

  const filterReload = useMutation({
    mutationFn: reloadFilter,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['filter/patterns'] }),
  })

  // 新規インシデントが WebSocket で通知されたら一覧を再取得
  useIncidentWebSocket(() => {
    void qc.invalidateQueries({ queryKey: ['incidents'] })
  })

  return (
    <div className="mx-auto max-w-3xl p-4">
      <div className="mb-2 flex items-center">
        <h1 className="text-2xl font-bold text-gray-800">インシデント一覧</h1>
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button
          onClick={() => reload.mutate()}
          disabled={reload.isPending}
          className="rounded border px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          title="yang_topology.yaml を再読み込みしてグラフを更新します"
        >
          {reload.isPending ? '読み込み中…' : 'トポロジーを再読み込み'}
        </button>
        <button
          onClick={() => filterReload.mutate()}
          disabled={filterReload.isPending}
          className="rounded border px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          title="syslog_ignore.txt を再読み込みしてフィルターを更新します"
        >
          {filterReload.isPending ? '読み込み中…' : 'フィルターを再読み込み'}
        </button>
        <button
          onClick={() => setShowPatterns((v) => !v)}
          className="rounded border px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
          title="現在有効な無視パターンを表示します"
        >
          {showPatterns ? 'パターンを隠す' : 'パターンを表示'}
        </button>
        {reload.isSuccess && (
          <span className="text-xs text-green-600">
            再読み込み完了 ({reload.data?.nodes}ノード / {reload.data?.edges}エッジ)
          </span>
        )}
        {reload.isError && (
          <span className="text-xs text-red-500">再読み込み失敗</span>
        )}
        {filterReload.isSuccess && (
          <span className="text-xs text-green-600">
            フィルター更新 ({filterReload.data?.count}件)
          </span>
        )}
        {filterReload.isError && (
          <span className="text-xs text-red-500">フィルター更新失敗</span>
        )}
      </div>

      {/* 無視パターン一覧 */}
      {showPatterns && (
        <div className="mb-4 rounded border bg-white p-3 shadow-sm">
          <p className="mb-1 text-xs font-semibold text-gray-500">
            無視パターン
            {filterData?.ignore_file && (
              <span className="ml-2 font-normal text-gray-400">({filterData.ignore_file})</span>
            )}
          </p>
          {filterData ? (
            filterData.patterns.length > 0 ? (
              <ul className="space-y-0.5">
                {filterData.patterns.map((p) => (
                  <li key={p} className="font-mono text-xs text-gray-700">{p}</li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-gray-400">パターンなし</p>
            )
          ) : (
            <p className="text-xs text-gray-400">読み込み中…</p>
          )}
        </div>
      )}

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
