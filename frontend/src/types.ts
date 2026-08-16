// API レスポンスの型定義

export interface Incident {
  incident_id: string
  created_at: string
  root_cause_node: string
  primary_event: string
  secondary_nodes: string[]
  raw_log_count: number
  status: 'OPEN' | 'RESOLVED'
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
