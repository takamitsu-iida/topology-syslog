import type { AiReport, FilterPatternsResponse, FilterReloadResponse, Incident, IncidentListResponse, InvestigationReport, SimilarIncidentsResponse, TopologyGraphResponse } from '../types'

/** 開発時は vite.config.ts の proxy が /incidents, /topology, /ws を localhost:8080 へ転送する */
const BASE = ''

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  return resp.json() as Promise<T>
}

async function put<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, { method: 'PUT' })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  return resp.json() as Promise<T>
}

async function post<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, { method: 'POST' })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  return resp.json() as Promise<T>
}

export const listIncidents = (status?: string): Promise<IncidentListResponse> => {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  return get<IncidentListResponse>(`/incidents${q}`)
}

export const getIncident = (id: string): Promise<Incident> =>
  get<Incident>(`/incidents/${encodeURIComponent(id)}`)

export const resolveIncident = (id: string): Promise<Incident> =>
  put<Incident>(`/incidents/${encodeURIComponent(id)}/resolve`)

export const getTopologyGraph = (): Promise<TopologyGraphResponse> =>
  get<TopologyGraphResponse>('/topology/graph')

export const reloadTopology = (): Promise<{ status: string; nodes: number; edges: number }> =>
  post('/topology/reload')

export const getFilterPatterns = (): Promise<FilterPatternsResponse> =>
  get<FilterPatternsResponse>('/filter/patterns')

export const reloadFilter = (): Promise<FilterReloadResponse> =>
  post<FilterReloadResponse>('/filter/reload')

export const generateAiReport = (id: string): Promise<AiReport> =>
  post<AiReport>(`/incidents/${encodeURIComponent(id)}/report`)

export const getSimilarIncidents = (id: string): Promise<SimilarIncidentsResponse> =>
  get<SimilarIncidentsResponse>(`/incidents/${encodeURIComponent(id)}/similar`)

export const startInvestigation = (id: string): Promise<{ incident_id: string; status: string }> =>
  post(`/incidents/${encodeURIComponent(id)}/investigation`)

export const getInvestigation = (id: string): Promise<InvestigationReport> =>
  get<InvestigationReport>(`/incidents/${encodeURIComponent(id)}/investigation`)
