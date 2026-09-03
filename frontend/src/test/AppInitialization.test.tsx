import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  health: vi.fn(),
  sources: vi.fn(),
  seedDemo: vi.fn(),
  resetDemo: vi.fn(),
  latestRun: vi.fn(),
  run: vi.fn(),
  rows: vi.fn(),
  exceptions: vi.fn(),
  close: vi.fn(),
  diagnostics: vi.fn(),
  proof: vi.fn(),
  proofAction: vi.fn(),
  review: vi.fn(),
  investigate: vi.fn(),
  approveClose: vi.fn(),
}))

vi.mock('../app/api', () => ({ api: apiMock }))

import App from '../app/App'

afterEach(cleanup)

beforeEach(() => {
  vi.clearAllMocks()
  window.history.replaceState({}, '', '/workspace')
  const run = {
    run_id: 'run_saved',
    state: 'SUCCESS',
    source_snapshot_id: 'snapshot_saved',
    rule_version: '1.0',
    configuration_version: '1.0',
    records_processed: 2,
    expected_paise: 100,
    explained_paise: 100,
    unresolved_paise: 0,
    total_ms: 2,
    timings: {},
    created_at: '2026-08-26T00:00:00Z',
  }
  apiMock.sources.mockResolvedValue({ items: [{ state: 'ACCEPTED' }] })
  apiMock.health.mockResolvedValue({
    status: 'ok', ai_assistance: 'evidence_mode', identity_mode: 'INSECURE_DEMO_CONTEXT',
    provider: { configuration_status: 'not_configured', reachability_status: 'not_probed' },
  })
  apiMock.latestRun.mockResolvedValue(run)
  apiMock.rows.mockResolvedValue({ items: [
    {
      settlement_id: 'setl_PC008', utr: 'UTR008', expected_paise: 1349836, observed_paise: null,
      difference_paise: null, evidence: { utr_exact: false, amount_exact: false, settlement_ledger_consistent: true, temporal_consistency: true, candidate_count: 0, amount_delta_paise: 1349836 },
      decision: 'REVIEW_REQUIRED', exception_type: 'MISSING_BANK_CREDIT', proof_id: 'proof_008', bank_ref: null, reasons: ['Missing bank credit'],
    },
    {
      settlement_id: 'setl_PC009', utr: 'UTR009', expected_paise: 1329560, observed_paise: null,
      difference_paise: null, evidence: { utr_exact: false, amount_exact: false, settlement_ledger_consistent: true, temporal_consistency: true, candidate_count: 0, amount_delta_paise: 1329560 },
      decision: 'REVIEW_REQUIRED', exception_type: 'MISSING_BANK_CREDIT', proof_id: 'proof_009', bank_ref: null, reasons: ['Missing bank credit'],
    },
  ] })
  apiMock.exceptions.mockResolvedValue({ items: [] })
  apiMock.close.mockResolvedValue({
    run_id: 'run_saved', state: 'READY', reconciled_paise: 100, unresolved_paise: 0,
    auto_verified_count: 1, manually_reviewed_count: 0, blocking_exceptions: 0,
    unreviewable_blockers: 0, exception_count: 0, settlement_exception_count: 0,
    review_item_count: 0, total_close_blockers: 0, system_error_blockers: 0,
    integrity_blockers: 0, source_snapshot_id: 'snapshot_saved', rule_version: '1.0',
    configuration_version: '1.0',
  })
  apiMock.diagnostics.mockResolvedValue({
    run, timeline: [], slowest_stage: { stage: 'none', duration_ms: 0 }, llm_calls: 0,
    llm_input_tokens: 0, llm_output_tokens: 0, estimated_llm_cost: 'unavailable', pricing_version: null,
    provider: { configuration_status: 'not_configured', reachability_status: 'not_probed' }, proof_reproducibility_failures: 0,
    identity_mode: 'INSECURE_DEMO_CONTEXT',
  })
  apiMock.investigate.mockResolvedValue({
    status: 'ANSWERED', route: 'DIRECT_TOOL', tool_name: 'close_blockers', question: "What prevents today's close?",
    explained_paise: 100, unresolved_paise: 0, canonical: {}, narration: null, narration_status: 'not_requested',
    lines: [], proof_ids: [], calculation_count: 1, unsupported_factual_claims: 0,
    provider: { configuration_status: 'not_configured', reachability_status: 'not_probed' }, estimated_cost: 'unavailable',
    message: 'Canonical answer', answer_mode: 'CURRENT_FACT', answer_label: 'Verified from evidence',
    detail: 'Freshly checked.', recommended_actions: [], technical_details: { route: 'DIRECT_TOOL' },
    citations: { proof_ids: [], source_rows: [], support_scope: 'AGGREGATE' }, supporting_record_count: 0, run_record_count: 2,
  })
})

it('renders the public provenance landing page without initializing financial data', async () => {
  window.history.replaceState({}, '', '/')

  render(<App />)

  expect(screen.getByRole('heading', { name: 'Close every settlement with proof.' })).toBeVisible()
  expect(screen.getByText('Evidence moves. Proof stays.')).toBeVisible()
  expect(screen.getAllByRole('link', { name: 'Open evidence workspace' })[0]).toHaveAttribute('href', '/workspace')
  expect(apiMock.health).not.toHaveBeenCalled()
  expect(apiMock.sources).not.toHaveBeenCalled()
  expect(apiMock.latestRun).not.toHaveBeenCalled()
})

it('reuses persisted evidence and the latest run instead of resetting on mount', async () => {
  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Settlement reconciliation' })).toBeVisible()
  expect(apiMock.latestRun).toHaveBeenCalledOnce()
  expect(apiMock.resetDemo).not.toHaveBeenCalled()
  expect(apiMock.seedDemo).not.toHaveBeenCalled()
  expect(apiMock.run).not.toHaveBeenCalled()
  expect(screen.getByRole('complementary', { name: 'Evidence Assistant' })).toBeVisible()
  expect(screen.getByText('Read-only copilot')).toBeVisible()
})

it('seeds a compatible snapshot before running when accepted evidence has no latest run', async () => {
  apiMock.latestRun.mockRejectedValueOnce(new Error('No completed run exists'))
  apiMock.seedDemo.mockResolvedValueOnce({ snapshot_id: 'snapshot_existing', record_count: 2 })
  apiMock.run.mockResolvedValueOnce({
    run_id: 'run_seeded', state: 'SUCCESS', source_snapshot_id: 'snapshot_existing', rule_version: '2.0',
    configuration_version: '2.0', records_processed: 2, expected_paise: 100, explained_paise: 100,
    unresolved_paise: 0, total_ms: 2, timings: {}, created_at: '2026-08-26T00:00:00Z',
  })

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Settlement reconciliation' })).toBeVisible()
  expect(apiMock.seedDemo).toHaveBeenCalledOnce()
  expect(apiMock.run).toHaveBeenCalledWith('snapshot_existing')
  expect(apiMock.resetDemo).not.toHaveBeenCalled()
})

it('refreshes diagnostics after an assistant provider call without discarding the answer', async () => {
  render(<App />)
  await screen.findByRole('heading', { name: 'Settlement reconciliation' })

  await userEvent.click(screen.getByRole('button', { name: "What prevents today's close?" }))

  expect(await screen.findByText('Canonical answer')).toBeVisible()
  await waitFor(() => expect(apiMock.diagnostics).toHaveBeenCalledTimes(2))
})

it('switches among context-keyed settlement threads without calling the assistant', async () => {
  render(<App />)
  await screen.findByRole('heading', { name: 'Settlement reconciliation' })
  const rows = screen.getAllByRole('row')
  const rowEight = rows.find((row) => within(row).queryByText('setl_PC008'))!
  const rowNine = rows.find((row) => within(row).queryByText('setl_PC009'))!

  await userEvent.click(within(rowEight).getByRole('button', { name: 'Ask assistant' }))
  expect(screen.getByRole('status', { name: 'Assistant context' })).toHaveTextContent('Investigating settlement setl_PC008')
  expect(screen.getByRole('status', { name: 'Assistant context' })).toHaveFocus()
  expect(screen.getAllByRole('button', { name: /Why is this blocked\?|What evidence is missing\?|What should I do next\?|Show me the proof/ })).toHaveLength(4)
  expect(apiMock.investigate).not.toHaveBeenCalled()

  await userEvent.type(screen.getByLabelText('Ask Evidence Assistant'), 'Why is this blocked?')
  await userEvent.click(screen.getByRole('button', { name: 'Send message' }))
  expect(await screen.findByText('Canonical answer')).toBeVisible()
  expect(apiMock.investigate).toHaveBeenCalledWith(
    'run_saved',
    'Why is this blocked?',
    { settlement_id: 'setl_PC008', proof_id: 'proof_008' },
    'reconciliation',
    [],
  )

  await userEvent.click(within(rowNine).getByRole('button', { name: 'Ask assistant' }))
  expect(screen.getByRole('status', { name: 'Assistant context' })).toHaveTextContent('Investigating settlement setl_PC009')
  expect(screen.queryByText('Canonical answer')).not.toBeInTheDocument()
  expect(apiMock.investigate).toHaveBeenCalledOnce()

  await userEvent.click(within(rowEight).getByRole('button', { name: 'Ask assistant' }))
  expect(screen.getByRole('status', { name: 'Assistant context' })).toHaveTextContent('Investigating settlement setl_PC008')
  expect(screen.getByText('Canonical answer')).toBeVisible()
  expect(apiMock.investigate).toHaveBeenCalledOnce()
})

it('discards an old-run assistant response that finishes after a rerun', async () => {
  let resolveInvestigation!: (value: Awaited<ReturnType<typeof apiMock.investigate>>) => void
  apiMock.investigate.mockReturnValue(new Promise((resolve) => { resolveInvestigation = resolve }))
  apiMock.run.mockResolvedValue({
    run_id: 'run_new', state: 'SUCCESS', source_snapshot_id: 'snapshot_saved', rule_version: '1.0',
    configuration_version: '1.0', records_processed: 2, expected_paise: 100, explained_paise: 100,
    unresolved_paise: 0, total_ms: 3, timings: {}, created_at: '2026-08-26T00:01:00Z',
  })

  render(<App />)
  await screen.findByRole('heading', { name: 'Settlement reconciliation' })
  await userEvent.click(screen.getByRole('button', { name: "What prevents today's close?" }))
  await waitFor(() => expect(apiMock.investigate).toHaveBeenCalledOnce())
  await userEvent.click(screen.getByRole('button', { name: 'Run reconciliation' }))
  await waitFor(() => expect(screen.getAllByText('run_new').length).toBeGreaterThan(0))
  const diagnosticsCallsAfterRerun = apiMock.diagnostics.mock.calls.length

  await act(async () => {
    resolveInvestigation({
      status: 'ANSWERED', route: 'DIRECT_TOOL', tool_name: 'close_blockers', question: 'Old run question',
      explained_paise: 10, unresolved_paise: 90, canonical: { run_id: 'run_saved' }, narration: null,
      narration_status: 'not_requested', lines: [], proof_ids: ['proof_old'],
      calculation_count: 1, unsupported_factual_claims: 0,
      provider: { configuration_status: 'not_configured', reachability_status: 'not_probed' },
      estimated_cost: 'unavailable', message: 'Old-run answer must never reappear',
      answer_mode: 'CURRENT_FACT', answer_label: 'Verified from evidence', detail: null,
      recommended_actions: [], technical_details: { route: 'DIRECT_TOOL' },
      citations: { proof_ids: ['proof_old'], source_rows: [], support_scope: 'DIRECT' },
      supporting_record_count: 1, run_record_count: 2,
    })
  })

  expect(screen.queryByText('Old-run answer must never reappear')).not.toBeInTheDocument()
  expect(apiMock.diagnostics).toHaveBeenCalledTimes(diagnosticsCallsAfterRerun)
})
