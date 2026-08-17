// API レスポンスの型定義

export interface Incident {
  incident_id: string
  created_at: string
  root_cause_node: string
  primary_event: string
  secondary_nodes: string[]
  raw_log_count: number
  raw_logs: string[]
  status: 'OPEN' | 'RESOLVED' | 'FLAPPING'
  recurrence_count: number
}

export interface AiReport {
  incident_id: string
  report: string
}

export interface SimilarIncident {
  incident_id: string
  root_cause_node: string
  created_at: string
  primary_event: string
  status: 'OPEN' | 'RESOLVED' | 'FLAPPING'
}

export interface SimilarIncidentsResponse {
  incidents: SimilarIncident[]
  source: 'rag' | 'db'
}

export interface IncidentListResponse {
  incidents: Incident[]
  total: number
}

export interface TopologyNodeData {
  id: string
  role: string
}

export interface CytoscapeElement {
  data: Record<string, string>
}

export interface TopologyGraphResponse {
  elements: {
    nodes: CytoscapeElement[]
    edges: CytoscapeElement[]
  }
}
