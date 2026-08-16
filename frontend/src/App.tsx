import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { IncidentList } from './pages/IncidentList'
import { IncidentDetail } from './pages/IncidentDetail'

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
            <span className="font-bold text-gray-800">🌐 Topology Syslog</span>
          </nav>
          <Routes>
            <Route path="/" element={<Navigate to="/incidents" replace />} />
            <Route path="/incidents" element={<IncidentList />} />
            <Route path="/incidents/:id" element={<IncidentDetail />} />
          </Routes>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
