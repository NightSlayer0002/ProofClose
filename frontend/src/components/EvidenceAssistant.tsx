import { ArrowRight, ArrowUpRight, ChevronRight, FileCheck2, MessageSquareText, Send, ShieldCheck, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'

import { formatINR } from '../app/formatters'
import type { AssistantContext, InvestigationReport } from '../app/types'
import { Tooltip } from './Tooltip'

interface Props {
  runId: string
  mode: 'Evidence mode' | 'AI-assisted evidence mode'
  messages: InvestigationReport[]
  loading: boolean
  selectedContext: AssistantContext
  focusRequest: number
  expanded?: boolean
  modal?: boolean
  onAsk: (question: string, context: AssistantContext) => void
  onProof: (proofId: string) => void
  onClose: () => void
  onExpand?: () => void
}

const runStarters = [
  "What prevents today's close?",
  "What amount is not auto-verified today?",
  'Show pending settlements',
  'Explain the exception breakdown',
]

const evidenceStarters = [
  'Why is this blocked?',
  'What evidence is missing?',
  'What should I do next?',
  'Show me the proof',
]

function contextPresentation(context: AssistantContext) {
  if (context.settlement_id) return {
    kind: 'Settlement',
    id: context.settlement_id,
    title: `Investigating settlement ${context.settlement_id}`,
    description: 'Questions in this thread are scoped to this settlement and its verified proof.',
    starters: evidenceStarters,
  }
  if (context.proof_id) return {
    kind: 'Proof',
    id: context.proof_id,
    title: `Investigating proof ${context.proof_id}`,
    description: 'Questions in this thread are scoped to this immutable proof.',
    starters: evidenceStarters,
  }
  return {
    kind: 'Current close',
    id: null,
    title: 'Investigating the current close',
    description: 'Ask about close blockers, not-auto-verified money, exceptions, or how ProofClose works.',
    starters: runStarters,
  }
}

function plural(value: number, singular: string): string {
  return `${value} ${singular}${value === 1 ? '' : 's'}`
}

export function EvidenceAssistant({
  runId,
  mode,
  messages,
  loading,
  selectedContext,
  focusRequest,
  expanded = false,
  modal = false,
  onAsk,
  onProof,
  onClose,
  onExpand,
}: Props) {
  const [question, setQuestion] = useState('')
  const panelRef = useRef<HTMLElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const contextRef = useRef<HTMLDivElement>(null)
  const logEndRef = useRef<HTMLDivElement>(null)
  const context = useMemo(() => contextPresentation(selectedContext), [selectedContext])

  useEffect(() => {
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !document.querySelector('.drawer-layer')) onClose()
    }
    document.addEventListener('keydown', dismissOnEscape)
    return () => document.removeEventListener('keydown', dismissOnEscape)
  }, [onClose])

  useEffect(() => {
    if (!modal) return
    closeButtonRef.current?.focus()
  }, [modal])

  useEffect(() => {
    if (focusRequest <= 0) return
    contextRef.current?.focus({ preventScroll: true })
    contextRef.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
  }, [focusRequest])

  useEffect(() => {
    if (messages.length === 0 && !loading) return
    logEndRef.current?.scrollIntoView?.({ block: 'end', behavior: 'smooth' })
  }, [loading, messages.length])

  const trapModalFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!modal || event.key !== 'Tab' || !panelRef.current) return
    const focusable = [...panelRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])')]
    if (!focusable.length) return
    const first = focusable[0]
    const last = focusable.at(-1)!
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || loading) return
    onAsk(trimmed, selectedContext)
    setQuestion('')
  }

  const submitOnEnter = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) return
    event.preventDefault()
    event.currentTarget.form?.requestSubmit()
  }

  return (
    <aside
      ref={panelRef}
      className={`evidence-assistant ${expanded ? 'expanded' : ''}`}
      aria-label="Evidence Assistant"
      role={modal ? 'dialog' : undefined}
      aria-modal={modal || undefined}
      data-assistance-mode={mode}
      onKeyDown={trapModalFocus}
    >
      <header className="assistant-header">
        <div className="assistant-title">
          <span className="assistant-icon"><MessageSquareText aria-hidden="true" size={16} /></span>
          <div><strong>Evidence Copilot</strong><span>Read-only copilot</span></div>
        </div>
        <div className="assistant-header-actions">
          {onExpand && !expanded && <Tooltip content="Open a larger conversation workspace." side="bottom"><button className="icon-button" aria-label="Open expanded Assistant" onClick={onExpand}><ArrowUpRight aria-hidden="true" size={15} /></button></Tooltip>}
          <Tooltip content={modal ? 'Close the Evidence Copilot.' : 'Collapse the Evidence Copilot.'} side="bottom"><button ref={closeButtonRef} className="icon-button" aria-label="Collapse Evidence Assistant" onClick={onClose}><X aria-hidden="true" size={15} /></button></Tooltip>
        </div>
      </header>

      <div className="assistant-trust"><ShieldCheck aria-hidden="true" size={14} /><span>Fresh evidence for current financial facts</span><small>No approvals or state changes</small></div>

      <div
        key={focusRequest}
        ref={contextRef}
        className={`assistant-context-divider ${focusRequest > 0 ? 'context-just-selected' : ''}`}
        role="status"
        aria-label="Assistant context"
        tabIndex={-1}
      >
        <div><span className="assistant-context-kicker">New context</span><strong>{context.title}</strong><p>{context.description}</p></div>
        <span className="assistant-context-chip">{context.kind}{context.id ? ` · ${context.id}` : ''}</span>
      </div>

      <div className="assistant-log" role="log" aria-label="Evidence Copilot conversation" aria-live="polite">
        {messages.length === 0 && <div className="assistant-empty"><strong>Start with a question</strong><p>The assistant will check fresh evidence whenever your question is about this close.</p><div className="assistant-starters">{context.starters.map((starter) => <button key={starter} onClick={() => onAsk(starter, selectedContext)}><span>{starter}</span><ArrowRight className="starter-arrow" aria-hidden="true" size={14} /></button>)}</div></div>}

        {messages.map((report, index) => {
          const proofIds = [...new Set(report.citations.proof_ids.filter(Boolean))]
          const sourceRows = [...new Set(report.citations.source_rows.filter(Boolean))]
          const hasSources = report.answer_mode !== 'GENERAL_HELP' && (proofIds.length > 0 || sourceRows.length > 0 || report.supporting_record_count > 0)
          const technical = {
            run_id: runId,
            status: report.status,
            route: report.route,
            tool_name: report.tool_name,
            narration_status: report.narration_status,
            calculation_count: report.calculation_count,
            unsupported_factual_claims: report.unsupported_factual_claims,
            provider: report.provider,
            estimated_cost: report.estimated_cost,
            canonical: report.canonical,
            ...report.technical_details,
          }
          return <article className="assistant-turn" key={`${report.question}-${index}`}>
            <div className="assistant-user-message"><span>You</span><p>{report.question}</p></div>
            <div className="assistant-response">
              <div className="assistant-response-header"><span className="assistant-author">PROOFCLOSE</span><span className={`assistant-answer-label mode-${report.answer_mode.toLowerCase()}`}>{report.answer_label}</span></div>
              <section className="assistant-primary-answer" aria-label={report.answer_mode === 'GENERAL_HELP' ? 'Assistant answer' : 'Verified facts'}>
                <p style={{ whiteSpace: 'pre-line' }}>{report.message}</p>
                {report.status === 'ANSWERED' && (report.explained_paise !== null || report.unresolved_paise !== null) && <dl>{report.explained_paise !== null && <div><dt>Auto-verified amount</dt><dd>{formatINR(report.explained_paise)}</dd></div>}{report.unresolved_paise !== null && <div><dt>Not auto-verified amount</dt><dd>{formatINR(report.unresolved_paise)}</dd></div>}</dl>}
              </section>
              {report.detail && <p className="assistant-detail" style={{ whiteSpace: 'pre-line' }}>{report.detail}</p>}
              {report.narration && <section className="assistant-additional"><span>Additional context</span><p style={{ whiteSpace: 'pre-line' }}>{report.narration}</p></section>}
              {report.recommended_actions.length > 0 && <section className="assistant-next-actions" aria-label="Recommended next steps"><h3>Recommended next steps</h3><ol>{report.recommended_actions.map((action) => <li key={action.code}><span>{action.label}</span><p>{action.detail}</p></li>)}</ol><small>Guidance only. The assistant did not change any financial state.</small></section>}

              {hasSources && <div className="assistant-support">
                <span>{plural(report.supporting_record_count, 'supporting record')} · {plural(proofIds.length, 'proof')}</span>
                <details className="assistant-disclosure"><summary>Sources <ChevronRight aria-hidden="true" size={13} /></summary><div className="assistant-source-list">{proofIds.map((proofId) => <button key={proofId} onClick={() => onProof(proofId)} aria-label={`Open proof ${proofId}`}><FileCheck2 aria-hidden="true" size={13} />Proof evidence</button>)}{sourceRows.map((sourceRow) => <span key={sourceRow}>Supporting record <code>{sourceRow}</code></span>)}<small>{report.citations.support_scope === 'DIRECT' ? 'Directly supports this answer' : `Aggregate context from ${report.run_record_count} run records`}</small></div></details>
              </div>}

              <details className="assistant-disclosure assistant-technical"><summary>Technical details <ChevronRight aria-hidden="true" size={13} /></summary><div className="assistant-technical-content"><dl><div><dt>Route</dt><dd><code>{report.route}</code></dd></div>{report.tool_name && <div><dt>Read-only tool</dt><dd><code>{report.tool_name}</code></dd></div>}</dl><pre>{JSON.stringify(technical, null, 2)}</pre></div></details>
            </div>
          </article>
        })}

        {loading && <div className="assistant-thinking" role="status" aria-label="Assistant is checking evidence"><span className="thinking-dot" /><span className="thinking-dot" /><span className="thinking-dot" /><span>Checking current evidence…</span></div>}
        <div ref={logEndRef} />
      </div>

      <form className="assistant-composer" onSubmit={submit}>
        <label className="sr-only" htmlFor="assistant-question">Ask Evidence Assistant</label>
        <textarea id="assistant-question" rows={1} value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={submitOnEnter} placeholder={`Ask about ${context.kind.toLowerCase()}…`} autoComplete="off" />
        <button className="assistant-send" disabled={loading || !question.trim()} aria-label="Send message"><Send aria-hidden="true" size={15} /></button>
      </form>
      <p className="assistant-boundary">Read-only guidance · fresh evidence for current facts · no autonomous actions</p>
    </aside>
  )
}
