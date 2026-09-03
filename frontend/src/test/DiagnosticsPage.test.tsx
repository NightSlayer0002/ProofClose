import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Diagnostics } from '../app/types'
import { DiagnosticsPage } from '../pages/DiagnosticsPage'

const data: Diagnostics = {
  run: {
    run_id: 'run_timing',
    state: 'COMPLETED',
    source_snapshot_id: 'snapshot_timing',
    rule_version: '1.0.0',
    configuration_version: '1.0.0',
    records_processed: 12,
    expected_paise: 1_000_000,
    explained_paise: 500_000,
    unresolved_paise: 500_000,
    total_ms: 125,
    timings: {},
    created_at: '2026-08-26T10:00:00Z',
  },
  timeline: [
    { stage: 'ingest', duration_ms: 25, metadata: { records_processed: 12 } },
    { stage: 'reconcile', duration_ms: 100, metadata: { records_processed: 12 } },
  ],
  slowest_stage: { stage: 'reconcile', duration_ms: 100 },
  llm_calls: 0,
  llm_input_tokens: 0,
  llm_output_tokens: 0,
  estimated_llm_cost: 'unavailable',
  pricing_version: null,
  provider: { configuration_status: 'not_configured', reachability_status: 'not_probed' },
  proof_reproducibility_failures: 0,
  identity_mode: 'INSECURE_DEMO_CONTEXT',
}

describe('DiagnosticsPage', () => {
  it('sizes timeline bars only from measured duration values', () => {
    render(<DiagnosticsPage data={data} />)

    const ingestCell = screen.getByText('25ms').closest('td')
    const reconcileCell = screen.getByText('100ms').closest('td')
    expect(ingestCell?.querySelector('.duration-bar')).toHaveStyle('--duration-ratio: 0.25')
    expect(reconcileCell?.querySelector('.duration-bar')).toHaveStyle('--duration-ratio: 1')
    expect(screen.getByText('Unavailable')).toBeVisible()
  })
})
