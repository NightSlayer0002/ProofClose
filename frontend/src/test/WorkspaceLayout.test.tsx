import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { WorkspaceLayout } from '../components/WorkspaceLayout'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('WorkspaceLayout', () => {
  it('makes every application sibling inert while the narrow assistant is modal', () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: true,
      media: '(max-width: 1080px)',
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })))

    const { unmount } = render(
      <div className="app-shell">
        <header data-testid="app-header"><button>Reconciliation</button></header>
        <WorkspaceLayout
          assistantOpen
          onOpenAssistant={vi.fn()}
          onCloseAssistant={vi.fn()}
          assistant={() => <aside role="dialog" aria-label="Evidence Assistant">Assistant</aside>}
        >
          <main>Finance workspace</main>
        </WorkspaceLayout>
      </div>,
    )

    expect(screen.getByTestId('app-header').inert).toBe(true)
    expect(screen.getByText('Finance workspace').parentElement?.inert).toBe(true)
    unmount()
    expect(document.body.style.overflow).toBe('')
  })
})
