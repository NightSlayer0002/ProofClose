import {
  ArrowRight,
  Banknote,
  Check,
  CircleDot,
  Database,
  FileCheck2,
  Fingerprint,
  GitCompareArrows,
  LockKeyhole,
  ScanLine,
  ShieldCheck,
  Waypoints,
} from 'lucide-react'

interface Props {
  onOpenWorkspace?: () => void
}

const workspaceLink = (onOpenWorkspace?: () => void) => ({
  href: '/workspace',
  onClick: onOpenWorkspace
    ? (event: React.MouseEvent<HTMLAnchorElement>) => {
        event.preventDefault()
        onOpenWorkspace()
      }
    : undefined,
})

function ProvenanceField() {
  return (
    <div className="provenance-field" aria-label="Source records flow through a frozen snapshot and versioned rules into an immutable proof">
      <div className="provenance-source-stack">
        <span className="provenance-caption">Source records</span>
        <div className="source-chip source-orders"><Database aria-hidden="true" size={15} /><span>Merchant orders</span><code>ord_0042</code></div>
        <div className="source-chip source-recon"><ScanLine aria-hidden="true" size={15} /><span>Razorpay recon</span><code>pay_0188</code></div>
        <div className="source-chip source-bank"><Banknote aria-hidden="true" size={15} /><span>Bank credits</span><code>UTR…208</code></div>
      </div>

      <div className="provenance-rail" aria-hidden="true"><span /><i /><span /><i /><span /></div>

      <div className="provenance-core">
        <div className="provenance-node snapshot-node">
          <span className="node-icon"><LockKeyhole aria-hidden="true" size={16} /></span>
          <div><small>Frozen snapshot</small><strong>snap_7f3a</strong></div>
          <span className="node-state"><Check aria-hidden="true" size={12} /> hashed</span>
        </div>
        <div className="rule-connector"><span>normalize</span><span>bind</span><span>evaluate</span></div>
      </div>

      <div className="proof-object-card">
        <header><span>Versioned proof object</span><span className="proof-object-status"><CircleDot aria-hidden="true" size={11} /> AUTO VERIFIED</span></header>
        <dl>
          <div><dt>Subject</dt><dd>setl_PC004</dd></div>
          <div><dt>Rule</dt><dd>settlement@2.0</dd></div>
          <div><dt>Expected</dt><dd>₹12,504.18</dd></div>
          <div><dt>Bank credit</dt><dd>₹12,504.18</dd></div>
          <div><dt>Evidence</dt><dd>1 unique candidate</dd></div>
        </dl>
        <footer><Fingerprint aria-hidden="true" size={12} /><code>sha256:d64a19…c445d</code></footer>
      </div>
    </div>
  )
}

export function LandingPage({ onOpenWorkspace }: Props) {
  const openWorkspace = workspaceLink(onOpenWorkspace)
  return (
    <div className="landing-shell">
      <div className="landing-ambient" aria-hidden="true"><span /><span /><span /></div>
      <header className="landing-nav">
        <a className="landing-brand" href="#top" aria-label="ProofClose landing page">
          <span className="brand-mark"><ShieldCheck aria-hidden="true" size={17} /></span>
          <span>ProofClose</span>
        </a>
        <nav aria-label="Landing page"><a href="#provenance">Provenance</a><a href="#controls">Controls</a><a href="#evaluation">Evaluation</a></nav>
        <a className="landing-nav-cta" {...openWorkspace}>Open workspace <ArrowRight aria-hidden="true" size={14} /></a>
      </header>

      <main id="top">
        <section className="landing-hero" aria-label="Evidence-first settlement close">
          <div className="landing-hero-copy">
            <p className="landing-kicker"><span /> Evidence-first finance operations</p>
            <h1>Close every settlement with proof.</h1>
            <p className="landing-lede">ProofClose traces merchant orders, Razorpay reconciliation records, settlements, and bank credits into versioned proof objects—then routes every exception into auditable human review.</p>
            <div className="landing-hero-actions">
              <a className="landing-primary" {...openWorkspace}>Open evidence workspace <ArrowRight aria-hidden="true" size={16} /></a>
              <a className="landing-secondary" href="#provenance">Trace the evidence <Waypoints aria-hidden="true" size={15} /></a>
            </div>
            <div className="landing-assurance" aria-label="Core assurances">
              <span><Check aria-hidden="true" size={13} /> deterministic decisions</span>
              <span><Check aria-hidden="true" size={13} /> human-controlled close</span>
              <span><Check aria-hidden="true" size={13} /> tamper-evident proof</span>
            </div>
          </div>
          <ProvenanceField />
        </section>

        <section className="landing-statement" id="provenance">
          <p>THE OPERATING PRINCIPLE</p>
          <h2>Evidence moves. Proof stays.</h2>
          <span>Every decision is reproducible from the source snapshot, rule version, configuration, and bound evidence that created it.</span>
        </section>

        <section className="landing-section provenance-section">
          <div className="landing-section-heading">
            <p className="landing-kicker"><span /> Provenance, made visible</p>
            <h2>One financial fact. Every source bound.</h2>
            <p>The product does not hide reconciliation behind a confidence score. It shows what arrived, what matched, which rule ran, and exactly what must be reviewed.</p>
          </div>
          <div className="provenance-steps">
            <article><span>01</span><Database aria-hidden="true" /><h3>Accept source deliveries</h3><p>CSV rows are validated, quarantined when invalid, hashed, and retained as submitted.</p></article>
            <article><span>02</span><LockKeyhole aria-hidden="true" /><h3>Freeze the evidence</h3><p>An immutable snapshot binds the accepted source IDs and content hashes before rules execute.</p></article>
            <article><span>03</span><GitCompareArrows aria-hidden="true" /><h3>Run versioned rules</h3><p>Integer-paise comparisons and explicit predicates decide; an exact UTR and amount still requires one unique bank candidate.</p></article>
            <article><span>04</span><FileCheck2 aria-hidden="true" /><h3>Seal a proof object</h3><p>The subject, sources, result, reasons, versions, and supersession lineage become tamper-evident evidence.</p></article>
          </div>
        </section>

        <section className="landing-section proof-anatomy" id="controls">
          <div className="anatomy-visual">
            <div className="anatomy-card">
              <header><FileCheck2 aria-hidden="true" size={18} /><strong>Proof anatomy</strong><span>immutable</span></header>
              <div className="anatomy-row"><span>Identity</span><code>tenant · run · subject</code><i /></div>
              <div className="anatomy-row"><span>Inputs</span><code>snapshot · source hashes</code><i /></div>
              <div className="anatomy-row"><span>Authority</span><code>rule · configuration</code><i /></div>
              <div className="anatomy-row"><span>Decision</span><code>formula · evidence · reasons</code><i /></div>
              <div className="anatomy-row"><span>History</span><code>supersedes · fingerprint</code><i /></div>
              <footer><Fingerprint aria-hidden="true" size={13} /> Any bound-field mutation breaks verification.</footer>
            </div>
          </div>
          <div className="anatomy-copy">
            <p className="landing-kicker"><span /> Authority stays explicit</p>
            <h2>A close you can defend later.</h2>
            <p>Historical reproduction reruns the original versioned rule. Current-rule re-evaluation creates a separate comparison proof. If the original implementation is unavailable, reproduction fails explicitly.</p>
            <ul>
              <li><Check aria-hidden="true" /> Deterministic code calculates and classifies money.</li>
              <li><Check aria-hidden="true" /> Humans disposition review items and approve the close.</li>
              <li><Check aria-hidden="true" /> Final Close Packs are immutable and verified on export.</li>
              <li><Check aria-hidden="true" /> Demo identity headers are labelled as non-authentication.</li>
            </ul>
          </div>
        </section>

        <section className="landing-section evaluation-section" id="evaluation">
          <div className="landing-section-heading compact">
            <p className="landing-kicker"><span /> Public, reproducible checks</p>
            <h2>Measured on synthetic evidence—not marketed as production accuracy.</h2>
            <p>The checked-in evaluation suite reports the complete fixture set and honest exception list, including ambiguous and adversarial cases.</p>
          </div>
          <div className="evaluation-grid">
            <article><strong>267</strong><span>source rows</span><small>deterministic demo fixture</small></article>
            <article><strong>801</strong><span>source rows</span><small>three-seed regression suite</small></article>
            <article><strong>100%</strong><span>auto-match precision</span><small>synthetic evaluation</small></article>
            <article><strong>100%</strong><span>ambiguous-case abstention</span><small>synthetic evaluation</small></article>
          </div>
          <p className="evaluation-footnote">These are test results for the repository’s synthetic datasets, not claims about real merchant traffic.</p>
        </section>

        <section className="landing-section trust-section">
          <div>
            <p className="landing-kicker"><span /> Bounded assistance</p>
            <h2>Useful context without moving money.</h2>
            <p>The <strong>Read-only Evidence Assistant</strong> can explain current facts, cite supporting records, and suggest a server-owned playbook. Canonical data remains visually separate from optional narration, and unsupported additions trigger deterministic fallback.</p>
          </div>
          <div className="boundary-grid">
            <article><ShieldCheck aria-hidden="true" /><h3>Code decides</h3><p>Models never calculate, match, approve, or change financial state.</p></article>
            <article><Fingerprint aria-hidden="true" /><h3>Evidence cites</h3><p>Direct support is distinguished from total run context.</p></article>
            <article><LockKeyhole aria-hidden="true" /><h3>People control</h3><p>Review and final approval remain explicit audited actions.</p></article>
          </div>
        </section>

        <section className="landing-section honest-section">
          <div><p className="landing-kicker"><span /> Honest POC boundary</p><h2>Built to prove the control model.</h2></div>
          <p>This build uses synthetic CSV sources, SQLite, and clearly labelled demo identity context. Production adoption would add authenticated tenant identity, RBAC, encrypted managed storage, live source connectors, durable queues, key management, and operational monitoring. The POC does not pretend those controls already exist.</p>
        </section>

        <section className="landing-cta">
          <span className="cta-mark"><ShieldCheck aria-hidden="true" /></span>
          <p>From source row to signed-off close</p>
          <h2>See the evidence chain work.</h2>
          <a className="landing-primary" {...openWorkspace}>Open evidence workspace <ArrowRight aria-hidden="true" size={16} /></a>
        </section>
      </main>

      <footer className="landing-footer"><a className="landing-brand" href="#top"><span className="brand-mark"><ShieldCheck aria-hidden="true" size={15} /></span><span>ProofClose</span></a><p>Evidence-first settlement reconciliation · Proof of concept</p><a {...openWorkspace}>Workspace <ArrowRight aria-hidden="true" size={13} /></a></footer>
    </div>
  )
}
