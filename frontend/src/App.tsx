import { FormEvent, lazy, Suspense, useState } from 'react'
import { BrowserRouter, Link, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { clearAccessToken, getAccessToken, setAccessToken } from './auth'

const IncidentList = lazy(() => import('./pages/IncidentList').then((module) => ({ default: module.IncidentList })))
const IncidentDetail = lazy(() => import('./pages/IncidentDetail').then((module) => ({ default: module.IncidentDetail })))
const KnowledgeReview = lazy(() => import('./pages/KnowledgeReview').then((module) => ({ default: module.KnowledgeReview })))
const RawLogs = lazy(() => import('./pages/RawLogs').then((module) => ({ default: module.RawLogs })))
const DataManagement = lazy(() => import('./pages/DataManagement').then((module) => ({ default: module.DataManagement })))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: 1 },
  },
})

export function App() {
  const [token, setToken] = useState(() => getAccessToken() ?? '')
  const [tokenInput, setTokenInput] = useState('')

  function submitToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!tokenInput.trim()) return
    setAccessToken(tokenInput.trim())
    setToken(tokenInput.trim())
    setTokenInput('')
  }

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-screen bg-gray-100">
          <nav className="border-b bg-white px-6 py-3 shadow-sm">
            <div className="flex flex-wrap items-center gap-4"><Link to="/incidents" aria-label="Topology Syslogのトップへ戻る" title="トップへ戻る" className="flex items-center gap-2 font-bold text-gray-800 hover:text-gray-600"><img src="/topology-syslog.svg" alt="" className="h-8 w-8" /> <span>Topology Syslog</span></Link><Link to="/knowledge" className="text-sm text-gray-600 hover:text-gray-900">Knowledge Review</Link><Link to="/raw-logs" className="text-sm text-gray-600 hover:text-gray-900">Raw SYSLOG</Link><Link to="/data-management" className="text-sm text-gray-600 hover:text-gray-900">データ管理</Link>{token ? <div className="ml-auto flex items-center gap-2"><span className="text-xs text-green-700">認証済み</span><button onClick={() => { clearAccessToken(); setToken('') }} className="text-sm text-gray-600 hover:text-gray-900">ログアウト</button></div> : <form onSubmit={submitToken} className="ml-auto flex flex-wrap items-center justify-end gap-2"><label className="flex items-center gap-2"><span className="text-sm font-medium text-gray-700">認証トークン</span><input value={tokenInput} onChange={(event) => setTokenInput(event.target.value)} type="password" placeholder="管理者から受け取った文字列" aria-label="認証トークン" aria-describedby="token-help" className="w-56 border px-2 py-1 text-sm" /></label><button className="border px-2 py-1 text-sm text-gray-700 hover:bg-gray-50">ログイン</button><span id="token-help" className="basis-full text-right text-xs text-gray-500">操作権限を確認するための秘密文字列です。システム管理者から受け取り、この画面を閉じるまで保持されます。</span></form>}</div>
          </nav>
          <Suspense fallback={<div className="p-4 text-gray-500">読み込み中...</div>}>
            <Routes>
              <Route path="/" element={<Navigate to="/incidents" replace />} />
              <Route path="/incidents" element={<IncidentList />} />
              <Route path="/incidents/:id" element={<IncidentDetail />} />
              <Route path="/knowledge" element={<KnowledgeReview />} />
              <Route path="/raw-logs" element={<RawLogs />} />
              <Route path="/data-management" element={<DataManagement />} />
            </Routes>
          </Suspense>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
