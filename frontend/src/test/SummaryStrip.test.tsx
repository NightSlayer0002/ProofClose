import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { RunSummary } from '../app/types'
import { SummaryStrip } from '../components/SummaryStrip'

const run: RunSummary = {
  run_id: 'run_coverage',
  state: 'COMPLETED',
  source_snapshot_id: 'snapshot_coverage',
  rule_version: '1.0.0',
  configuration_version: '1.0.0',
  records_processed: 12,
  expected_paise: 1_000_000,
  explained_paise: 579_186,
  unresolved_paise: 420_814,
  total_ms: 267,
  timings: {},
  created_at: '2026-08-26T10:00:00Z',
}

describe('SummaryStrip', () => {
  it('derives the coverage treatment from explained and expected money', () => {
    render(<SummaryStrip run={run} rows={[]} />)

    expect(screen.getByText('57.9%')).toBeVisible()
    expect(screen.getByRole('progressbar', { name: 'Explained money coverage' })).toHaveAttribute('aria-valuenow', '57.9')
  })
})
