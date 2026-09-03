import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import type { InvestigationReport } from '../app/types'
import { EvidenceAssistant } from '../components/EvidenceAssistant'
import { WorkspaceLayout } from '../components/WorkspaceLayout'

afterEach(cleanup)

const report: InvestigationReport = {
  status: 'ANSWERED',
  route: 'DIRECT_TOOL',
  tool_name: 'settlement_lookup',
  question: 'Why was this refused?',
  explained_paise: 475000,
  unresolved_paise: 0,
  canonical: { settlement_id: 'setl_1', decision: 'REFUSED', expected_paise: 475000 },
  narration: 'The supplied facts show that this settlement was refused.\nA person must review it.',
  narration_status: 'accepted',
  lines: [{ amount_paise: 475000, label: 'REFUSED', classification: 'UNRESOLVED', proof_id: 'proof_1' }],
  proof_ids: ['proof_1'],
  citations: { proof_ids: ['proof_1'], source_rows: ['bank:bank_1'], support_scope: 'DIRECT' },
  supporting_record_count: 2,
  run_record_count: 267,
  calculation_count: 1,
  unsupported_factual_claims: 0,
  provider: { configuration_status: 'configured', reachability_status: 'reachable', model: 'test-model' },
  estimated_cost: 'unavailable',
  message: 'This is the deterministic evidence result.\nThe status is current.',
  answer_mode: 'EVIDENCE_GUIDANCE',
  answer_label: 'Verified + guidance',
  detail: 'No settlement, review, proof, or close state was changed.',
  recommended_actions: [
    { code: 'CHECK_BANK_WINDOW', label: 'Check the bank statement window', detail: 'Confirm the credit did not post just outside the selected window.' },
    { code: 'REVIEW_EVIDENCE', label: 'Review the linked proof', detail: 'Compare the UTR and amount before making a human decision.' },
  ],
  technical_details: { route: 'DIRECT_TOOL', unsupported_tokens: ['internal-only-token'] },
}

it('renders a restrained transcript with verified facts and ordered guidance', async () => {
  const onProof = vi.fn()
  render(
    <EvidenceAssistant
      runId="run_1"
      mode="AI-assisted evidence mode"
      messages={[report]}
      loading={false}
      selectedContext={{ settlement_id: 'setl_1', proof_id: 'proof_1' }}
      focusRequest={0}
      onAsk={vi.fn()}
      onProof={onProof}
      onClose={vi.fn()}
    />,
  )

  const assistant = screen.getByRole('complementary', { name: 'Evidence Assistant' })
  expect(assistant).toHaveTextContent('Investigating settlement setl_1')
  expect(screen.getByText('Verified + guidance')).toBeVisible()
  expect(screen.getByRole('region', { name: 'Verified facts' })).toHaveTextContent('This is the deterministic evidence result.')
  expect(assistant).toHaveTextContent('Auto-verified amount')
  expect(assistant).toHaveTextContent('Not auto-verified amount')
  expect(assistant).not.toHaveTextContent(/^Unresolved$/)
  const guidanceItems = within(screen.getByRole('region', { name: 'Recommended next steps' })).getAllByRole('listitem')
  expect(guidanceItems[0]).toHaveTextContent('Check the bank statement window')
  expect(guidanceItems[1]).toHaveTextContent('Review the linked proof')
  expect(assistant).toHaveTextContent('2 supporting records · 1 proof')
  const additionalContext = screen.getByText('Additional context').closest('section')!
  expect(additionalContext).toHaveTextContent('A person must review it.')
  expect(additionalContext.querySelector('p')).toHaveStyle({ whiteSpace: 'pre-line' })

  const sources = screen.getByText('Sources').closest('details')!
  expect(sources).not.toHaveAttribute('open')
  await userEvent.click(within(sources).getByText('Sources'))
  await userEvent.click(screen.getByRole('button', { name: 'Open proof proof_1' }))
  expect(onProof).toHaveBeenCalledWith('proof_1')
})

it('hides route enums, raw canonical data, provider telemetry, and validation tokens by default', async () => {
  render(
    <EvidenceAssistant
      runId="run_1"
      mode="AI-assisted evidence mode"
      messages={[report]}
      loading={false}
      selectedContext={{ settlement_id: 'setl_1' }}
      focusRequest={0}
      onAsk={vi.fn()}
      onProof={vi.fn()}
      onClose={vi.fn()}
    />,
  )

  const disclosure = screen.getByText('Technical details').closest('details')!
  expect(disclosure).not.toHaveAttribute('open')
  expect(screen.getByText('DIRECT_TOOL')).not.toBeVisible()
  expect(screen.getByText(/internal-only-token/)).not.toBeVisible()
  expect(screen.getByText(/"settlement_id": "setl_1"/)).not.toBeVisible()

  await userEvent.click(within(disclosure).getByText('Technical details'))
  expect(screen.getByText('DIRECT_TOOL')).toBeVisible()
  expect(screen.getByText(/internal-only-token/)).toBeVisible()
})

it('shows exactly the server-approved public label and no fake sources for general help', () => {
  render(
    <EvidenceAssistant
      runId="run_1"
      mode="Evidence mode"
      messages={[{
        ...report,
        answer_mode: 'GENERAL_HELP',
        answer_label: 'General guidance',
        explained_paise: null,
        unresolved_paise: null,
        canonical: {},
        citations: { proof_ids: [], source_rows: [], support_scope: 'DIRECT' },
        supporting_record_count: 0,
        proof_ids: [],
        recommended_actions: [],
        technical_details: { route: 'GENERAL_HELP' },
      }]}
      loading={false}
      selectedContext={{}}
      focusRequest={0}
      onAsk={vi.fn()}
      onProof={vi.fn()}
      onClose={vi.fn()}
    />,
  )

  expect(screen.getByText('General guidance')).toBeVisible()
  expect(screen.queryByText('Verified from evidence')).not.toBeInTheDocument()
  expect(screen.queryByText('Verified + guidance')).not.toBeInTheDocument()
  expect(screen.queryByText('Unable to verify')).not.toBeInTheDocument()
  expect(screen.queryByText('Sources')).not.toBeInTheDocument()
  expect(screen.queryByText(/supporting records/)).not.toBeInTheDocument()
})

it('shows four settlement-specific starters and submits with the selected context', async () => {
  const onAsk = vi.fn()
  render(
    <EvidenceAssistant
      runId="run_1"
      mode="Evidence mode"
      messages={[]}
      loading={false}
      selectedContext={{ settlement_id: 'setl_1', proof_id: 'proof_1' }}
      focusRequest={0}
      onAsk={onAsk}
      onProof={vi.fn()}
      onClose={vi.fn()}
    />,
  )

  expect(screen.getByRole('button', { name: 'Why is this blocked?' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'What evidence is missing?' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'What should I do next?' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Show me the proof' })).toBeVisible()
  await userEvent.type(screen.getByLabelText('Ask Evidence Assistant'), 'What should I do next?')
  await userEvent.click(screen.getByRole('button', { name: 'Send message' }))
  expect(onAsk).toHaveBeenCalledWith('What should I do next?', { settlement_id: 'setl_1', proof_id: 'proof_1' })
})

it('focuses the selected context only when explicitly requested', () => {
  const { rerender } = render(
    <EvidenceAssistant
      runId="run_1"
      mode="Evidence mode"
      messages={[]}
      loading={false}
      selectedContext={{ settlement_id: 'setl_1' }}
      focusRequest={0}
      onAsk={vi.fn()}
      onProof={vi.fn()}
      onClose={vi.fn()}
    />,
  )
  const divider = screen.getByRole('status', { name: 'Assistant context' })
  expect(divider).not.toHaveFocus()

  rerender(
    <EvidenceAssistant
      runId="run_1"
      mode="Evidence mode"
      messages={[]}
      loading={false}
      selectedContext={{ settlement_id: 'setl_1' }}
      focusRequest={1}
      onAsk={vi.fn()}
      onProof={vi.fn()}
      onClose={vi.fn()}
    />,
  )
  expect(screen.getByRole('status', { name: 'Assistant context' })).toHaveFocus()
})

it('shows bounded read-only progress without simulating typed model output', () => {
  render(
    <EvidenceAssistant
      runId="run_1"
      mode="Evidence mode"
      messages={[]}
      loading
      selectedContext={{}}
      focusRequest={0}
      onAsk={vi.fn()}
      onProof={vi.fn()}
      onClose={vi.fn()}
    />,
  )

  expect(screen.getByRole('status', { name: 'Assistant is checking evidence' })).toHaveTextContent('Checking current evidence')
})

function CollapsibleHarness() {
  const [open, setOpen] = useState(true)
  return (
    <WorkspaceLayout
      assistantOpen={open}
      onOpenAssistant={() => setOpen(true)}
      onCloseAssistant={() => setOpen(false)}
      assistant={() => (
        <EvidenceAssistant
          runId="run_1"
          mode="Evidence mode"
          messages={[report]}
          loading={false}
          selectedContext={{}}
          focusRequest={0}
          onAsk={vi.fn()}
          onProof={vi.fn()}
          onClose={() => setOpen(false)}
        />
      )}
    >
      <main>Finance workspace</main>
    </WorkspaceLayout>
  )
}

it('collapses and reopens without losing the conversation owned by the parent', async () => {
  render(<CollapsibleHarness />)
  expect(screen.getByText('Why was this refused?')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Collapse Evidence Assistant' }))
  expect(screen.queryByText('Why was this refused?')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Open Evidence Assistant' }))
  expect(screen.getByText('Why was this refused?')).toBeVisible()
})
