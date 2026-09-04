// API レスポンスの型定義

export interface Incident {
  incident_id: string
  created_at: string
  root_cause_node: string
  primary_event: string
  secondary_nodes: string[]
  raw_log_count: number
  raw_logs: string[]
  status: 'OPEN' | 'CLOSED' | 'RESOLVED' | 'FLAPPING'
  condition: 'ACTIVE' | 'DEGRADED' | 'RECOVERING' | 'RECOVERED' | 'FLAPPING'
  recurrence_count: number
  last_fault_at: string | null
  last_recovery_at: string | null
  flap_count: number
  recovery_evidence: string[]
  rca_explanation: RCAExplanation
}

export interface RCAEvidence {
  source: string
  summary: string
  weight: number
  related_nodes: string[]
  related_log_ids: string[]
}

export interface RCACandidate {
  node_id: string
  confidence: number
  evidences: RCAEvidence[]
  secondary_nodes: string[]
  alternative_reason: string | null
}

export interface RCAExplanation {
  confidence: number | null
  primary_candidate: RCACandidate | null
  alternative_candidates: RCACandidate[]
}

export interface RCAEvaluation {
  evaluation_id: number
  incident_id: string
  evaluated_at: string
  reason: string
  explanation: RCAExplanation
}

export interface RCAHistoryResponse {
  evaluations: RCAEvaluation[]
  total: number
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
  status: 'running' | 'completed' | 'failed' | 'interrupted'
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

export interface NodeStateRecord {
  node_id: string
  state: 'UP' | 'DOWN' | 'DEGRADED' | 'UNKNOWN'
  observed_at: string
  expires_at: string
  reason: string
  probes: Array<{ probe_type: string; target: string; success: boolean | null; observed_at: string; latency_ms: number | null; error: string | null }>
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

export interface RawLog {
  log_id: number
  received_at: string
  source_ip: string
  hostname: string
  facility: number
  severity: number
  message: string
  vendor: string | null
  event_type: string | null
  normalized_signature: string | null
  knowledge_status: string
  knowledge_id: string | null
  event_classification: string
  event_action: string | null
  classification_reasons: Array<{ source: string; detail: string; confidence: number }>
}

export interface RawLogListResponse {
  logs: RawLog[]
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
  description?: string
  vendor?: string
  classification?: string
  correlation_role?: string
  severity_policy?: Record<string, string>
  dedup_window_sec?: number
  runbook?: string[]
  confidence?: number
  priority?: number
}
