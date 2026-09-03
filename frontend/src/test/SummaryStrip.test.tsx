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
  it('names automatic verification separately from exceptions and review workflow', () => {
    render(<SummaryStrip run={run} rows={[]} />)

    expect(screen.getByText('Expected settlement amount')).toBeVisible()
    expect(screen.getByText('Auto-verified amount')).toBeVisible()
    expect(screen.getByText('Auto-verification coverage')).toBeVisible()
    expect(screen.getByText('Settlement exceptions')).toBeVisible()
    expect(screen.getByText('Refused matches')).toBeVisible()
    expect(screen.getByText('57.9%')).toBeVisible()
    expect(screen.getByRole('progressbar', { name: 'Auto-verification money coverage' })).toHaveAttribute('aria-valuenow', '57.9')
    expect(screen.queryByText(/^Explained$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Coverage$/)).not.toBeInTheDocument()
  })
})
