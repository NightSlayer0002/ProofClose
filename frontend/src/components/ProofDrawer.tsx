import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { AlertTriangle, Check, Copy, Flag, History, RefreshCw, X } from 'lucide-react'

import { formatINR } from '../app/formatters'
import type { Evidence, Proof } from '../app/types'
import { StatusLabel } from './StatusLabel'
import { Tooltip } from './Tooltip'

interface Props {
  proof: Proof
  busyAction: 'reproduce' | 'reevaluate' | null
  onClose: () => void
  onAction: (action: 'reproduce' | 'reevaluate') => void
  onChallenge: () => void
  challengeConfirmation?: string | null
}

const isSettlementEvidence = (evidence: Proof['evidence']): evidence is Evidence => 'candidate_count' in evidence

export function ProofDrawer({ proof, busyAction, onClose, onAction, onChallenge, challengeConfirmation }: Props) {
  const layer = useRef<HTMLDivElement>(null)
  const drawer = useRef<HTMLElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const onCloseRef = useRef(onClose)
  const [rawOpen, setRawOpen] = useState(false)
  onCloseRef.current = onClose

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const modalLayer = layer.current
    const siblings = modalLayer?.parentElement
      ? Array.from(modalLayer.parentElement.children).filter((element): element is HTMLElement => element instanceof HTMLElement && element !== modalLayer)
      : []
    const priorInert = siblings.map((element) => element.inert)
    const previousOverflow = document.body.style.overflow
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
      }
    }
    siblings.forEach((element) => { element.inert = true })
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKey, true)
    closeButton.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey, true)
      siblings.forEach((element, index) => { element.inert = priorInert[index] ?? false })
      document.body.style.overflow = previousOverflow
      previous?.focus()
    }
  }, [])

  const trapFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Tab' || !drawer.current) return
    const focusable = Array.from(drawer.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )).filter((element) => !element.hidden)
    const first = focusable[0]
    const last = focusable.at(-1)
    if (!first || !last) return
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const settlementEvidence = isSettlementEvidence(proof.evidence)
  const settlementInput = proof.evidence_inputs.settlement
  const checks: ReadonlyArray<readonly [string, boolean]> = isSettlementEvidence(proof.evidence)
    ? [
        ['UTR exact', proof.evidence.utr_exact],
        ['Amount exact', proof.evidence.amount_exact],
        ['Settlement reconstruction', proof.evidence.settlement_ledger_consistent],
        ['Unique bank candidate', proof.evidence.candidate_count === 1],
      ]
    : [
        ['Payment rows present', proof.evidence.payment_row_count > 0],
        ['Expected order payment', proof.evidence.settled_payment_paise === proof.evidence.expected_order_payment_paise],
        ['No excess settled payment', proof.evidence.excess_payment_paise === 0],
      ]
  const evidenceCount = isSettlementEvidence(proof.evidence)
    ? proof.evidence.candidate_count
    : proof.evidence.payment_row_count

  return (
    <div ref={layer} className="drawer-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="proof-drawer" role="dialog" aria-modal="true" aria-label="Financial proof" tabIndex={-1} ref={drawer} onKeyDown={trapFocus}>
        <div className="drawer-header">
          <div>
            <StatusLabel value={proof.status} />
            <h2>Financial proof</h2>
            <code>{proof.proof_id}</code>
          </div>
          <Tooltip content="Close proof and return focus to the previous control." side="bottom"><button ref={closeButton} className="icon-button" aria-label="Close proof" onClick={onClose}><X aria-hidden="true" size={18} /></button></Tooltip>
        </div>

        <section className="proof-section evidence-pair">
          <div>
            <span className="section-kicker">{proof.subject.subject_type === 'ORDER' ? 'Order' : 'Settlement'}</span>
            <code>{proof.subject.subject_id}</code>
            <dl><dt>Expected credit</dt><dd>{formatINR(proof.result.expected_paise)}</dd></dl>
            <dl><dt>Settlement UTR</dt><dd><code>{settlementInput?.utr ?? 'Not applicable'}</code></dd></dl>
          </div>
          <div>
            <span className="section-kicker">Bank</span>
            <code>{proof.source_rows.find((row) => row.table === 'bank_statement')?.id ?? 'No supported row'}</code>
            <dl><dt>Observed credit</dt><dd>{proof.result.observed_paise == null ? '—' : formatINR(proof.result.observed_paise)}</dd></dl>
            <dl><dt>{settlementEvidence ? 'Candidate count' : 'Payment row count'}</dt><dd>{evidenceCount}</dd></dl>
          </div>
        </section>

        <section className="proof-section calculation-block">
          <div className="section-heading"><span>Calculation</span><code>{proof.classification.toUpperCase()}</code></div>
          <p>{proof.formula}</p>
          <dl><dt>Expected</dt><dd>{formatINR(proof.result.expected_paise)}</dd></dl>
          <dl><dt>Bank credit</dt><dd>{proof.result.observed_paise == null ? '—' : formatINR(proof.result.observed_paise)}</dd></dl>
          <dl className="total"><dt>Difference</dt><dd>{proof.result.delta_paise == null ? '—' : formatINR(proof.result.delta_paise)}</dd></dl>
        </section>

        <section className="proof-section">
          <div className="section-heading"><span>Verification</span><span>{proof.decision_score}/100 evidence score</span></div>
          <div className="verification-list">
            {checks.map(([label, passed]) => (
              <div key={label}><span>{label}</span><span className={passed ? 'pass' : 'fail'}>{passed ? <><Check size={13} /> Passed</> : <><AlertTriangle size={13} /> Not proven</>}</span></div>
            ))}
          </div>
          <ul className="reason-list">{proof.decision_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </section>

        <section className="proof-section version-grid">
          <div><span>Source snapshot</span><code>{proof.source_snapshot_id}</code></div>
          <div><span>Rule</span><code>{proof.rule_name}@{proof.rule_version}</code></div>
          <div><span>Configuration</span><code>{proof.configuration.version}</code></div>
          <div><span>Decision fingerprint</span><code title={proof.decision_fingerprint}>{proof.decision_fingerprint.slice(0, 24)}…</code></div>
          <div><span>Artifact fingerprint</span><code title={proof.artifact_fingerprint}>{proof.artifact_fingerprint.slice(0, 24)}…</code></div>
        </section>

        <section className="proof-section proof-operations">
          <div>
            <span className="proof-operation-kind">Historical reproduction</span>
            <h3>Historical integrity</h3>
            <p>Uses this proof’s original versioned rule. It fails explicitly if that code is unavailable.</p>
            <button onClick={() => onAction('reproduce')} disabled={busyAction !== null}>
              <History aria-hidden="true" size={15} /> {busyAction === 'reproduce' ? 'Reproducing…' : 'Reproduce historical proof'}
            </button>
          </div>
          <div>
            <span className="proof-operation-kind">Current-rule re-evaluation</span>
            <h3>Version comparison</h3>
            <p>Runs current rules on the same old snapshot and creates a new linked proof.</p>
            <button onClick={() => onAction('reevaluate')} disabled={busyAction !== null}>
              <RefreshCw aria-hidden="true" size={15} /> {busyAction === 'reevaluate' ? 'Evaluating…' : 'Evaluate with current rules'}
            </button>
          </div>
        </section>

        <div className="drawer-footer">
          <Tooltip content="View the source rows captured by this proof; nothing is modified."><button className="text-button" onClick={() => setRawOpen((value) => !value)}><Copy aria-hidden="true" size={14} /> {rawOpen ? 'Hide raw evidence' : 'View raw evidence'}</button></Tooltip>
          <button className="text-button danger" onClick={onChallenge}><Flag aria-hidden="true" size={14} /> Flag match</button>
        </div>
        {challengeConfirmation && <p className="proof-feedback-confirmation" role="status" aria-label="Proof challenge confirmation"><Check aria-hidden="true" size={14} />{challengeConfirmation}</p>}
        {rawOpen && <pre className="raw-evidence">{JSON.stringify(proof.source_rows, null, 2)}</pre>}
      </aside>
    </div>
  )
}
