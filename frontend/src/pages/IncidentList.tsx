import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listIncidents, listNodeStates, listRawLogs, resolveIncident, reloadTopology, getFilterPatterns, reloadFilter } from '../api/client'
import { IncidentCard } from '../components/IncidentCard'
import { useIncidentWebSocket } from '../hooks/useWebSocket'

const STATUS_FILTERS = [
  { label: 'OPEN',      value: 'OPEN' as const },
  { label: '全て',     value: undefined },
]

const NODE_STATE_PREVIEW_LIMIT = 6
const NODE_STATE_ORDER = { DOWN: 0, DEGRADED: 1, UNKNOWN: 2, UP: 3 }
const RAW_LOG_PREVIEW_LIMIT = 5

function formatTime(value: string) {
  return new Date(value).toLocaleString('ja-JP', { hour12: false })
}

export function IncidentList() {
  const [statusFilter, setStatusFilter] = useState<string | undefined>('OPEN')
  const [showPatterns, setShowPatterns] = useState(false)
  const [showAllNodeStates, setShowAllNodeStates] = useState(false)
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

  const { data: nodeStates, isError: isNodeMonitorError } = useQuery({
    queryKey: ['node-states'],
    queryFn: listNodeStates,
    refetchInterval: 30_000,
  })

  const rawLogPreview = useQuery({
    queryKey: ['raw-logs', 'incident-empty-preview'],
    queryFn: () => listRawLogs({ limit: RAW_LOG_PREVIEW_LIMIT }),
    enabled: data?.incidents.length === 0,
    refetchInterval: 30_000,
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

  const sortedNodeStates = [...(nodeStates ?? [])].sort((left, right) => {
    const stateOrder = NODE_STATE_ORDER[left.state] - NODE_STATE_ORDER[right.state]
    return stateOrder !== 0 ? stateOrder : left.node_id.localeCompare(right.node_id)
  })
  const visibleNodeStates = showAllNodeStates ? sortedNodeStates : sortedNodeStates.slice(0, NODE_STATE_PREVIEW_LIMIT)
  const hiddenNodeStateCount = sortedNodeStates.length - visibleNodeStates.length
  const nodeStateCounts = sortedNodeStates.reduce(
    (counts, node) => ({ ...counts, [node.state]: counts[node.state] + 1 }),
    { UP: 0, DOWN: 0, DEGRADED: 0, UNKNOWN: 0 },
  )

  return (
    <div className="mx-auto max-w-7xl p-4">
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

      <section className="mb-4 border border-gray-200 bg-white p-3" aria-label="ノード状態">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold text-gray-700">ノード状態</h2>
            <p className="text-xs text-gray-500">障害・劣化ノードを優先表示 / 30秒ごとに更新</p>
          </div>
          {nodeStates && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span className="rounded bg-red-50 px-2 py-1 text-red-700">DOWN {nodeStateCounts.DOWN}</span>
              <span className="rounded bg-amber-50 px-2 py-1 text-amber-700">DEGRADED {nodeStateCounts.DEGRADED}</span>
              <span className="rounded bg-gray-100 px-2 py-1 text-gray-600">UNKNOWN {nodeStateCounts.UNKNOWN}</span>
              <span className="rounded bg-green-50 px-2 py-1 text-green-700">UP {nodeStateCounts.UP}</span>
            </div>
          )}
        </div>
        {isNodeMonitorError && <p className="text-sm text-amber-700">モニター状態を取得できません</p>}
        {nodeStates && <>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {visibleNodeStates.map((node) => <div key={node.node_id} className="border border-gray-200 px-2 py-1.5 text-sm"><div className="flex justify-between gap-2"><span className="truncate font-medium text-gray-800" title={node.node_id}>{node.node_id}</span><span className={node.state === 'UP' ? 'text-green-700' : node.state === 'DOWN' ? 'text-red-700' : node.state === 'DEGRADED' ? 'text-amber-700' : 'text-gray-500'}>{node.state}</span></div><p className="mt-1 truncate text-xs text-gray-500" title={node.reason}>{node.reason}</p><time className="text-xs text-gray-400">観測: {new Date(node.observed_at).toLocaleString()}</time></div>)}
          </div>
          {sortedNodeStates.length > NODE_STATE_PREVIEW_LIMIT && (
            <button
              type="button"
              onClick={() => setShowAllNodeStates((current) => !current)}
              className="mt-2 rounded border px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              {showAllNodeStates ? 'ノード状態を折りたたむ' : `残り${hiddenNodeStateCount}ノードを表示`}
            </button>
          )}
        </>}
      </section>

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
          <section className="border border-gray-200 bg-white p-4" aria-label="Raw SYSLOG受信状況">
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-gray-800">インシデントなし</h2>
                {rawLogPreview.isLoading && <p className="mt-1 text-sm text-gray-500">Raw SYSLOG の受信状況を確認中です。</p>}
                {rawLogPreview.isError && <p className="mt-1 text-sm text-amber-700">Raw SYSLOG の受信状況を取得できません。</p>}
                {rawLogPreview.data?.logs.length === 0 && <p className="mt-1 text-sm text-gray-500">Raw SYSLOG もまだ保存されていません。受信設定、送信元、時刻を確認してください。</p>}
                {rawLogPreview.data && rawLogPreview.data.logs.length > 0 && <p className="mt-1 text-sm text-gray-500">Raw SYSLOG は受信されています。直近のログは新規インシデント作成条件には該当していません。</p>}
              </div>
              <Link to="/raw-logs" className="rounded border px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50">Raw SYSLOG を開く</Link>
            </div>
            {rawLogPreview.data && rawLogPreview.data.logs.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-sm">
                  <thead className="border-b bg-gray-50 text-xs text-gray-500">
                    <tr><th className="px-3 py-2">受信時刻</th><th className="px-3 py-2">装置</th><th className="px-3 py-2">Severity</th><th className="px-3 py-2">処理</th><th className="px-3 py-2">メッセージ</th></tr>
                  </thead>
                  <tbody>
                    {rawLogPreview.data.logs.map((log) => (
                      <tr key={log.log_id} className="border-b last:border-b-0 align-top">
                        <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-600">{formatTime(log.received_at)}</td>
                        <td className="px-3 py-2 font-medium text-gray-800">{log.hostname}</td>
                        <td className="px-3 py-2 text-gray-700">S{log.severity}</td>
                        <td className="px-3 py-2 text-xs text-gray-600">{log.event_classification}<br /><span className="text-gray-500">{log.event_action ?? '-'}</span></td>
                        <td className="max-w-xl px-3 py-2 font-mono text-xs text-gray-700 break-words">{log.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
