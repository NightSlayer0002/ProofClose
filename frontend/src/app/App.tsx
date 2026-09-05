import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from './api'
import { isWorkspacePath, pageForPath, pathForPage } from './routing'
import type { AssistantContext, AssistantContextType, AssistantThread, CloseState, ConversationTurn, Diagnostics, ExceptionItem, FeedbackType, Page, Proof, ReconciliationRow, ReviewAction, RunSummary } from './types'
import { ActionDialog } from '../components/ActionDialog'
import { AppHeader } from '../components/AppHeader'
import { EvidenceAssistant } from '../components/EvidenceAssistant'
import { ProofDrawer } from '../components/ProofDrawer'
import { WorkspaceLayout } from '../components/WorkspaceLayout'
import { ClosePage } from '../pages/ClosePage'
import { DiagnosticsPage } from '../pages/DiagnosticsPage'
import { ExceptionsPage } from '../pages/ExceptionsPage'
import { InvestigatePage } from '../pages/InvestigatePage'
import { LandingPage } from '../pages/LandingPage'
import { ReconciliationPage } from '../pages/ReconciliationPage'
import { SourcesPage } from '../pages/SourcesPage'

type OperatorAction =
  | { kind: 'review'; item: ExceptionItem; action: ReviewAction }
  | { kind: 'close' }
  | { kind: 'challenge'; proof: Proof }

const REVIEW_DIALOG_COPY: Record<ReviewAction, { title: string; confirm: string }> = {
  APPROVE: { title: 'Accept exception finding', confirm: 'Record acceptance' },
  REJECT: { title: 'Reject exception finding', confirm: 'Record rejection' },
  LEAVE_UNRESOLVED: { title: 'Record unresolved exception', confirm: 'Record unresolved' },
}

const FEEDBACK_OPTIONS: ReadonlyArray<{ value: FeedbackType; label: string }> = [
  { value: 'INCORRECT_MATCH', label: 'Incorrect match' },
  { value: 'INCORRECT_EXCEPTION', label: 'Incorrect exception' },
  { value: 'PROOF_UNCLEAR', label: 'Proof unclear' },
  { value: 'OTHER', label: 'Other' },
]

function contextType(context: AssistantContext): AssistantContextType {
  if (context.settlement_id) return 'settlement'
  if (context.proof_id) return 'proof'
  return 'run'
}

function assistantContextKey(runId: string, context: AssistantContext): string {
  const type = contextType(context)
  const id = type === 'settlement' ? context.settlement_id : type === 'proof' ? context.proof_id : 'current'
  return `${runId}:${type}:${id ?? 'current'}`
}

function conversationHistory(thread?: AssistantThread): ConversationTurn[] {
  if (!thread) return []
  return thread.messages
    .flatMap((report): ConversationTurn[] => [
      { role: 'user', content: report.question.slice(0, 500) },
      { role: 'assistant', content: report.message.slice(0, 500) },
    ])
    .slice(-6)
}

interface WorkspaceAppProps {
  pathname: string
  onHome: () => void
  onPathChange: (path: string) => void
}

function WorkspaceApp({ pathname, onHome, onPathChange }: WorkspaceAppProps) {
  const page = pageForPath(pathname)
  const initialSourcesPage = useRef(page === 'sources')
  const [run, setRun] = useState<RunSummary | null>(null)
  const [rows, setRows] = useState<ReconciliationRow[]>([])
  const [exceptions, setExceptions] = useState<ExceptionItem[]>([])
  const [closeState, setCloseState] = useState<CloseState | null>(null)
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null)
  const [assistantThreads, setAssistantThreads] = useState<Record<string, AssistantThread>>({})
  const [assistantMode, setAssistantMode] = useState<'Evidence mode' | 'AI-assisted evidence mode'>('Evidence mode')
  const [assistantOpen, setAssistantOpen] = useState(() => !(window.matchMedia?.('(max-width: 1080px)').matches ?? false))
  const [selectedContext, setSelectedContext] = useState<AssistantContext>({})
  const [assistantFocusRequest, setAssistantFocusRequest] = useState(0)
  const [proof, setProof] = useState<Proof | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [reviewing, setReviewing] = useState<string | null>(null)
  const [proofAction, setProofAction] = useState<'reproduce' | 'reevaluate' | null>(null)
  const [operatorAction, setOperatorAction] = useState<OperatorAction | null>(null)
  const [challengeConfirmation, setChallengeConfirmation] = useState<string | null>(null)
  const [investigating, setInvestigating] = useState(false)
  const [approving, setApproving] = useState(false)
  const [message, setMessage] = useState('Loading immutable demo evidence…')
  const [error, setError] = useState<string | null>(null)
  const activeRunIdRef = useRef<string | null>(null)
  const investigationSequenceRef = useRef(0)

  const refreshRunData = useCallback(async (summary: RunSummary) => {
    const [rowData, exceptionData, closeData, diagnosticData] = await Promise.all([
      api.rows(summary.run_id), api.exceptions(summary.run_id), api.close(summary.run_id), api.diagnostics(summary.run_id),
    ])
    activeRunIdRef.current = summary.run_id
    setRun(summary)
    setRows(rowData.items)
    setExceptions(exceptionData.items)
    setCloseState(closeData)
    setDiagnostics(diagnosticData)
  }, [])

  const initialize = useCallback(async () => {
    try {
      setLoading(true)
      setMessage('Loading immutable finance evidence…')
      const [health, sources] = await Promise.all([api.health(), api.sources()])
      setAssistantMode(health.ai_assistance === 'ai_assisted_evidence_mode' ? 'AI-assisted evidence mode' : 'Evidence mode')
      if (initialSourcesPage.current) { setMessage(''); return }
      let summary: RunSummary
      if (!sources.items.some((source) => source.state === 'ACCEPTED')) {
        const demo = await api.seedDemo()
        setMessage(`Creating source snapshot from ${demo.record_count} records…`)
        summary = await api.run(demo.snapshot_id)
      } else {
        try {
          summary = await api.latestRun()
        } catch {
          onPathChange(pathForPage('sources'))
          setMessage('Choose your accepted source files before creating a run.')
          return
        }
      }
      await refreshRunData(summary)
      setMessage('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'ProofClose could not initialize')
    } finally {
      setLoading(false)
    }
  }, [refreshRunData, onPathChange])

  useEffect(() => { void initialize() }, [initialize])

  const navigate = (nextPage: Page) => {
    onPathChange(pathForPage(nextPage))
  }

  const rerun = async () => {
    try {
      setRunning(true)
      investigationSequenceRef.current += 1
      setInvestigating(false)
      const summary = await api.run(run?.source_snapshot_id)
      await refreshRunData(summary)
      setAssistantThreads({})
      setSelectedContext({})
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Run failed') } finally { setRunning(false) }
  }

  const runSelectedSources = async (sourceIds: string[], evaluatedAt?: string) => {
    setRunning(true)
    investigationSequenceRef.current += 1
    setInvestigating(false)
    try {
      const snapshot = await api.snapshot(sourceIds)
      const summary = await api.run(snapshot.snapshot_id, evaluatedAt)
      await refreshRunData(summary)
      setAssistantThreads({}); setSelectedContext({}); setProof(null); setError(null)
      setMessage('New run created from your selected source files. Previous evidence is preserved.')
      navigate('reconciliation')
    } finally { setRunning(false) }
  }

  const openProof = async (proofId: string) => {
    try {
      setChallengeConfirmation(null)
      setProof(await api.proof(proofId))
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Proof unavailable') }
  }

  const actOnProof = async (action: 'reproduce' | 'reevaluate') => {
    if (!proof) return
    try {
      setProofAction(action)
      const result = await api.proofAction(proof.proof_id, action)
      setMessage(action === 'reproduce' ? `Historical proof: ${String(result.status)}` : 'Current-rule comparison proof created')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Proof operation failed') } finally { setProofAction(null) }
  }

  const review = async (item: ExceptionItem, action: ReviewAction, reason: string) => {
    if (!run) throw new Error('The active reconciliation run is unavailable.')
    try {
      setReviewing(item.exception_id)
      await api.review(item.exception_id, action, reason)
      const [exceptionData, closeData] = await Promise.all([api.exceptions(run.run_id), api.close(run.run_id)])
      setExceptions(exceptionData.items)
      setCloseState(closeData)
      setMessage(`Review recorded for ${item.exception_id}.`)
    } finally { setReviewing(null) }
  }

  const investigate = async (question: string, context: AssistantContext = selectedContext) => {
    if (!run) return
    const requestRunId = run.run_id
    const requestContextKey = assistantContextKey(requestRunId, context)
    const history = conversationHistory(assistantThreads[requestContextKey])
    const requestSequence = ++investigationSequenceRef.current
    try {
      setInvestigating(true)
      const answer = await api.investigate(requestRunId, question, context, page, history)
      if (activeRunIdRef.current !== requestRunId || investigationSequenceRef.current !== requestSequence) return
      setAssistantThreads((current) => {
        const thread = current[requestContextKey] ?? { context, messages: [] }
        return { ...current, [requestContextKey]: { ...thread, messages: [...thread.messages, answer] } }
      })
      try {
        const refreshedDiagnostics = await api.diagnostics(requestRunId)
        if (activeRunIdRef.current === requestRunId && investigationSequenceRef.current === requestSequence) {
          setDiagnostics(refreshedDiagnostics)
        }
      } catch (cause) {
        if (activeRunIdRef.current === requestRunId && investigationSequenceRef.current === requestSequence) {
          setError(cause instanceof Error ? cause.message : 'Diagnostics refresh failed')
        }
      }
    } catch (cause) {
      if (activeRunIdRef.current === requestRunId && investigationSequenceRef.current === requestSequence) {
        setError(cause instanceof Error ? cause.message : 'Investigation failed')
      }
    } finally {
      if (investigationSequenceRef.current === requestSequence) setInvestigating(false)
    }
  }

  const openAssistantForContext = (context: AssistantContext) => {
    if (!run) return
    const key = assistantContextKey(run.run_id, context)
    setAssistantThreads((current) => current[key] ? current : { ...current, [key]: { context, messages: [] } })
    setSelectedContext(context)
    setAssistantOpen(true)
    setAssistantFocusRequest((current) => current + 1)
  }

  const askAboutSettlement = (row: ReconciliationRow) => {
    openAssistantForContext({ settlement_id: row.settlement_id, proof_id: row.proof_id })
  }

  const askAboutException = (item: ExceptionItem) => {
    openAssistantForContext({ proof_id: item.proof_id })
  }

  const approve = async (reason: string) => {
    if (!run) throw new Error('The active reconciliation run is unavailable.')
    try {
      setApproving(true)
      setCloseState(await api.approveClose(run.run_id, reason))
      setMessage('Final Close Pack approved with the recorded operator reason.')
    } finally { setApproving(false) }
  }

  const submitOperatorAction = async (text: string, option?: string) => {
    if (!operatorAction) throw new Error('The selected operator action is unavailable.')
    if (operatorAction.kind === 'review') {
      await review(operatorAction.item, operatorAction.action, text)
      return
    }
    if (operatorAction.kind === 'close') {
      await approve(text)
      return
    }
    const feedbackType = FEEDBACK_OPTIONS.find((item) => item.value === option)?.value
    if (!feedbackType) throw new Error('Select a supported feedback type.')
    const feedback = await api.challenge(operatorAction.proof.proof_id, feedbackType, text)
    setChallengeConfirmation(`Recorded ${feedback.feedback_type.replaceAll('_', ' ').toLowerCase()}: ${feedback.comment}`)
  }

  if (loading) return <div className="startup"><span className="brand-mark">P</span><h1>ProofClose</h1><p>{message}</p><div className="progress-line" /></div>
  if (page === 'sources') return <div className="app-shell"><AppHeader active={page} identityMode="INSECURE_DEMO_CONTEXT" running={running} canRun={Boolean(run)} onHome={onHome} onNavigate={navigate} onRun={() => void rerun()} /><SourcesPage onRun={runSelectedSources} running={running} /></div>
  if (error && !run) return <div className="startup error-state"><h1>ProofClose could not start</h1><p>{error}</p><button className="primary-action" onClick={() => void initialize()}>Retry initialization</button></div>
  if (!run || !closeState || !diagnostics) return <div className="startup"><h1>No reconciliation run selected</h1><p>Select source files to create your first run.</p><button className="primary-action" onClick={() => navigate('sources')}>Open Data sources</button></div>

  const selectedThread = assistantThreads[assistantContextKey(run.run_id, selectedContext)]
  const assistant = (expanded = false, modal = false) => <EvidenceAssistant
    runId={run.run_id}
    mode={assistantMode}
    messages={selectedThread?.messages ?? []}
    loading={investigating}
    selectedContext={selectedContext}
    focusRequest={assistantFocusRequest}
    expanded={expanded}
    modal={modal}
    onAsk={(question, context) => void investigate(question, context)}
    onProof={(id) => void openProof(id)}
    onClose={() => expanded ? navigate('reconciliation') : setAssistantOpen(false)}
    onExpand={expanded ? undefined : () => navigate('investigate')}
  />

  let workspacePage = null
  if (page === 'reconciliation') workspacePage = <ReconciliationPage run={run} rows={rows} onProof={(id) => void openProof(id)} onAskAbout={askAboutSettlement} />
  if (page === 'exceptions') workspacePage = <ExceptionsPage items={exceptions} reviewing={reviewing} onProof={(id) => void openProof(id)} onAskAbout={askAboutException} onReview={(item, action) => setOperatorAction({ kind: 'review', item, action })} />
  if (page === 'close') workspacePage = <ClosePage state={closeState} approving={approving} onApprove={() => setOperatorAction({ kind: 'close' })} />

  let actionDialog = null
  if (operatorAction?.kind === 'review') {
    const copy = REVIEW_DIALOG_COPY[operatorAction.action]
    actionDialog = <ActionDialog
      title={copy.title}
      description={`Record the reason for ${operatorAction.item.exception_type.replaceAll('_', ' ').toLowerCase()} (${operatorAction.item.exception_id}). The exact text becomes part of the audit trail.`}
      fieldLabel="Operator reason"
      confirmLabel={copy.confirm}
      onClose={() => setOperatorAction(null)}
      onSubmit={submitOperatorAction}
    />
  } else if (operatorAction?.kind === 'close') {
    actionDialog = <ActionDialog
      title="Approve final close"
      description={`Record why this ${closeState.state === 'READY' ? 'clean close' : 'close with reviewed exceptions'} is approved. The exact text is bound into the immutable Final Close Pack.`}
      fieldLabel="Approval reason"
      confirmLabel="Approve final close"
      onClose={() => setOperatorAction(null)}
      onSubmit={submitOperatorAction}
    />
  } else if (operatorAction?.kind === 'challenge') {
    actionDialog = <ActionDialog
      title="Challenge financial proof"
      description={`Record append-only feedback for ${operatorAction.proof.subject.subject_id}. This does not change the proof, decision, rule, configuration, or close state.`}
      fieldLabel="Operator comment"
      confirmLabel="Submit challenge"
      optionLabel="Feedback type"
      options={FEEDBACK_OPTIONS}
      initialOption="INCORRECT_MATCH"
      onClose={() => setOperatorAction(null)}
      onSubmit={submitOperatorAction}
    />
  }

  return (
    <div className="app-shell">
      <AppHeader active={page} identityMode="INSECURE_DEMO_CONTEXT" running={running} onHome={onHome} onNavigate={navigate} onRun={() => void rerun()} />
      {error && <div className="toast error-toast" role="alert"><span>{error}</span><button onClick={() => setError(null)}>Dismiss</button></div>}
      {message && <div className="toast" role="status"><span>{message}</span><button onClick={() => setMessage('')}>Dismiss</button></div>}
      {workspacePage && <WorkspaceLayout assistantOpen={assistantOpen} onOpenAssistant={() => setAssistantOpen(true)} onCloseAssistant={() => setAssistantOpen(false)} assistant={(modal) => assistant(false, modal)}>{workspacePage}</WorkspaceLayout>}
      {page === 'investigate' && <InvestigatePage assistant={assistant(true)} />}
      {page === 'diagnostics' && <DiagnosticsPage data={diagnostics} />}
      {proof && <ProofDrawer proof={proof} busyAction={proofAction} challengeConfirmation={challengeConfirmation} onClose={() => setProof(null)} onAction={(action) => void actOnProof(action)} onChallenge={() => setOperatorAction({ kind: 'challenge', proof })} />}
      {actionDialog}
    </div>
  )
}

export default function App() {
  const [pathname, setPathname] = useState(() => window.location.pathname)

  useEffect(() => {
    const onPopState = () => setPathname(window.location.pathname)
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigatePath = useCallback((path: string) => {
    if (window.location.pathname !== path) window.history.pushState({}, '', path)
    setPathname(path)
    window.scrollTo?.({ top: 0, behavior: 'smooth' })
  }, [])

  if (!isWorkspacePath(pathname)) {
    return <LandingPage onOpenWorkspace={() => navigatePath('/workspace')} />
  }

  return <WorkspaceApp pathname={pathname} onHome={() => navigatePath('/')} onPathChange={navigatePath} />
}
