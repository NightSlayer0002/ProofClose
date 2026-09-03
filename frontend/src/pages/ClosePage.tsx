import { Download, LockKeyhole, ShieldCheck } from 'lucide-react'

import { formatINR, sentenceCase } from '../app/formatters'
import type { CloseState } from '../app/types'

export function ClosePage({ state, approving, onApprove }: { state: CloseState; approving: boolean; onApprove: () => void }) {
  const canApprove = state.state === 'REVIEWED_WITH_EXCEPTIONS'
  return (
    <main className="page close-page" aria-labelledby="close-title">
      <div className="page-heading"><div><p className="eyebrow">26 Aug 2026</p><h1 id="close-title">Daily close</h1><p>The close reflects current persisted evidence and reviewed exceptions.</p></div><span className={`close-state ${state.state === 'BLOCKED' ? 'blocked' : ''}`} data-state={state.state.toLowerCase()}>{state.state === 'BLOCKED' ? <LockKeyhole aria-hidden="true" size={16} /> : <ShieldCheck aria-hidden="true" size={16} />}{sentenceCase(state.state)}</span></div>
      <dl className="close-ledger"><div className="money-ledger-item"><dt>Reconciled</dt><dd>{formatINR(state.reconciled_paise)}</dd></div><div className="money-ledger-item unresolved-ledger-item"><dt>Unresolved</dt><dd>{formatINR(state.unresolved_paise)}</dd></div><div><dt>Auto verified</dt><dd>{state.auto_verified_count}</dd></div><div><dt>Manually reviewed</dt><dd>{state.manually_reviewed_count}</dd></div><div><dt>Blocking exceptions</dt><dd>{state.blocking_exceptions}</dd></div></dl>
      <section className="close-policy"><div className="close-policy-copy"><span className="section-kicker">Persisted control</span><h2>Close policy</h2><p>{state.blocking_exceptions ? `${state.blocking_exceptions} exception${state.blocking_exceptions === 1 ? '' : 's'} still require human review.` : state.exception_count ? 'Every exception has been reviewed. Explicit controller approval is required.' : 'No blocking exceptions remain.'}</p><code>snapshot {state.source_snapshot_id} · rule {state.rule_version}</code></div><div className="close-actions"><a className="secondary-action" href={`/api/close/export?run_id=${state.run_id}`}><Download aria-hidden="true" size={15} /> Export close pack</a><button className="primary-action" onClick={onApprove} disabled={!canApprove || approving}>{approving ? 'Approving…' : 'Approve close with exceptions'}</button></div></section>
    </main>
  )
}
