import type {
  CloseState,
  Diagnostics,
  ExceptionItem,
  InvestigationReport,
  AssistantContext,
  ConversationTurn,
  HealthStatus,
  Proof,
  ReconciliationRow,
  RunSummary,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: { message: response.statusText } }))
    throw new Error(error.detail?.message || error.detail?.code || 'Request failed')
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<HealthStatus>('/api/health'),
  sources: () => request<{ items: Array<{ state: string }> }>('/api/sources'),
  seedDemo: () => request<{ snapshot_id: string; record_count: number }>('/api/demo/seed', { method: 'POST' }),
  /** Explicitly destructive and intentionally unused during startup. */
  resetDemo: () => request<{ snapshot_id: string; record_count: number }>('/api/demo/reset', { method: 'POST' }),
  latestRun: () => request<RunSummary>('/api/runs/latest'),
  run: (snapshotId?: string) =>
    request<RunSummary>('/api/runs', { method: 'POST', body: JSON.stringify({ snapshot_id: snapshotId ?? null }) }),
  rows: (runId: string) => request<{ items: ReconciliationRow[] }>(`/api/runs/${runId}/settlements`),
  exceptions: (runId: string) => request<{ items: ExceptionItem[] }>(`/api/exceptions?run_id=${runId}`),
  proof: (proofId: string) => request<Proof>(`/api/proofs/${proofId}`),
  proofAction: (proofId: string, action: 'reproduce' | 'reevaluate') =>
    request<Record<string, unknown>>(`/api/proofs/${proofId}/${action}`, { method: 'POST' }),
  review: (exceptionId: string, action: string, reason: string) =>
    request(`/api/exceptions/${exceptionId}/review`, {
      method: 'POST',
      body: JSON.stringify({ action, reason }),
    }),
  investigate: (runId: string, question: string, context: AssistantContext = {}, page?: string, history: ConversationTurn[] = []) =>
    request<InvestigationReport>('/api/investigations/query', {
      method: 'POST',
      body: JSON.stringify({ run_id: runId, question, page, history, ...context }),
    }),
  close: (runId: string) => request<CloseState>(`/api/close?run_id=${runId}`),
  approveClose: (runId: string, reason: string) =>
    request<CloseState>('/api/close/approve', {
      method: 'POST',
      body: JSON.stringify({ run_id: runId, reason }),
    }),
  diagnostics: (runId: string) => request<Diagnostics>(`/api/ops/diagnostics?run_id=${runId}`),
}
