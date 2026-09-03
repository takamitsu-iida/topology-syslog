import { FormEvent, lazy, Suspense, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
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
            <div className="flex flex-wrap items-center gap-4"><span className="font-bold text-gray-800">Topology Syslog</span><a href="/knowledge" className="text-sm text-gray-600 hover:text-gray-900">Knowledge Review</a><a href="/raw-logs" className="text-sm text-gray-600 hover:text-gray-900">Raw SYSLOG</a><a href="/data-management" className="text-sm text-gray-600 hover:text-gray-900">データ管理</a>{token ? <button onClick={() => { clearAccessToken(); setToken('') }} className="text-sm text-gray-600 hover:text-gray-900">ログアウト</button> : <form onSubmit={submitToken} className="flex items-center gap-1"><input value={tokenInput} onChange={(event) => setTokenInput(event.target.value)} type="password" placeholder="アクセストークン" aria-label="アクセストークン" className="w-36 border px-2 py-1 text-sm" /><button className="border px-2 py-1 text-sm text-gray-700 hover:bg-gray-50">接続</button></form>}</div>
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
