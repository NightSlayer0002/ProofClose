import { formatAge, formatINR, sentenceCase } from '../app/formatters'
import type { ExceptionItem } from '../app/types'
import { StatusLabel } from '../components/StatusLabel'
import { Tooltip } from '../components/Tooltip'

interface Props {
  items: ExceptionItem[]
  reviewing: string | null
  onProof: (id: string) => void
  onAskAbout: (item: ExceptionItem) => void
  onReview: (item: ExceptionItem, action: string) => void
}

export function ExceptionsPage({ items, reviewing, onProof, onAskAbout, onReview }: Props) {
  const openItems = items.filter((item) => item.state === 'OPEN')
  const unresolvedMoney = openItems.reduce((total, item) => total + item.amount_paise, 0)
  return (
    <main className="page" aria-labelledby="exceptions-title">
      <div className="page-heading"><div><p className="eyebrow">Human control</p><h1 id="exceptions-title">Exception queue</h1><p>Ambiguous or contradictory money waits here until a person makes an audited decision.</p></div><dl className="queue-summary"><div><dt>Open</dt><dd>{openItems.length}</dd></div><div><dt>Unresolved money</dt><dd>{formatINR(unresolvedMoney)}</dd></div></dl></div>
      <div className="data-table-wrap">
        <table className="data-table exception-table">
          <thead><tr><th className="amount">Amount</th><th>Exception</th><th>Age</th><th>State</th><th>Evidence</th><th>Action</th></tr></thead>
          <tbody>{items.map((item) => <tr key={item.exception_id} data-state={item.state.toLowerCase().replaceAll('_', '-')}><td className="amount strong">{formatINR(item.amount_paise)}</td><td><strong>{sentenceCase(item.exception_type)}</strong><code>{item.exception_id}</code></td><td>{formatAge(item.created_at)}</td><td><StatusLabel value={item.state} /></td><td><div className="table-row-tools"><Tooltip content="Inspect the immutable proof before deciding."><button className="table-action" onClick={() => onProof(item.proof_id)}>Inspect proof</button></Tooltip><Tooltip content="Ask a read-only question scoped to this proof."><button className="table-action" onClick={() => onAskAbout(item)}>Ask assistant</button></Tooltip></div></td><td><div className="row-actions review-action-group"><Tooltip content="Audited human decision; the original proof remains unchanged."><button className="review-approve" disabled={reviewing === item.exception_id || item.state !== 'OPEN'} onClick={() => onReview(item, 'APPROVE')}>Approve</button></Tooltip><Tooltip content="Audited rejection; the original proof remains unchanged."><button className="review-reject" disabled={reviewing === item.exception_id || item.state !== 'OPEN'} onClick={() => onReview(item, 'REJECT')}>Reject</button></Tooltip><Tooltip content="Keep the amount unresolved and document it for follow-up."><button className="review-unresolved" disabled={reviewing === item.exception_id || item.state !== 'OPEN'} onClick={() => onReview(item, 'LEAVE_UNRESOLVED')}>Leave unresolved</button></Tooltip></div></td></tr>)}</tbody>
        </table>
      </div>
    </main>
  )
}
