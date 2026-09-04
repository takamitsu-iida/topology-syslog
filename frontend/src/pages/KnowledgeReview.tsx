import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { approveKnowledgeRule, createKnowledgeRule, disableKnowledgeRule, getUnknownEventSuggestions, listKnowledgeRules, listUnknownEvents } from '../api/client'
import type { UnknownEvent } from '../types'

const CLASSIFICATION_OPTIONS = [
  { value: 'fault-signal', label: '障害シグナル' },
  { value: 'state-change', label: '状態変化' },
  { value: 'recovery', label: '復旧イベント' },
  { value: 'config-change', label: '設定変更' },
  { value: 'security', label: 'セキュリティ' },
  { value: 'retain-only', label: '保存のみ' },
  { value: 'noise', label: 'ノイズ' },
  { value: 'unknown', label: '未分類' },
]

const ACTION_OPTIONS = [
  { value: 'page_immediately', label: '即時通知' },
  { value: 'create_incident', label: 'インシデントを作成' },
  { value: 'correlate_only', label: '既存インシデントへ相関のみ' },
  { value: 'retain_only', label: '保存のみ' },
]

const CORRELATION_ROLE_BY_CLASSIFICATION: Record<string, string> = {
  'fault-signal': 'root-cause-candidate',
  'state-change': 'secondary-impact',
  recovery: 'recovery',
  'config-change': 'informational',
  security: 'security',
  'retain-only': 'informational',
  noise: 'informational',
  unknown: 'review-required',
}

function severitySummary(counts: Record<string, number>) {
  return Object.entries(counts)
    .sort(([left], [right]) => Number(left) - Number(right))
    .map(([severity, count]) => `S${severity}: ${count}`)
    .join(' / ')
}

function ruleIdFromSignature(signature: string) {
  return signature.replace(/[^A-Z0-9]+/gi, '-').replace(/(^-|-$)/g, '').toLowerCase()
}

export function KnowledgeReview() {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<UnknownEvent | null>(null)
  const [ruleId, setRuleId] = useState('')
  const [description, setDescription] = useState('')
  const [vendor, setVendor] = useState('')
  const [classification, setClassification] = useState('fault-signal')
  const [action, setAction] = useState('create_incident')
  const [dedupWindow, setDedupWindow] = useState('120')
  const [confidence, setConfidence] = useState('0.7')
  const [priority, setPriority] = useState('80')
  const [runbook, setRunbook] = useState('')
  const [createdRuleId, setCreatedRuleId] = useState<string | null>(null)
  const events = useQuery({ queryKey: ['knowledge', 'unknown-events'], queryFn: listUnknownEvents })
  const rules = useQuery({ queryKey: ['knowledge', 'rules'], queryFn: listKnowledgeRules })
  const suggestions = useQuery({
    queryKey: ['knowledge', 'suggestions', selected?.signature],
    queryFn: () => getUnknownEventSuggestions(selected!.signature),
    enabled: selected !== null,
  })
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ['knowledge'] }) }
  const create = useMutation({
    mutationFn: createKnowledgeRule,
    onSuccess: (rule) => {
      setCreatedRuleId(rule.rule_id)
      refresh()
    },
  })
  const approve = useMutation({ mutationFn: approveKnowledgeRule, onSuccess: refresh })
  const disable = useMutation({ mutationFn: disableKnowledgeRule, onSuccess: refresh })

  function selectEvent(event: UnknownEvent) {
    setSelected(event)
    setRuleId(ruleIdFromSignature(event.signature))
    setDescription(`${event.signature} を検知した際の処理ルール。`)
    setVendor(event.vendor ?? '')
    setClassification(event.classification_candidate && event.classification_candidate !== 'unknown' ? event.classification_candidate : 'fault-signal')
    setAction(event.recommended_action && event.recommended_action !== 'review' ? event.recommended_action : 'create_incident')
    setDedupWindow('120')
    setConfidence('0.7')
    setPriority('80')
    setRunbook('')
    setCreatedRuleId(null)
    create.reset()
  }

  function submitRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selected || !ruleId.trim()) return
    create.mutate({
      rule_id: ruleId.trim(),
      signature: selected.signature,
      description: description.trim() || undefined,
      vendor: vendor.trim() || undefined,
      classification,
      correlation_role: CORRELATION_ROLE_BY_CLASSIFICATION[classification] ?? 'review-required',
      severity_policy: { '0-7': action },
      dedup_window_sec: Number(dedupWindow),
      runbook: runbook.split('\n').map((item) => item.trim()).filter(Boolean),
      confidence: Number(confidence),
      priority: Number(priority),
    })
  }

  return (
    <main className="mx-auto max-w-7xl p-4">
      <header className="mb-5 flex items-baseline justify-between gap-3">
        <div><h1 className="text-2xl font-bold text-gray-800">SYSLOG Knowledge Review</h1><p className="mt-1 text-sm text-gray-500">未知メッセージをルールの下書きにし、内容を確認してから有効化します。</p></div>
        <span className="text-sm text-gray-500">未知イベント: {events.data?.total ?? 0}</span>
      </header>
      {events.isError && <p className="border border-red-200 bg-red-50 p-3 text-sm text-red-700">SKB が未設定、または未知イベントを取得できません。</p>}
      <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
        <section><h2 className="mb-2 text-sm font-semibold text-gray-700">未知イベント</h2><div className="overflow-x-auto border bg-white"><table className="w-full text-left text-sm"><thead className="bg-gray-50 text-xs text-gray-500"><tr><th className="px-3 py-2">シグネチャ</th><th className="px-3 py-2">件数</th><th className="px-3 py-2">Severity</th><th className="px-3 py-2">分類候補</th><th className="px-3 py-2">処理方針</th></tr></thead><tbody>{events.data?.events.map((item) => <tr key={item.signature} onClick={() => selectEvent(item)} className={`cursor-pointer border-t hover:bg-blue-50 ${selected?.signature === item.signature ? 'bg-blue-50' : ''}`}><td className="px-3 py-2 font-mono text-xs">{item.signature}</td><td className="px-3 py-2">{item.occurrence_count}</td><td className="px-3 py-2 text-xs">S{item.representative_severity ?? '-'} / {severitySummary(item.severity_counts)}</td><td className="px-3 py-2 text-xs">{item.classification_candidate ?? 'unknown'}</td><td className="px-3 py-2 text-xs">{item.recommended_action ?? 'review'}</td></tr>)}</tbody></table>{events.data?.events.length === 0 && <p className="p-8 text-center text-sm text-gray-500">未知イベントはありません</p>}</div></section>
        <section className="border bg-white p-4"><h2 className="text-sm font-semibold text-gray-700">ルール下書き</h2>{!selected ? <p className="mt-4 text-sm text-gray-500">未知イベントを選択してください。</p> : <><p className="mt-3 font-mono text-sm">{selected.signature}</p><p className="mt-1 text-xs text-gray-500">ノード: {selected.nodes.join(', ')} / 代表 Severity: S{selected.representative_severity ?? '-'} / {severitySummary(selected.severity_counts)}</p><p className="mt-3 bg-gray-50 p-2 text-xs text-gray-700">{selected.representative_message}</p><h3 className="mt-4 text-xs font-semibold text-gray-600">類似インシデント ({suggestions.data?.source ?? '読み込み中'})</h3><ul className="mt-1 space-y-1 text-xs text-gray-600">{suggestions.data?.incidents.map((incident) => <li key={incident.incident_id}>{incident.incident_id}: {incident.primary_event}</li>)}{suggestions.data?.incidents.length === 0 && <li>類似インシデントはありません</li>}</ul><form onSubmit={submitRule} className="mt-4 space-y-3 border-t pt-4"><div className="grid gap-2 sm:grid-cols-2"><label className="block text-xs font-medium text-gray-600">ルール ID<input value={ruleId} onChange={(event) => setRuleId(event.target.value)} className="mt-1 w-full border px-2 py-1.5 text-sm" required /></label><label className="block text-xs font-medium text-gray-600">ベンダー<input value={vendor} onChange={(event) => setVendor(event.target.value)} placeholder="未指定で全ベンダー対象" className="mt-1 w-full border px-2 py-1.5 text-sm" /></label></div><label className="block text-xs font-medium text-gray-600">説明<textarea value={description} onChange={(event) => setDescription(event.target.value)} className="mt-1 min-h-16 w-full border px-2 py-1.5 text-sm" /></label><div className="grid gap-2 sm:grid-cols-2"><label className="block text-xs font-medium text-gray-600">分類カテゴリ<select value={classification} onChange={(event) => setClassification(event.target.value)} className="mt-1 w-full border px-2 py-1.5 text-sm">{CLASSIFICATION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label><label className="block text-xs font-medium text-gray-600">Severity 0-7 の処理<select value={action} onChange={(event) => setAction(event.target.value)} className="mt-1 w-full border px-2 py-1.5 text-sm">{ACTION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label></div><div className="grid gap-2 sm:grid-cols-3"><label className="block text-xs font-medium text-gray-600">重複抑止（秒）<input value={dedupWindow} onChange={(event) => setDedupWindow(event.target.value)} type="number" min="0" className="mt-1 w-full border px-2 py-1.5 text-sm" required /></label><label className="block text-xs font-medium text-gray-600">信頼度<input value={confidence} onChange={(event) => setConfidence(event.target.value)} type="number" min="0" max="1" step="0.05" className="mt-1 w-full border px-2 py-1.5 text-sm" required /></label><label className="block text-xs font-medium text-gray-600">優先度<input value={priority} onChange={(event) => setPriority(event.target.value)} type="number" min="0" className="mt-1 w-full border px-2 py-1.5 text-sm" required /></label></div><p className="border border-gray-200 bg-gray-50 px-2 py-1.5 text-xs text-gray-600">correlation_role: {CORRELATION_ROLE_BY_CLASSIFICATION[classification] ?? 'review-required'} / severity_policy: 0-7 = {action}</p><label className="block text-xs font-medium text-gray-600">Runbook（1 行 1 コマンド）<textarea value={runbook} onChange={(event) => setRunbook(event.target.value)} className="mt-1 min-h-16 w-full border px-2 py-1.5 text-sm" /></label>{create.isError && <p className="border border-red-200 bg-red-50 p-2 text-xs text-red-700">作成に失敗しました: {create.error.message}</p>}{createdRuleId && <p className="border border-green-200 bg-green-50 p-2 text-xs text-green-700">「{createdRuleId}」を保留ルールとして rules.yaml に保存しました。下の一覧から承認できます。</p>}<button disabled={create.isPending} className="bg-gray-800 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50">{create.isPending ? '保存中...' : '保留ルールを作成'}</button></form></>}</section>
      </div>
      <section className="mt-6"><h2 className="mb-2 text-sm font-semibold text-gray-700">知識ルール</h2><div className="overflow-x-auto border bg-white"><table className="w-full text-left text-sm"><thead className="bg-gray-50 text-xs text-gray-500"><tr><th className="px-3 py-2">ID</th><th className="px-3 py-2">シグネチャ</th><th className="px-3 py-2">分類</th><th className="px-3 py-2">Severity Policy</th><th className="px-3 py-2">状態</th><th className="px-3 py-2"></th></tr></thead><tbody>{rules.data?.map((rule) => <tr key={rule.rule_id} className="border-t"><td className="px-3 py-2">{rule.rule_id}</td><td className="px-3 py-2 font-mono text-xs">{rule.signature}</td><td className="px-3 py-2 text-xs">{rule.classification ?? '-'}</td><td className="px-3 py-2 text-xs">{Object.entries(rule.severity_policy).map(([range, policy]) => `${range}: ${policy}`).join(' / ') || '-'}</td><td className="px-3 py-2">{rule.status}</td><td className="px-3 py-2 text-right">{rule.status === 'pending' && <button onClick={() => approve.mutate(rule.rule_id)} className="mr-2 text-xs text-blue-700">承認</button>}{rule.status !== 'disabled' && <button onClick={() => disable.mutate(rule.rule_id)} className="text-xs text-red-700">無効化</button>}</td></tr>)}</tbody></table></div></section>
    </main>
  )
}
