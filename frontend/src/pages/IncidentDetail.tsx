import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { generateAiReport, getIncident, getInvestigation, getSimilarIncidents, getTopologyGraph, startInvestigation } from '../api/client'
import { TopologyMap } from '../components/TopologyMap'

export function IncidentDetail() {
  const { id } = useParams<{ id: string }>()

  const { data: incident, isLoading } = useQuery({
    queryKey: ['incident', id],
    queryFn: () => getIncident(id!),
    enabled: !!id,
  })

  const { data: topoGraph } = useQuery({
    queryKey: ['topology-graph'],
    queryFn: getTopologyGraph,
    staleTime: 60_000,
  })

  const { data: similarData } = useQuery({
    queryKey: ['similar-incidents', id],
    queryFn: () => getSimilarIncidents(id!),
    enabled: !!id,
  })

  const [aiReport, setAiReport] = useState<string | null>(null)
  const { mutate: requestReport, isPending: isReporting, error: reportError } = useMutation({
    mutationFn: () => generateAiReport(id!),
    onSuccess: (data) => setAiReport(data.report),
  })

  const [investigationStarted, setInvestigationStarted] = useState(false)
  const { mutate: triggerInvestigation, isPending: isStarting } = useMutation({
    mutationFn: () => startInvestigation(id!),
    onSuccess: () => setInvestigationStarted(true),
  })
  const { data: investigationReport } = useQuery({
    queryKey: ['investigation', id],
    queryFn: () => getInvestigation(id!),
    enabled: investigationStarted,
    // 完了 or 失敗になるまで 3 秒ごとにポーリング
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'completed' || status === 'failed' ? false : 3000
    },
  })

  if (isLoading) return <div className="p-4 text-gray-500">読み込み中…</div>
  if (!incident) return <div className="p-4 text-red-500">インシデントが見つかりません</div>

  const isOpen = incident.status === 'OPEN'

  const stateBadge = (() => {
    if (incident.status === 'RESOLVED') return { label: '復旧済', cls: 'bg-gray-200 text-gray-600' }
    if (incident.status === 'FLAPPING') return { label: 'フラッピング', cls: 'bg-amber-100 text-amber-700' }
    if (incident.recurrence_count > 0)  return { label: `再発 (${incident.recurrence_count + 1}回目)`, cls: 'bg-orange-100 text-orange-700' }
    return { label: '新規発生', cls: 'bg-red-100 text-red-700' }
  })()

  return (
    <div className="mx-auto max-w-3xl p-4">
      <Link to="/incidents" className="text-sm text-blue-500 hover:underline">
        ← インシデント一覧
      </Link>

      <div className="mt-2 flex items-center gap-3">
        <h1 className="text-2xl font-bold text-gray-800">{incident.incident_id}</h1>
        <span className={`rounded-full px-3 py-0.5 text-sm font-medium ${stateBadge.cls}`}>
          {stateBadge.label}
        </span>
      </div>

      {/* 概要カード */}
      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="rounded-lg border bg-white p-3 shadow-sm">
          <p className="text-xs text-gray-400">根本原因ノード</p>
          <p className="mt-0.5 font-semibold text-red-600">{incident.root_cause_node}</p>
        </div>
        <div className="rounded-lg border bg-white p-3 shadow-sm">
          <p className="text-xs text-gray-400">発生時刻</p>
          <p className="mt-0.5 font-semibold text-gray-800">
            {new Date(incident.created_at).toLocaleString('ja-JP')}
          </p>
        </div>
        <div className="col-span-2 rounded-lg border bg-white p-3 shadow-sm">
          <p className="text-xs text-gray-400">主イベント</p>
          <code className="mt-0.5 block text-sm text-gray-800">{incident.primary_event}</code>
        </div>
      </div>

      {/* 二次影響ノード */}
      {incident.secondary_nodes.length > 0 && (
        <div className="mt-4 rounded-lg border bg-white p-3 shadow-sm">
          <p className="mb-2 text-xs text-gray-400">
            二次影響ノード ({incident.secondary_nodes.length})
          </p>
          <div className="flex flex-wrap gap-2">
            {incident.secondary_nodes.map((n) => (
              <span key={n} className="rounded bg-yellow-100 px-2 py-0.5 text-sm text-yellow-800">
                {n}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* トポロジービュー */}
      {topoGraph && (
        <div className="mt-4 rounded-lg border bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-base font-semibold text-gray-700">トポロジービュー</h2>
          <TopologyMap
            elements={topoGraph.elements}
            rootCauseNode={incident.root_cause_node}
            secondaryNodes={incident.secondary_nodes}
          />
          <div className="mt-3 flex gap-4 text-xs text-gray-600">
            <span className="flex items-center gap-1">
              <span className="inline-block h-3 w-3 rounded-full bg-red-400" /> 根本原因
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-3 w-3 rounded-full bg-yellow-400" /> 二次影響
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-3 w-3 rounded-full bg-blue-300" /> 正常
            </span>
          </div>
        </div>
      )}

      {/* 元SYSLOGログ */}
      {incident.raw_logs.length > 0 && (
        <div className="mt-4 rounded-lg border bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-base font-semibold text-gray-700">
            元SYSLOGログ ({incident.raw_logs.length}件)
          </h2>
          <div className="max-h-64 overflow-y-auto rounded bg-gray-900 p-3">
            {incident.raw_logs.map((log, i) => (
              <p key={i} className="font-mono text-xs leading-5 text-green-400">
                {log}
              </p>
            ))}
          </div>
        </div>
      )}

      {/* AI 障害レポート */}
      <div className="mt-4 rounded-lg border bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-700">AI 障害レポート</h2>
          <button
            onClick={() => requestReport()}
            disabled={isReporting}
            className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
          >
            {isReporting ? '生成中…' : aiReport ? '再生成' : 'AI レポートを生成'}
          </button>
        </div>

        {reportError && (
          <p className="mt-3 text-sm text-red-600">
            エラー: {(reportError as Error).message}
          </p>
        )}

        {isReporting && !aiReport && (
          <div className="mt-4 space-y-2 animate-pulse">
            <div className="h-3 rounded bg-gray-200" />
            <div className="h-3 w-5/6 rounded bg-gray-200" />
            <div className="h-3 rounded bg-gray-200" />
            <div className="h-3 w-4/6 rounded bg-gray-200" />
          </div>
        )}

        {aiReport ? (
          <div className="mt-3 rounded bg-gray-50 p-4 text-sm leading-relaxed text-gray-800">
            {aiReport.split('\n').map((line, i) => (
              <p key={i} className={line.startsWith('#') ? 'mt-3 font-semibold' : 'mt-1'}>
                {line.split(/(\*\*[^*]+\*\*)/).map((seg, j) =>
                  seg.startsWith('**') && seg.endsWith('**')
                    ? <strong key={j}>{seg.slice(2, -2)}</strong>
                    : <span key={j}>{seg}</span>
                )}
              </p>
            ))}
          </div>
        ) : (
          !isReporting && !reportError && (
            <p className="mt-3 text-sm text-gray-400">
              ボタンをクリックすると AI が障害の原因と対応策をレポートします。
            </p>
          )
        )}
      </div>

      {/* 装置調査 */}
      <div className="mt-4 rounded-lg border bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-700">装置調査 (pyATS)</h2>
          <button
            onClick={() => triggerInvestigation()}
            disabled={isStarting || investigationReport?.status === 'running'}
            className="rounded bg-teal-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
          >
            {investigationReport?.status === 'running'
              ? '調査中…'
              : isStarting
              ? '開始中…'
              : investigationReport?.status === 'completed'
              ? '再調査'
              : '調査を開始'}
          </button>
        </div>

        {!investigationStarted && !investigationReport && (
          <p className="mt-3 text-sm text-gray-400">
            ボタンをクリックすると LLM エージェントが実機に SSH 接続して状態を収集します。
          </p>
        )}

        {investigationReport?.status === 'running' && (
          <div className="mt-4 space-y-2 animate-pulse">
            <div className="h-3 rounded bg-gray-200" />
            <div className="h-3 w-5/6 rounded bg-gray-200" />
            <div className="h-3 rounded bg-gray-200" />
          </div>
        )}

        {investigationReport?.status === 'failed' && (
          <p className="mt-3 text-sm text-red-600">
            エラー: {investigationReport.error ?? '不明なエラー'}
          </p>
        )}

        {investigationReport?.status === 'completed' && (
          <div className="mt-3 space-y-3">
            <div className="rounded bg-gray-50 p-4 text-sm leading-relaxed text-gray-800">
              {investigationReport.summary.split('\n').map((line, i) => (
                <p key={i} className={line.startsWith('#') ? 'mt-3 font-semibold' : 'mt-1'}>
                  {line.split(/(\*\*[^*]+\*\*)/).map((seg, j) =>
                    seg.startsWith('**') && seg.endsWith('**')
                      ? <strong key={j}>{seg.slice(2, -2)}</strong>
                      : <span key={j}>{seg}</span>
                  )}
                </p>
              ))}
            </div>

            {investigationReport.commands.length > 0 && (
              <details className="rounded border">
                <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50">
                  実行コマンド ({investigationReport.commands.length} 件)
                </summary>
                <div className="divide-y">
                  {investigationReport.commands.map((cmd, i) => (
                    <div key={i} className="p-3">
                      <p className="text-xs text-gray-500">
                        <span className="font-semibold text-gray-700">{cmd.device_id}</span>
                        {' '}&gt; <code>{cmd.command}</code>
                      </p>
                      {cmd.error
                        ? <p className="mt-1 text-xs text-red-500">{cmd.error}</p>
                        : (
                          <pre className="mt-1 max-h-40 overflow-y-auto rounded bg-gray-900 p-2 font-mono text-xs leading-4 text-green-400 whitespace-pre-wrap">
                            {cmd.output}
                          </pre>
                        )}
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
      </div>

      {/* 類似インシデント */}
      {similarData && (
        <div className="mt-4 rounded-lg border bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-base font-semibold text-gray-700">類似インシデント</h2>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
              {similarData.source === 'rag' ? 'AI 類似検索' : '同一根本原因'}
            </span>
          </div>
          {similarData.incidents.length === 0 ? (
            <p className="text-sm text-gray-400">該当なし</p>
          ) : (
            <ul className="space-y-2">
              {similarData.incidents.map((s) => (
                <li key={s.incident_id}>
                  <Link
                    to={`/incidents/${encodeURIComponent(s.incident_id)}`}
                    className="flex items-start gap-3 rounded-lg border p-3 hover:bg-gray-50 transition-colors"
                  >
                    <span
                      className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
                        s.status === 'OPEN'
                          ? 'bg-red-100 text-red-700'
                          : s.status === 'FLAPPING'
                          ? 'bg-orange-100 text-orange-700'
                          : 'bg-gray-200 text-gray-600'
                      }`}
                    >
                      {s.status}
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800">{s.incident_id}</p>
                      <p className="text-xs text-gray-500">
                        根本原因: {s.root_cause_node} &nbsp;·&nbsp;
                        {new Date(s.created_at).toLocaleString('ja-JP')}
                      </p>
                      <code className="mt-0.5 block truncate text-xs text-gray-600">{s.primary_event}</code>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
