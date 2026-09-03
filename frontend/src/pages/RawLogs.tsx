import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listRawLogs } from '../api/client'

const ACTION_OPTIONS = [
  { value: '', label: 'すべて' },
  { value: 'retain_only', label: '保存のみ' },
  { value: 'correlate_only', label: '相関のみ' },
  { value: 'create_incident', label: 'インシデント作成' },
  { value: 'page_immediately', label: '即時通知' },
]

const KNOWLEDGE_STATUS_OPTIONS = [
  { value: '', label: 'すべて' },
  { value: 'unknown', label: '未知' },
  { value: 'known', label: '既知' },
]

function formatTime(value: string) {
  return new Date(value).toLocaleString('ja-JP', { hour12: false })
}

export function RawLogs() {
  const [hostnameInput, setHostnameInput] = useState('')
  const [hostname, setHostname] = useState('')
  const [action, setAction] = useState('retain_only')
  const [knowledgeStatus, setKnowledgeStatus] = useState('')
  const logs = useQuery({
    queryKey: ['raw-logs', hostname, action, knowledgeStatus],
    queryFn: () => listRawLogs({ hostname, action, knowledgeStatus }),
  })

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setHostname(hostnameInput.trim())
  }

  return (
    <main className="mx-auto max-w-7xl p-4">
      <header className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
        <div><h1 className="text-2xl font-bold text-gray-800">Raw SYSLOG</h1><p className="mt-1 text-sm text-gray-500">インシデント化の有無にかかわらず、受信・分類済みの SYSLOG を確認します。</p></div>
        <span className="text-sm text-gray-500">表示件数: {logs.data?.total ?? 0}</span>
      </header>
      <form onSubmit={submit} className="mb-4 grid gap-3 border bg-white p-3 sm:grid-cols-[minmax(0,1fr)_180px_150px_auto]">
        <label className="text-xs font-medium text-gray-600">ホスト名<input value={hostnameInput} onChange={(event) => setHostnameInput(event.target.value)} placeholder="例: Leaf1" className="mt-1 w-full border px-2 py-1.5 text-sm" /></label>
        <label className="text-xs font-medium text-gray-600">処理方針<select value={action} onChange={(event) => setAction(event.target.value)} className="mt-1 w-full border px-2 py-1.5 text-sm">{ACTION_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label className="text-xs font-medium text-gray-600">知識ベース<select value={knowledgeStatus} onChange={(event) => setKnowledgeStatus(event.target.value)} className="mt-1 w-full border px-2 py-1.5 text-sm">{KNOWLEDGE_STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <button type="submit" className="self-end bg-gray-800 px-4 py-1.5 text-sm text-white hover:bg-gray-700">検索</button>
      </form>
      {logs.isError && <p className="border border-red-200 bg-red-50 p-3 text-sm text-red-700">Raw SYSLOG を取得できません。</p>}
      <section className="overflow-x-auto border bg-white">
        <table className="w-full min-w-[1050px] text-left text-sm"><thead className="bg-gray-50 text-xs text-gray-500"><tr><th className="px-3 py-2">受信時刻</th><th className="px-3 py-2">装置</th><th className="px-3 py-2">Severity</th><th className="px-3 py-2">分類 / 処理</th><th className="px-3 py-2">知識</th><th className="px-3 py-2">メッセージ</th></tr></thead><tbody>{logs.data?.logs.map((log) => <tr key={log.log_id} className="border-t align-top"><td className="whitespace-nowrap px-3 py-2 text-xs text-gray-600">{formatTime(log.received_at)}<br />{log.source_ip}</td><td className="px-3 py-2 font-medium">{log.hostname}</td><td className="px-3 py-2">S{log.severity}</td><td className="px-3 py-2 text-xs">{log.event_classification}<br /><span className="text-gray-500">{log.event_action ?? '-'}</span></td><td className="px-3 py-2 text-xs">{log.knowledge_status}<br /><span className="font-mono text-gray-500">{log.knowledge_id ?? '-'}</span></td><td className="max-w-xl px-3 py-2 font-mono text-xs break-words">{log.message}<div className="mt-1 text-gray-500">{log.normalized_signature ?? ''}</div></td></tr>)}</tbody></table>
        {!logs.isLoading && logs.data?.logs.length === 0 && <p className="p-8 text-center text-sm text-gray-500">条件に一致する Raw SYSLOG はありません。</p>}
      </section>
    </main>
  )
}