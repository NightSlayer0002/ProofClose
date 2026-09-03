import { Download, LockKeyhole, ShieldCheck } from 'lucide-react'

import { formatINR, sentenceCase } from '../app/formatters'
import type { CloseState } from '../app/types'

export function ClosePage({ state, approving, onApprove }: { state: CloseState; approving: boolean; onApprove: () => void }) {
  const canApprove = state.state === 'READY' || state.state === 'REVIEWED_WITH_EXCEPTIONS'
  const cleanClose = state.state === 'READY'
  const blockerText = state.total_close_blockers
    ? `${state.total_close_blockers} total close blocker${state.total_close_blockers === 1 ? '' : 's'} remain: ${state.review_item_count - state.manually_reviewed_count} open review item${state.review_item_count - state.manually_reviewed_count === 1 ? '' : 's'}, ${state.unreviewable_blockers} unreviewable result${state.unreviewable_blockers === 1 ? '' : 's'}, ${state.system_error_blockers} system error${state.system_error_blockers === 1 ? '' : 's'}, and ${state.integrity_blockers} integrity failure${state.integrity_blockers === 1 ? '' : 's'}.`
    : state.review_item_count
      ? 'Every review item has a recorded disposition. Explicit controller approval is required.'
      : 'No close blockers remain. Explicit controller approval is required.'
  return (
    <main className="page close-page" aria-labelledby="close-title">
      <div className="page-heading"><div><p className="eyebrow">26 Aug 2026</p><h1 id="close-title">Daily close</h1><p>The close reflects current persisted evidence and reviewed exceptions.</p></div><span className={`close-state ${state.state === 'BLOCKED' ? 'blocked' : ''}`} data-state={state.state.toLowerCase()}>{state.state === 'BLOCKED' ? <LockKeyhole aria-hidden="true" size={16} /> : <ShieldCheck aria-hidden="true" size={16} />}{sentenceCase(state.state)}</span></div>
      <dl className="close-ledger"><div className="money-ledger-item"><dt>Auto-verified amount</dt><dd>{formatINR(state.reconciled_paise)}</dd></div><div className="money-ledger-item unresolved-ledger-item"><dt>Not auto-verified amount</dt><dd>{formatINR(state.unresolved_paise)}</dd></div><div><dt>Auto-verified settlements</dt><dd>{state.auto_verified_count}</dd></div><div><dt>Reviewed items</dt><dd>{state.manually_reviewed_count}</dd></div><div><dt>Total close blockers</dt><dd>{state.total_close_blockers}</dd></div></dl>
      <section className="close-policy"><div className="close-policy-copy"><span className="section-kicker">Persisted control</span><h2>Close policy</h2><p>{blockerText}</p><code>snapshot {state.source_snapshot_id} · rule {state.rule_version} · config {state.configuration_version}</code></div><div className="close-actions"><a className="secondary-action" href={`/api/close/export?run_id=${state.run_id}`}><Download aria-hidden="true" size={15} /> Export close pack</a><button className="primary-action" onClick={onApprove} disabled={!canApprove || approving}>{approving ? 'Approving…' : cleanClose ? 'Approve clean close' : 'Approve close with reviewed exceptions'}</button></div></section>
    </main>
  )
}
