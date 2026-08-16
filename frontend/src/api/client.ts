import type { Incident, IncidentListResponse, TopologyGraphResponse } from '../types'

/** バックエンド URL: 開発時は Vite proxy が転送する */
const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

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
