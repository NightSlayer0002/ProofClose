import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ProofDrawer } from '../components/ProofDrawer'
import type { Proof } from '../app/types'

const proof: Proof = {
  schema_version: 'proof-object/v2',
  proof_id: 'proof_123',
  tenant_id: 'demo_merchant',
  run_id: 'run_123',
  source_snapshot_id: 'snapshot_123',
  status: 'AUTO_VERIFIED',
  source_rows: [{ table: 'bank_statement', id: 'raw_bank_1', raw_hash: 'sha256:abc' }],
  subject: { subject_type: 'SETTLEMENT', subject_id: 'setl_1' },
  rule_name: 'settlement_match',
  rule_version: '1.0',
  configuration: { version: '1.0', values: { pending_hours: 3 } },
  evidence_inputs: { settlement: { settlement_id: 'setl_1', utr: 'UTR1' } },
  evaluated_at: '2026-08-26T12:00:00Z',
  formula: 'sum(credit_paise) - sum(debit_paise)',
  result: { expected_paise: 475000, observed_paise: 475000, delta_paise: 0 },
  evidence: {
    utr_exact: true,
    amount_exact: true,
    settlement_ledger_consistent: true,
    temporal_consistency: true,
    candidate_count: 1,
    amount_delta_paise: 0,
  },
  decision_score: 100,
  decision_reasons: ['UTR exact', 'Unique bank candidate'],
  classification: 'calculated',
  exception_type: null,
  unresolved_reason: null,
  decision_fingerprint: 'sha256:decision',
  artifact_fingerprint: 'sha256:artifact',
  supersedes_proof_id: null,
  created_at: '2026-08-26T12:00:00Z',
}

afterEach(cleanup)

describe('ProofDrawer', () => {
  it('separates historical reproduction from current-rule reevaluation', () => {
    render(<ProofDrawer proof={proof} busyAction={null} onClose={vi.fn()} onAction={vi.fn()} />)
    expect(screen.getByRole('dialog', { name: 'Financial proof' })).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByText('Historical reproduction')).toBeVisible()
    expect(screen.getByText('Current-rule re-evaluation')).toBeVisible()
    expect(screen.getByRole('button', { name: /reproduce historical proof/i })).toBeVisible()
    expect(screen.getByRole('button', { name: /evaluate with current rules/i })).toBeVisible()
    expect(screen.getByText('Decision fingerprint')).toBeVisible()
    expect(screen.getByText('Artifact fingerprint')).toBeVisible()
  })

  it('closes with Escape', async () => {
    const close = vi.fn()
    render(<ProofDrawer proof={proof} busyAction={null} onClose={close} onAction={vi.fn()} />)
    await userEvent.keyboard('{Escape}')
    expect(close).toHaveBeenCalledTimes(1)
  })

  it('isolates background controls and traps focus until unmounted', async () => {
    const user = userEvent.setup()
    const { unmount } = render(
      <div className="app-shell">
        <header data-testid="app-header"><button>Underlying navigation</button></header>
        <ProofDrawer proof={proof} busyAction={null} onClose={vi.fn()} onAction={vi.fn()} />
      </div>,
    )

    const header = screen.getByTestId('app-header')
    const close = screen.getByRole('button', { name: 'Close proof' })
    expect(header.inert).toBe(true)
    expect(document.body.style.overflow).toBe('hidden')
    expect(close).toHaveFocus()

    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Flag match' })).toHaveFocus()
    await user.tab()
    expect(close).toHaveFocus()

    unmount()
    expect(header.inert).toBe(false)
    expect(document.body.style.overflow).toBe('')
  })
})
