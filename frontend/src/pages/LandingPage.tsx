import { useState, useSyncExternalStore } from 'react'
import { ArrowDown, ArrowRight, Check, Pause, Play, ShieldCheck } from 'lucide-react'
import { LandingBackdrop } from '../components/LandingBackdrop'
import workspaceCapture from '../../../docs/screenshots/reconciliation.png'
import copilotCapture from '../../../docs/screenshots/resolution-brief.png'

interface Props { onOpenWorkspace?: () => void }
const motionQuery = '(prefers-reduced-motion: reduce)'
const prefersReducedMotion = () => window.matchMedia?.(motionQuery).matches ?? false
const subscribeMotion = (listener: () => void) => {
  const query = window.matchMedia?.(motionQuery)
  query?.addEventListener('change', listener)
  return () => query?.removeEventListener('change', listener)
}
const workspaceLink = (onOpenWorkspace?: () => void) => ({
  href: '/workspace',
  onClick: onOpenWorkspace ? (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    onOpenWorkspace()
  } : undefined,
})

function ProvenanceField() {
  return <aside className="pc-artifact" aria-label="Illustrative evidence provenance">
    <header><span>Settlement audit trace</span><span className="pc-example-label">Illustrative</span></header>
    <div className="pc-source-list"><span>Merchant orders</span><span>Razorpay recon</span><span>Settlements</span><span>Bank credits</span></div>
    <div className="pc-trace-stage"><ArrowDown size={14} aria-hidden="true" /><span>Frozen snapshot</span><code>snap_7f3a</code></div>
    <div className="pc-trace-stage"><ArrowDown size={14} aria-hidden="true" /><span>Rule</span><code>settlement_match@2.0</code></div>
    <div className="pc-proof-object">
      <h2>Versioned proof object</h2>
      <dl>
        <div><dt>Subject</dt><dd><code>setl_PC004</code></dd></div>
        <div><dt>Expected</dt><dd>₹12,504.18</dd></div>
        <div><dt>Bank credit</dt><dd>₹12,504.18</dd></div>
        <div><dt>Difference</dt><dd>₹0.00</dd></div>
        <div><dt>Candidates</dt><dd>1 <span className="pc-muted">· unique</span></dd></div>
        <div><dt>Decision</dt><dd className="pc-verified"><Check size={13} aria-hidden="true" /> AUTO VERIFIED</dd></div>
      </dl>
      <footer><span>Fingerprint</span><code>sha256:d64a19…c445d</code></footer>
    </div>
    <p className="pc-caption">Illustrative example · workspace results come from your selected data.</p>
  </aside>
}

export function LandingPage({ onOpenWorkspace }: Props) {
  const reducedMotion = useSyncExternalStore(subscribeMotion, prefersReducedMotion, () => true)
  const [motionOverride, setMotionOverride] = useState<boolean | null>(null)
  const motionPaused = motionOverride ?? reducedMotion
  const openWorkspace = workspaceLink(onOpenWorkspace)
  return <div className="landing-shell pc-public" data-motion-paused={motionPaused}>
    <LandingBackdrop paused={motionPaused} />
    <header className="pc-nav pc-width">
      <a className="pc-brand" href="#top" aria-label="ProofClose landing page"><ShieldCheck size={23} aria-hidden="true" />ProofClose</a>
      <nav aria-label="Landing page"><a href="#provenance">Provenance</a><a href="#controls">Controls</a><a href="#evaluation">Evaluation</a></nav>
      <div className="pc-nav-actions">
        <button className="pc-motion" type="button" aria-label={motionPaused ? 'Resume background animation' : 'Pause background animation'} aria-pressed={motionPaused} title={motionPaused ? 'Resume background animation' : 'Pause background animation'} onClick={() => setMotionOverride(!motionPaused)}>
          {motionPaused ? <Play size={13} aria-hidden="true" /> : <Pause size={13} aria-hidden="true" />}<span>Motion {motionPaused ? 'off' : 'on'}</span>
        </button>
        <a className="pc-nav-link" {...openWorkspace}>Open workspace <ArrowRight size={14} aria-hidden="true" /></a>
      </div>
    </header>
    <main id="top">
      <section className="pc-hero pc-width" aria-label="Evidence-first settlement close">
        <div className="pc-hero-copy">
          <p className="pc-eyebrow">Settlement reconciliation / Proof of concept</p>
          <h1>Close every settlement with proof.</h1>
          <p className="pc-lede">ProofClose traces merchant orders, Razorpay reconciliation records, settlements, and bank credits into versioned proof objects—then routes every exception into auditable human review.</p>
          <div className="pc-actions"><a className="pc-primary" {...openWorkspace}>Open evidence workspace <ArrowRight size={16} aria-hidden="true" /></a><a className="pc-secondary" href="#provenance">Trace the evidence <ArrowDown size={15} aria-hidden="true" /></a></div>
          <div className="pc-assurances" aria-label="Core assurances"><span><Check size={13} aria-hidden="true" /> deterministic decisions</span><span><Check size={13} aria-hidden="true" /> human-controlled close</span><span><Check size={13} aria-hidden="true" /> tamper-evident proof</span></div>
          <a className="pc-text-link" href="/workspace/sources">Bring your own CSV data <ArrowRight size={14} aria-hidden="true" /></a>
        </div>
        <ProvenanceField />
      </section>
      <section className="pc-product pc-width" aria-labelledby="product-title" id="provenance">
        <div className="pc-section-heading"><div><p className="pc-eyebrow">01 / The working product</p><h2 id="product-title">From settlement to proof.</h2></div><p>It shows what arrived, what matched, which rule ran, and exactly what must be reviewed.</p></div>
        <figure className="pc-product-frame"><img src={workspaceCapture} width="1280" height="800" alt="ProofClose reconciliation workspace with expected amounts, bank credits and evidence-linked decisions" loading="lazy" /><figcaption>Actual POC capture · synthetic demonstration data · deterministic offline assistance. Open the workspace to inspect current results.</figcaption></figure>
        <div className="pc-flow"><h3>One financial fact. Every source bound.</h3><p aria-label="Evidence workflow">Merchant orders <ArrowRight aria-hidden="true" /> Razorpay recon <ArrowRight aria-hidden="true" /> Settlement <ArrowRight aria-hidden="true" /> Bank <ArrowRight aria-hidden="true" /> Proof Object <ArrowRight aria-hidden="true" /> Human review / Close Pack</p></div>
      </section>
      <section className="pc-controls pc-width" id="controls" aria-label="Evidence controls">
        <div className="pc-section-heading"><div><p className="pc-eyebrow">02 / The control model</p><h2>Evidence moves. Proof stays.</h2></div><p>Trace a decision to its original evidence. Then turn failed checks into a resolution brief: what is unknown, what to request, and what to recheck.</p></div>
        <article className="pc-editorial-row"><div><span>01</span><h3>Exact money</h3></div><p>Authoritative amounts are integer paise. Floats never decide a match. An exact UTR and amount still requires one unique bank candidate.</p><dl className="pc-mini-ledger"><div><dt>Stored amount</dt><dd>1250418 paise</dd></div><div><dt>Displayed amount</dt><dd>₹12,504.18</dd></div></dl></article>
        <article className="pc-editorial-row"><div><span>02</span><h3>Refusal over guessing</h3></div><p>The product does not hide reconciliation behind a confidence score. Two candidates are not one supported answer.</p><dl className="pc-mini-ledger"><div><dt>Illustrative candidates</dt><dd>2</dd></div><div><dt>Decision</dt><dd className="pc-refused">REFUSED</dd></div></dl></article>
        <article className="pc-editorial-row"><div><span>03</span><h3>Reproducible proof</h3></div><p>Historical reproduction reruns the original versioned rule. Current-rule re-evaluation creates a separate comparison proof. If the original implementation is unavailable, reproduction fails explicitly.</p><dl className="pc-mini-ledger"><div><dt>Bound inputs</dt><dd>Snapshot · source hashes</dd></div><div><dt>Authority</dt><dd>Rule · configuration</dd></div><div><dt>Integrity</dt><dd>Artifact fingerprint</dd></div></dl></article>
        <article className="pc-copilot-row"><div><p className="pc-eyebrow">04 / Evidence Copilot</p><h3>Useful context without moving money.</h3><p>The <strong>Read-only Evidence Assistant</strong> can explain current facts, cite supporting records, and suggest a server-owned playbook. Canonical data remains visually separate from optional narration, and unsupported additions trigger deterministic fallback.</p><p>Models never calculate, match, approve, or change financial state. Review and final approval remain explicit audited actions.</p></div><figure className="pc-product-frame"><a href={copilotCapture} target="_blank" rel="noreferrer" aria-label="View full Evidence Copilot product capture"><img src={copilotCapture} width="1280" height="800" alt="Actual Evidence Copilot response and resolution brief in the ProofClose workspace" loading="lazy" /></a><figcaption>Actual POC capture · synthetic data · offline evidence response. Select the image to inspect it at full size.</figcaption></figure></article>
      </section>
      <section className="pc-evaluation pc-width" id="evaluation">
        <div className="pc-section-heading"><div><p className="pc-eyebrow">03 / Public, reproducible checks</p><h2>Measured on synthetic evidence—not marketed as production accuracy.</h2></div><p>Measured on 3 × 267-row synthetic runs: 801 source rows. The checked-in evaluation suite includes ambiguous and adversarial cases.</p></div>
        <div className="pc-table-scroll"><table aria-label="Synthetic regression results"><thead><tr><th scope="col">Measure</th><th scope="col">Evidence</th><th scope="col">Result</th></tr></thead><tbody>
          <tr><th scope="row">Automatic-match precision</th><td>21 / 21</td><td>100%</td></tr>
          <tr><th scope="row">Exception recall</th><td>15 / 15</td><td>100%</td></tr>
          <tr><th scope="row">Ambiguous cases safely refused</th><td>3 / 3</td><td>100%</td></tr>
          <tr><th scope="row">Valid required proofs</th><td>39 / 39</td><td>100%</td></tr>
          <tr><th scope="row">False refusals</th><td>Three-seed suite</td><td>0</td></tr>
          <tr><th scope="row">Money automatically proven</th><td>Integer-paise coverage</td><td>57.1%</td></tr>
        </tbody></table></div>
        <p className="pc-disclaimer">Synthetic regression evidence, not production accuracy or throughput.</p>
      </section>
      <section className="pc-limitations pc-width" aria-label="POC boundaries">
        <div><p className="pc-eyebrow">04 / Honest POC boundary</p><h2>Built to prove the control model.</h2><p>The bundled example is synthetic; your own data follows an explicit INR input contract. This POC uses SQLite and clearly labelled demo identity context.</p></div>
        <div><h3>Implemented</h3><ul><li>Deterministic reconciliation</li><li>Immutable source snapshots</li><li>Versioned Proof Objects</li><li>Human review with reasons</li><li>Read-only Evidence Copilot</li><li>Tamper-evident Final Close Packs</li></ul></div>
        <div><h3>Not claimed</h3><ul><li>Live Razorpay or bank connectors</li><li>Production SSO / RBAC</li><li>Production-scale distributed infrastructure</li><li>Production merchant accuracy benchmarks</li></ul><p>Production adoption also needs encrypted managed storage, durable queues, key management, and operational monitoring.</p></div>
      </section>
      <section className="pc-final pc-width"><div><p className="pc-eyebrow">From source row to signed-off close</p><h2>See the evidence chain work.</h2></div><a className="pc-primary" {...openWorkspace}>Open evidence workspace <ArrowRight size={16} aria-hidden="true" /></a></section>
    </main>
    <footer className="pc-footer pc-width"><a className="pc-brand" href="#top"><ShieldCheck size={20} aria-hidden="true" />ProofClose</a><p>Evidence-first settlement reconciliation · Proof of concept</p><a className="pc-text-link" {...openWorkspace}>Workspace <ArrowRight size={13} aria-hidden="true" /></a></footer>
  </div>
}
