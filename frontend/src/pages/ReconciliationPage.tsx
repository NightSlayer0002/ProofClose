import { FileCheck2, MessageSquareText, Search, SlidersHorizontal } from 'lucide-react'
import { useMemo, useState } from 'react'

import { formatINR } from '../app/formatters'
import type { ReconciliationRow, RunSummary } from '../app/types'
import { StatusLabel } from '../components/StatusLabel'
import { SummaryStrip } from '../components/SummaryStrip'
import { Tooltip } from '../components/Tooltip'

export function ReconciliationPage({ run, rows, onProof, onAskAbout }: { run: RunSummary; rows: ReconciliationRow[]; onProof: (id: string) => void; onAskAbout: (row: ReconciliationRow) => void }) {
  const [query, setQuery] = useState('')
  const [decision, setDecision] = useState('ALL')
  const filtered = useMemo(() => rows.filter((row) => {
    const matches = `${row.settlement_id} ${row.utr ?? ''}`.toLowerCase().includes(query.toLowerCase())
    return matches && (decision === 'ALL' || row.decision === decision)
  }), [rows, query, decision])

  return (
    <main className="page" aria-labelledby="reconciliation-title">
      <div className="page-heading">
        <div><p className="eyebrow">Daily control / 26 Aug 2026</p><h1 id="reconciliation-title">Settlement reconciliation</h1><p>Trace every bank credit to immutable Razorpay and merchant evidence.</p></div>
        <div className="run-meta"><span>{run.records_processed} records</span><span>Run {run.total_ms}ms</span><code>{run.run_id}</code></div>
      </div>
      <SummaryStrip run={run} rows={rows} />
      <div className="table-toolbar">
        <label className="search-control"><Search aria-hidden="true" size={14} /><span className="sr-only">Search settlements</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search settlement or UTR" /></label>
        <label className="filter-control"><SlidersHorizontal aria-hidden="true" size={14} /><span className="sr-only">Filter decision</span><select value={decision} onChange={(event) => setDecision(event.target.value)}><option value="ALL">All decisions</option><option value="AUTO_VERIFIED">Verified</option><option value="REVIEW_REQUIRED">Review required</option><option value="REFUSED">Refused</option><option value="UNRESOLVED">Unresolved</option><option value="PENDING">Pending</option></select></label>
        <span className="result-count">{filtered.length} settlements</span>
      </div>
      <div className="data-table-wrap">
        <table className="data-table">
          <thead><tr><th>Settlement</th><th>UTR</th><th className="amount">Expected</th><th className="amount">Bank credit</th><th className="amount">Difference</th><th>Evidence</th><th>Decision</th><th><span className="sr-only">Action</span></th></tr></thead>
          <tbody>{filtered.map((row) => <tr key={row.settlement_id} data-state={row.decision.toLowerCase().replaceAll('_', '-')} onDoubleClick={() => onProof(row.proof_id)}><td><button className="id-link" onClick={() => onProof(row.proof_id)}>{row.settlement_id}</button></td><td><code>{row.utr ?? '—'}</code></td><td className="amount">{formatINR(row.expected_paise)}</td><td className="amount">{row.observed_paise == null ? '—' : formatINR(row.observed_paise)}</td><td className={`amount ${row.difference_paise ? 'negative' : ''}`}>{row.difference_paise == null ? '—' : formatINR(row.difference_paise)}</td><td><span className="evidence-count">{row.evidence.candidate_count} candidate{row.evidence.candidate_count === 1 ? '' : 's'}</span></td><td><StatusLabel value={row.decision} /></td><td><div className="table-row-tools"><Tooltip content="Open the immutable inputs, rule version, calculation, and lineage."><button className="table-action proof-action" onClick={() => onProof(row.proof_id)}><FileCheck2 aria-hidden="true" size={13} />Prove it</button></Tooltip><Tooltip content="Ask read-only questions scoped to this settlement and proof."><button className="table-action assistant-action" onClick={() => onAskAbout(row)}><MessageSquareText aria-hidden="true" size={13} />Ask assistant</button></Tooltip></div></td></tr>)}</tbody>
        </table>
      </div>
    </main>
  )
}
