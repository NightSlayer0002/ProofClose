import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { CloseState, ExceptionItem } from '../app/types'
import { ClosePage } from '../pages/ClosePage'
import { ExceptionsPage } from '../pages/ExceptionsPage'

const exceptions: ExceptionItem[] = [
  {
    exception_id: 'exc_open',
    run_id: 'run_1',
    proof_id: 'proof_1',
    exception_type: 'MISSING_BANK_CREDIT',
    amount_paise: 475000,
    state: 'OPEN',
    created_at: '2026-08-26T10:00:00Z',
  },
  {
    exception_id: 'exc_reviewed',
    run_id: 'run_1',
    proof_id: 'proof_2',
    exception_type: 'AMBIGUOUS_MATCH',
    amount_paise: 475000,
    state: 'LEFT_UNRESOLVED',
    created_at: '2026-08-26T10:01:00Z',
  },
]

const baseClose: CloseState = {
  run_id: 'run_1',
  state: 'BLOCKED',
  reconciled_paise: 525000,
  unresolved_paise: 475000,
  auto_verified_count: 1,
  manually_reviewed_count: 1,
  blocking_exceptions: 2,
  unreviewable_blockers: 1,
  exception_count: 2,
  settlement_exception_count: 1,
  review_item_count: 2,
  total_close_blockers: 2,
  system_error_blockers: 0,
  integrity_blockers: 0,
  source_snapshot_id: 'snapshot_1',
  rule_version: '2.0',
  configuration_version: '2.0',
}

it('uses review-item counts instead of an overlapping unresolved-money total', () => {
  render(<ExceptionsPage items={exceptions} reviewing={null} onProof={vi.fn()} onAskAbout={vi.fn()} onReview={vi.fn()} />)

  expect(screen.getByText('Open review items')).toBeVisible()
  expect(screen.getByText('All review items')).toBeVisible()
  expect(screen.queryByText('Unresolved money')).not.toBeInTheDocument()
})

it('names residual money and blockers by their actual close semantics', () => {
  render(<ClosePage state={baseClose} approving={false} onApprove={vi.fn()} />)

  expect(screen.getByText('Auto-verified amount')).toBeVisible()
  expect(screen.getByText('Not auto-verified amount')).toBeVisible()
  expect(screen.getByText('Total close blockers')).toBeVisible()
  expect(screen.queryByText(/^Unresolved$/)).not.toBeInTheDocument()
  expect(screen.queryByText('Blocking exceptions')).not.toBeInTheDocument()
})

it('allows the clean READY state that the backend approval policy accepts', () => {
  render(
    <ClosePage
      state={{ ...baseClose, state: 'READY', unresolved_paise: 0, blocking_exceptions: 0, unreviewable_blockers: 0, exception_count: 0, settlement_exception_count: 0, review_item_count: 0, total_close_blockers: 0 }}
      approving={false}
      onApprove={vi.fn()}
    />,
  )

  expect(screen.getByRole('button', { name: 'Approve clean close' })).toBeEnabled()
})
