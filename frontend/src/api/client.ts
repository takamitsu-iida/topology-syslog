import type { AiReport, FilterPatternsResponse, FilterReloadResponse, Incident, IncidentListResponse, InvestigationReport, KnowledgeRule, KnowledgeRuleInput, RawLogListResponse, RCAHistoryResponse, SimilarIncidentsResponse, TopologyGraphResponse, UnknownEventListResponse } from '../types'
import { getAccessToken } from '../auth'

/** 開発時は vite.config.ts の proxy が /incidents, /topology, /ws を localhost:8080 へ転送する */
const BASE = ''

function authHeaders(body?: unknown): HeadersInit | undefined {
  const token = getAccessToken()
  if (!token && body === undefined) return undefined
  return {
    ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, { headers: authHeaders() })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  return resp.json() as Promise<T>
}

async function put<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, { method: 'PUT', headers: authHeaders() })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  return resp.json() as Promise<T>
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: authHeaders(body),
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  return resp.json() as Promise<T>
}

async function deleteRequest<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, { method: 'DELETE', headers: authHeaders() })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  return resp.json() as Promise<T>
}

export const listIncidents = (status?: string): Promise<IncidentListResponse> => {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  return get<IncidentListResponse>(`/incidents${q}`)
}

export const getIncident = (id: string): Promise<Incident> =>
  get<Incident>(`/incidents/${encodeURIComponent(id)}`)

export const getRcaHistory = (id: string): Promise<RCAHistoryResponse> =>
  get<RCAHistoryResponse>(`/incidents/${encodeURIComponent(id)}/rca-history`)

export const resolveIncident = (id: string): Promise<Incident> =>
  put<Incident>(`/incidents/${encodeURIComponent(id)}/resolve`)

export const previewClosedIncidentPurge = (before: string): Promise<{ count: number }> =>
  deleteRequest<{ count: number }>(`/incidents?before=${encodeURIComponent(before)}`)

export const purgeClosedIncidents = (before: string): Promise<{ count: number }> =>
  deleteRequest<{ count: number }>(`/incidents?before=${encodeURIComponent(before)}&confirm=true`)

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

export const listUnknownEvents = (): Promise<UnknownEventListResponse> =>
  get<UnknownEventListResponse>('/knowledge/unknown-events')

export interface RawLogFilters {
  hostname?: string
  action?: string
  knowledgeStatus?: string
}

export const listRawLogs = (filters: RawLogFilters = {}): Promise<RawLogListResponse> => {
  const params = new URLSearchParams({ limit: '100' })
  if (filters.hostname) params.set('hostname', filters.hostname)
  if (filters.action) params.set('action', filters.action)
  if (filters.knowledgeStatus) params.set('knowledge_status', filters.knowledgeStatus)
  return get<RawLogListResponse>(`/raw-logs?${params}`)
}

export const previewRawLogPurge = (before: string): Promise<{ count: number }> =>
  deleteRequest<{ count: number }>(`/raw-logs?before=${encodeURIComponent(before)}`)

export const purgeRawLogs = (before: string): Promise<{ count: number }> =>
  deleteRequest<{ count: number }>(`/raw-logs?before=${encodeURIComponent(before)}&confirm=true`)

export const getUnknownEventSuggestions = (signature: string): Promise<SimilarIncidentsResponse> =>
  get<SimilarIncidentsResponse>(`/knowledge/unknown-events/${encodeURIComponent(signature)}/suggestions`)

export const listKnowledgeRules = (): Promise<KnowledgeRule[]> =>
  get<KnowledgeRule[]>('/knowledge/rules')

export const createKnowledgeRule = (rule: KnowledgeRuleInput): Promise<KnowledgeRule> =>
  post<KnowledgeRule>('/knowledge/rules', rule)

export const approveKnowledgeRule = (ruleId: string): Promise<KnowledgeRule> =>
  post<KnowledgeRule>(`/knowledge/rules/${encodeURIComponent(ruleId)}/approve`)

export const disableKnowledgeRule = (ruleId: string): Promise<KnowledgeRule> =>
  post<KnowledgeRule>(`/knowledge/rules/${encodeURIComponent(ruleId)}/disable`)
