import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AppHeader } from '../components/AppHeader'

describe('AppHeader', () => {
  it('labels demo identity as context rather than authentication', () => {
    render(
      <AppHeader
        active="reconciliation"
        identityMode="INSECURE_DEMO_CONTEXT"
        running={false}
        onHome={vi.fn()}
        onNavigate={vi.fn()}
        onRun={vi.fn()}
      />,
    )
    const identityBoundary = screen.getByText(/demo context—not authentication/i)
    expect(identityBoundary).toBeVisible()
    expect(identityBoundary).toHaveClass('identity-warning')
    expect(identityBoundary).not.toHaveTextContent(/signed in|authenticated/i)
    expect(screen.getByRole('navigation', { name: /primary/i })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Reconciliation' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'Exceptions' })).not.toHaveAttribute('aria-current')
  })
})
