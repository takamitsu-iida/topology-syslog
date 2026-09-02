import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { IncidentList } from './pages/IncidentList'
import { IncidentDetail } from './pages/IncidentDetail'
import { KnowledgeReview } from './pages/KnowledgeReview'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: 1 },
  },
})

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-screen bg-gray-100">
          <nav className="border-b bg-white px-6 py-3 shadow-sm">
            <div className="flex items-center gap-4"><span className="font-bold text-gray-800">Topology Syslog</span><a href="/knowledge" className="text-sm text-gray-600 hover:text-gray-900">Knowledge Review</a></div>
          </nav>
          <Routes>
            <Route path="/" element={<Navigate to="/incidents" replace />} />
            <Route path="/incidents" element={<IncidentList />} />
            <Route path="/incidents/:id" element={<IncidentDetail />} />
            <Route path="/knowledge" element={<KnowledgeReview />} />
          </Routes>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
