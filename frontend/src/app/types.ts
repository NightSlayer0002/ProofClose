export type Page = 'reconciliation' | 'exceptions' | 'investigate' | 'close' | 'diagnostics'

export type Decision =
  | 'AUTO_VERIFIED'
  | 'REVIEW_REQUIRED'
  | 'REFUSED'
  | 'UNRESOLVED'
  | 'PENDING'
  | 'SYSTEM_ERROR'

export interface Evidence {
  utr_exact: boolean
  amount_exact: boolean
  settlement_ledger_consistent: boolean
  temporal_consistency: boolean
  candidate_count: number
  amount_delta_paise: number
}

export interface OrderEvidence {
  payment_row_count: number
  settled_payment_paise: number
  expected_order_payment_paise: number
  excess_payment_paise: number
}

export interface RunSummary {
  run_id: string
  state: string
  source_snapshot_id: string
  rule_version: string
  configuration_version: string
  records_processed: number
  expected_paise: number
  explained_paise: number
  unresolved_paise: number
  total_ms: number
  timings: Record<string, number>
  created_at: string
}

export interface ReconciliationRow {
  settlement_id: string
  utr: string | null
  expected_paise: number
  observed_paise: number | null
  difference_paise: number | null
  evidence: Evidence
  decision: Decision
  exception_type: string | null
  proof_id: string
  bank_ref: string | null
  reasons: string[]
}

export interface SourceReference {
  table: string
  id: string
  raw_hash: string
}

export interface Proof {
  schema_version: 'proof-object/v2'
  proof_id: string
  tenant_id: string
  run_id: string
  source_snapshot_id: string
  status: Decision
  source_rows: SourceReference[]
  subject: { subject_type: 'SETTLEMENT' | 'ORDER'; subject_id: string }
  rule_name: string
  rule_version: string
  configuration: { version: string; values: Record<string, number> }
  evidence_inputs: Record<string, unknown> & { settlement?: { settlement_id?: string; utr?: string } }
  evaluated_at: string
  formula: string
  result: { expected_paise: number; observed_paise: number | null; delta_paise: number | null }
  evidence: Evidence | OrderEvidence
  decision_score: number
  decision_reasons: string[]
  classification: string
  exception_type: string | null
  unresolved_reason: string | null
  decision_fingerprint: string
  artifact_fingerprint: string
  supersedes_proof_id: string | null
  created_at: string
}

export interface ExceptionItem {
  exception_id: string
  run_id: string
  proof_id: string
  exception_type: string
  amount_paise: number
  state: string
  created_at: string
}

export interface InvestigationLine {
  amount_paise: number
  label: string
  classification: 'OBSERVED' | 'CALCULATED' | 'INFERRED' | 'UNRESOLVED'
  proof_id: string
}

export type AnswerMode = 'CURRENT_FACT' | 'EVIDENCE_GUIDANCE' | 'GENERAL_HELP' | 'UNABLE_TO_VERIFY'

export type AnswerLabel = 'Verified from evidence' | 'Verified + guidance' | 'General guidance' | 'Unable to verify'

export interface RecommendedAction {
  code: string
  label: string
  detail: string
}

export interface AssistantCitations {
  proof_ids: string[]
  source_rows: string[]
  support_scope: 'DIRECT' | 'AGGREGATE'
}

export interface ConversationTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface InvestigationReport {
  status: string
  route: string
  tool_name?: string | null
  question: string
  explained_paise: number | null
  unresolved_paise: number | null
  canonical: Record<string, unknown>
  narration: string | null
  narration_status: string
  lines: InvestigationLine[]
  proof_ids: string[]
  citations: AssistantCitations
  supporting_record_count: number
  run_record_count: number
  calculation_count: number
  unsupported_factual_claims: number
  provider: ProviderStatus
  estimated_cost: number | string
  message: string
  answer_mode: AnswerMode
  answer_label: AnswerLabel
  detail: string | null
  recommended_actions: RecommendedAction[]
  technical_details: Record<string, unknown>
}

export interface ProviderStatus {
  configuration_status: 'not_configured' | 'configured'
  reachability_status: 'not_probed' | 'reachable' | 'unreachable'
  model?: string | null
  failure_category?: string | null
}

export interface AssistantContext {
  settlement_id?: string
  proof_id?: string
}

export type AssistantContextType = 'run' | 'settlement' | 'proof'

export interface AssistantThread {
  context: AssistantContext
  messages: InvestigationReport[]
}

export interface HealthStatus {
  status: string
  ai_assistance: 'evidence_mode' | 'ai_assisted_evidence_mode'
  identity_mode: string
  provider: ProviderStatus
}

export interface CloseState {
  run_id: string
  state: string
  reconciled_paise: number
  unresolved_paise: number
  auto_verified_count: number
  manually_reviewed_count: number
  blocking_exceptions: number
  unreviewable_blockers: number
  exception_count: number
  settlement_exception_count: number
  review_item_count: number
  total_close_blockers: number
  system_error_blockers: number
  integrity_blockers: number
  source_snapshot_id: string
  rule_version: string
  configuration_version: string
}

export interface Diagnostics {
  run: RunSummary
  timeline: Array<{ stage: string; duration_ms: number; metadata: Record<string, unknown> }>
  slowest_stage: { stage: string; duration_ms: number }
  llm_calls: number
  llm_input_tokens: number
  llm_output_tokens: number
  estimated_llm_cost: number | 'unavailable'
  pricing_version: string | null
  provider: ProviderStatus
  proof_reproducibility_failures: number
  identity_mode: string
}
