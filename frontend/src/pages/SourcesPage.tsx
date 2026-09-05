import { useEffect, useState } from 'react'
import { ArrowRight, CheckCircle2, Download, FileUp, Layers } from 'lucide-react'
import { api } from '../app/api'
import type { SourceCatalog, SourceFile } from '../app/types'

export function SourcesPage({ onRun, running }: { onRun: (sourceIds: string[], evaluatedAt?: string) => Promise<void>; running: boolean }) {
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null)
  const [sources, setSources] = useState<SourceFile[]>([])
  const [selected, setSelected] = useState<Record<string, string>>({})
  const [uploading, setUploading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [evaluationTime, setEvaluationTime] = useState('')

  useEffect(() => {
    let active = true
    Promise.all([api.sourceSchema(), api.sources()]).then(([schema, files]) => {
      if (active) { setCatalog(schema); setSources(files.items) }
    }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : 'Could not load source requirements') })
    return () => { active = false }
  }, [])

  const upload = async (type: string, file: File) => {
    setUploading(type); setError(null); setNotice('')
    try {
      const result = await api.uploadSource(type, file)
      setSelected((current) => ({ ...current, [type]: result.source_id }))
      const availableRows = result.accepted_rows + (result.duplicate_rows ?? 0)
      setNotice(`${file.name}: ${availableRows} row${availableRows === 1 ? '' : 's'} available.${result.duplicate_rows > 0 ? ' Existing delivery reused.' : ''} Existing runs have not changed.`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Upload rejected')
    } finally {
      try { setSources((await api.sources()).items) } catch { setError('Could not refresh source status. Reopen Data sources before starting a run.') }
      setUploading(null)
    }
  }

  const download = (filename: string, content: string) => {
    const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url; link.download = filename; link.click()
    URL.revokeObjectURL(url)
  }
  const selectedFiles = catalog?.sources.map((role) => sources.find((file) => file.source_id === selected[role.source_type] && file.source_type === role.source_type && file.state === 'ACCEPTED')) ?? []
  const ready = Boolean(catalog && selectedFiles.length > 0 && selectedFiles.length === catalog.sources.length && selectedFiles.every(Boolean))

  return <main className="sources-page">
    <header className="sources-heading"><p className="eyebrow">YOUR DATA · YOUR EVIDENCE</p><h1>Choose what this close is built on.</h1><p>Upload source deliveries, check validation, then choose the exact files to reconcile. Existing snapshots and proofs stay unchanged.</p></header>
    <aside className="source-contract"><Layers aria-hidden="true" size={22} /><div><strong>Explicit inputs. No guessing.</strong><p>INR only. Every amount is a whole paise integer—even columns named amount, credit or debit. For example, ₹125.50 is 12550. Other bank formats need an adapter before upload.</p><p>Use one CSV per role, from the same reporting period. Dates: ISO date, timezone-aware timestamp, or epoch seconds. Unknown columns and invalid rows are rejected, not silently ignored.</p></div></aside>
    {error && <p role="alert" className="source-error">{error}</p>}
    {notice && <p role="status" className="source-notice"><CheckCircle2 aria-hidden="true" size={17} />{notice}</p>}
    {!catalog && !error && <p role="status">Loading input requirements…</p>}
    <div className="source-grid">{catalog?.sources.map((role, index) => {
      const files = sources.filter((file) => file.source_type === role.source_type && file.state === 'ACCEPTED')
      return <section className="source-card" key={role.source_type}>
        <div className="source-card-heading"><span>0{index + 1}</span><h2>{role.label}</h2></div>
        <label className="source-upload"><FileUp aria-hidden="true" size={19} /><span>{uploading === role.source_type ? 'Validating delivery…' : 'Upload CSV'}</span><input aria-label={`Upload ${role.label}`} type="file" accept=".csv,text/csv" disabled={Boolean(uploading) || running} onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(role.source_type, file); event.target.value = '' }} /></label>
        <label className="source-selection">Accepted delivery<select aria-label={`Select ${role.label}`} value={selected[role.source_type] ?? ''} disabled={Boolean(uploading) || running} onChange={(event) => setSelected((current) => ({ ...current, [role.source_type]: event.target.value }))}><option value="">Select a file explicitly</option>{files.map((file) => <option key={file.source_id} value={file.source_id}>{file.filename} · {file.row_count} rows · {file.content_hash.slice(0, 8)}</option>)}</select></label>
        <details><summary>Columns and template</summary><p>Required: <code>{role.required_columns.join(', ')}</code></p><p>Optional columns may be omitted. If included, some require a value: use 0 for unused monetary fields.</p><p>Paise fields: <code>{role.money_columns.join(', ')}</code></p><button className="text-action" onClick={() => download(`${role.source_type}-template.csv`, role.required_columns.join(',') + '\n')}><Download aria-hidden="true" size={14} /> Download required-column template</button></details>
      </section>
    })}</div>
    <label className="source-selection">Evaluate as of (optional, your local time)<input type="datetime-local" value={evaluationTime} onChange={(event) => setEvaluationTime(event.target.value)} disabled={running} /><small>Leave blank for the current time on custom data. Historical dates affect pending decisions and are recorded in each proof. The unchanged bundled demo retains its documented example clock.</small></label>
    <section className="source-run"><div><strong>{selectedFiles.filter(Boolean).length} of {catalog?.sources.length ?? 4} source roles selected</strong><p>{ready ? `${selectedFiles.reduce((total, file) => total + (file?.row_count ?? 0), 0)} accepted rows. Only these files will enter the new snapshot.` : 'No source is selected automatically, including demo files.'}</p><small>Maximum {catalog?.max_rows.toLocaleString('en-IN') ?? '5,000'} rows and {catalog ? catalog.max_bytes / 1024 / 1024 : 5} MiB per file. This POC does not confirm whether your exports cover every transaction.</small></div><button className="primary-action" disabled={!ready || Boolean(uploading) || running} onClick={() => { setError(null); void onRun(selectedFiles.map((file) => file!.source_id), evaluationTime ? new Date(evaluationTime).toISOString() : undefined).catch((cause) => setError(cause instanceof Error ? cause.message : 'Run failed')) }}>{running ? 'Reconciling selected evidence…' : 'Create snapshot & reconcile'}<ArrowRight aria-hidden="true" size={16} /></button></section>
    {sources.some((file) => file.state === 'QUARANTINED') && <details className="source-quarantine"><summary>Rejected deliveries</summary>{sources.filter((file) => file.state === 'QUARANTINED').map((file) => <p key={file.source_id}><strong>{file.filename}</strong>: {file.error ?? 'Validation failed'}</p>)}</details>}
  </main>
}
