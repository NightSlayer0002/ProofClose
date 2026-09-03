import type { CSSProperties } from 'react'

import type { Diagnostics } from '../app/types'
import { sentenceCase } from '../app/formatters'

export function DiagnosticsPage({ data }: { data: Diagnostics }) {
  const maxDuration = Math.max(1, ...data.timeline.map((item) => item.duration_ms))
  return (
    <main className="page diagnostics-page" aria-labelledby="diagnostics-title">
      <div className="page-heading"><div><p className="eyebrow">Engineering operations</p><h1 id="diagnostics-title">Run diagnostics</h1><p>Measured timings and failure signals—not marketing metrics.</p></div><code>{data.run.run_id}</code></div>
      <dl className="diagnostic-strip"><div><dt>Records</dt><dd>{data.run.records_processed}</dd></div><div><dt>Total latency</dt><dd>{data.run.total_ms}ms</dd></div><div><dt>Slowest stage</dt><dd>{sentenceCase(data.slowest_stage.stage)}</dd></div><div><dt>LLM calls</dt><dd>{data.llm_calls}</dd></div><div><dt>Tokens in / out</dt><dd>{data.llm_input_tokens} / {data.llm_output_tokens}</dd></div><div><dt>Estimated cost</dt><dd>{data.estimated_llm_cost === 'unavailable' ? 'Unavailable' : `₹${data.estimated_llm_cost}`}</dd></div><div><dt>Proof failures</dt><dd>{data.proof_reproducibility_failures}</dd></div></dl>
      <p className="identity-panel"><strong>Assistant provider:</strong> {data.provider.configuration_status.replaceAll('_', ' ')}; reachability {data.provider.reachability_status.replaceAll('_', ' ')}. Cost stays unavailable unless a versioned pricing configuration exists.</p>
      <section className="timeline-section"><h2>Run timeline <span>Measured stage duration</span></h2><div className="data-table-wrap timeline-table-wrap"><table className="data-table"><thead><tr><th>Stage</th><th className="amount">Duration</th><th>Records observed</th></tr></thead><tbody>{data.timeline.map((item) => <tr key={item.stage}><td>{sentenceCase(item.stage)}</td><td className="amount duration-cell"><span>{item.duration_ms}ms</span><span className="duration-track" aria-hidden="true"><span className="duration-bar" style={{ '--duration-ratio': item.duration_ms / maxDuration } as CSSProperties} /></span></td><td>{String(item.metadata.records_processed ?? '—')}</td></tr>)}</tbody></table></div></section>
      <p className="identity-panel"><strong>Identity boundary:</strong> {data.identity_mode.replaceAll('_', ' ')}. These headers exist only for a single-tenant offline demo and are not production authentication.</p>
    </main>
  )
}
