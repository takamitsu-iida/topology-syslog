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

export interface CommandResult {
  device_id: string
  command: string
  output: string
  timestamp: string
  error: string | null
}

export interface InvestigationReport {
  incident_id: string
  status: 'running' | 'completed' | 'failed'
  started_at: string
  completed_at: string | null
  summary: string
  error: string | null
  commands: CommandResult[]
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

export interface FilterPatternsResponse {
  patterns: string[]
  count: number
  ignore_file: string | null
}

export interface FilterReloadResponse {
  status: string
  patterns: string[]
  count: number
}

export interface UnknownEvent {
  signature: string
  vendor: string | null
  first_seen: string
  last_seen: string
  occurrence_count: number
  severity_counts: Record<string, number>
  nodes: string[]
  representative_message: string
  representative_severity: number | null
  classification_candidate: string | null
  recommended_action: string | null
}

export interface UnknownEventListResponse {
  events: UnknownEvent[]
  total: number
}

export interface KnowledgeRule {
  rule_id: string
  signature: string
  vendor: string | null
  classification: string | null
  correlation_role: string | null
  severity_policy: Record<string, string>
  runbook: string[]
  status: 'approved' | 'pending' | 'disabled'
  confidence: number | null
  priority: number
}

export interface KnowledgeRuleInput {
  rule_id: string
  signature: string
  vendor?: string
  classification?: string
  correlation_role?: string
  severity_policy?: Record<string, string>
  runbook?: string[]
  confidence?: number
  priority?: number
}
