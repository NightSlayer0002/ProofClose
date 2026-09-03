import { Activity, Play, ShieldCheck } from 'lucide-react'

import type { Page } from '../app/types'
import { Tooltip } from './Tooltip'

interface Props {
  active: Page
  identityMode: string
  running: boolean
  onHome: () => void
  onNavigate: (page: Page) => void
  onRun: () => void
}

const primary: Array<{ id: Page; label: string }> = [
  { id: 'reconciliation', label: 'Reconciliation' },
  { id: 'exceptions', label: 'Exceptions' },
  { id: 'investigate', label: 'Assistant' },
  { id: 'close', label: 'Close' },
]

export function AppHeader({ active, identityMode, running, onHome, onNavigate, onRun }: Props) {
  return (
    <header className="app-header">
      <button className="brand" onClick={onHome} aria-label="ProofClose home">
        <span className="brand-mark"><ShieldCheck aria-hidden="true" size={17} /></span>
        <span className="brand-name">ProofClose</span>
      </button>
      <nav className="primary-nav" aria-label="Primary">
        <div className="nav-track">
          {primary.map((item) => (
            <button
              key={item.id}
              className={active === item.id ? 'active' : ''}
              aria-current={active === item.id ? 'page' : undefined}
              onClick={() => onNavigate(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </nav>
      <div className="header-trust">
        <span
          className="identity-warning"
          title={`Offline demo identity headers only · ${identityMode.replaceAll('_', ' ').toLowerCase()}`}
        >
          Demo context—not authentication
        </span>
      </div>
      <div className="header-actions">
        <Tooltip content="View measured run timings, provider reachability, and proof failures." side="bottom">
          <button className="diagnostics-link" onClick={() => onNavigate('diagnostics')}>
            <Activity aria-hidden="true" size={15} /> <span className="diagnostics-label">Diagnostics</span>
          </button>
        </Tooltip>
        <button className={`primary-action run-action ${running ? 'is-running' : ''}`} onClick={onRun} disabled={running}>
          <Play aria-hidden="true" size={14} fill="currentColor" /> <span className="run-label">{running ? 'Reconciling…' : 'Run reconciliation'}</span>
        </button>
      </div>
    </header>
  )
}
