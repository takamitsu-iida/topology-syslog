import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { previewClosedIncidentPurge, previewRawLogPurge, purgeClosedIncidents, purgeRawLogs } from '../api/client'

function toUtcCutoff(date: string) {
  return new Date(`${date}T00:00:00`).toISOString()
}

export function DataManagement() {
  const [beforeDate, setBeforeDate] = useState('')
  const queryClient = useQueryClient()
  const cutoff = beforeDate ? toUtcCutoff(beforeDate) : ''
  const incidents = useQuery({ queryKey: ['purge-preview', 'incidents', cutoff], queryFn: () => previewClosedIncidentPurge(cutoff), enabled: Boolean(cutoff) })
  const rawLogs = useQuery({ queryKey: ['purge-preview', 'raw-logs', cutoff], queryFn: () => previewRawLogPurge(cutoff), enabled: Boolean(cutoff) })
  const purgeIncidents = useMutation({ mutationFn: purgeClosedIncidents, onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['purge-preview', 'incidents'] }) })
  const purgeLogs = useMutation({ mutationFn: purgeRawLogs, onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['purge-preview', 'raw-logs'] }); void queryClient.invalidateQueries({ queryKey: ['raw-logs'] }) } })

  function confirmAndPurge(kind: 'incidents' | 'raw-logs') {
    if (!cutoff) return
    const count = kind === 'incidents' ? incidents.data?.count : rawLogs.data?.count
    const label = kind === 'incidents' ? 'CLOSED インシデント' : 'Raw SYSLOG'
    if (!window.confirm(`${beforeDate} より前の ${label} ${count ?? 0} 件を完全に削除します。この操作は取り消せません。`)) return
    if (kind === 'incidents') purgeIncidents.mutate(cutoff)
    else purgeLogs.mutate(cutoff)
  }

  return (
    <main className="mx-auto max-w-3xl p-4">
      <header className="mb-6"><h1 className="text-2xl font-bold text-gray-800">データ管理</h1><p className="mt-1 text-sm text-gray-500">保存期間を過ぎたデータを個別に削除します。</p></header>
      <section className="border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900"><h2 className="font-semibold">削除は取り消せません</h2><p className="mt-1">指定日の 00:00 より前のデータが対象です。インシデントは CLOSED のものだけを削除し、OPEN のインシデントは対象外です。</p></section>
      <label className="mt-5 block max-w-xs text-sm font-medium text-gray-700">削除基準日<input type="date" value={beforeDate} onChange={(event) => setBeforeDate(event.target.value)} className="mt-1 block w-full border px-3 py-2" /></label>
      <div className="mt-5 space-y-4">
        <section className="border bg-white p-4"><h2 className="font-semibold text-gray-800">過去のインシデント</h2><p className="mt-1 text-sm text-gray-500">CLOSED のインシデントと関連する RCA 履歴を削除します。</p><div className="mt-4 flex flex-wrap items-center justify-between gap-3"><span className="text-sm text-gray-700">{beforeDate ? `削除対象: ${incidents.data?.count ?? (incidents.isLoading ? '確認中...' : 0)} 件` : '削除基準日を指定してください'}</span><button onClick={() => confirmAndPurge('incidents')} disabled={!cutoff || incidents.isLoading || purgeIncidents.isPending} className="bg-red-700 px-4 py-2 text-sm text-white hover:bg-red-800 disabled:cursor-not-allowed disabled:opacity-50">{purgeIncidents.isPending ? '削除中...' : 'CLOSED インシデントを削除'}</button></div>{purgeIncidents.isSuccess && <p className="mt-3 text-sm text-green-700">{purgeIncidents.data.count} 件を削除しました。</p>}{purgeIncidents.isError && <p className="mt-3 text-sm text-red-700">削除に失敗しました。</p>}</section>
        <section className="border bg-white p-4"><h2 className="font-semibold text-gray-800">過去の Raw SYSLOG</h2><p className="mt-1 text-sm text-gray-500">インシデント化されたログを含め、保存済みの Raw SYSLOG を削除します。</p><div className="mt-4 flex flex-wrap items-center justify-between gap-3"><span className="text-sm text-gray-700">{beforeDate ? `削除対象: ${rawLogs.data?.count ?? (rawLogs.isLoading ? '確認中...' : 0)} 件` : '削除基準日を指定してください'}</span><button onClick={() => confirmAndPurge('raw-logs')} disabled={!cutoff || rawLogs.isLoading || purgeLogs.isPending} className="bg-red-700 px-4 py-2 text-sm text-white hover:bg-red-800 disabled:cursor-not-allowed disabled:opacity-50">{purgeLogs.isPending ? '削除中...' : 'Raw SYSLOG を削除'}</button></div>{purgeLogs.isSuccess && <p className="mt-3 text-sm text-green-700">{purgeLogs.data.count} 件を削除しました。</p>}{purgeLogs.isError && <p className="mt-3 text-sm text-red-700">削除に失敗しました。</p>}</section>
      </div>
    </main>
  )
}