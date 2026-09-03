import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Tooltip } from '../components/Tooltip'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('Tooltip', () => {
  it('shows explanatory text after pointer intent and hides on exit', () => {
    vi.useFakeTimers()
    render(
      <Tooltip content="Opens the immutable proof">
        <button>Prove it</button>
      </Tooltip>,
    )

    fireEvent.pointerEnter(screen.getByRole('button', { name: 'Prove it' }))
    act(() => vi.advanceTimersByTime(299))
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    act(() => vi.advanceTimersByTime(1))
    expect(screen.getByRole('tooltip')).toHaveTextContent('Opens the immutable proof')

    fireEvent.pointerLeave(screen.getByRole('button', { name: 'Prove it' }))
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('works from keyboard focus and dismisses on Escape', () => {
    render(
      <Tooltip content="Audited review action">
        <button>Accept</button>
      </Tooltip>,
    )

    const trigger = screen.getByRole('button', { name: 'Accept' })
    fireEvent.focus(trigger)
    expect(screen.getByRole('tooltip')).toBeVisible()
    expect(trigger).toHaveAttribute('aria-describedby', screen.getByRole('tooltip').id)

    fireEvent.keyDown(trigger, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('renders outside scroll containers so it cannot be clipped by a table', () => {
    render(
      <div className="data-table-wrap">
        <Tooltip content="Opens immutable evidence">
          <button>Inspect proof</button>
        </Tooltip>
      </div>,
    )

    fireEvent.focus(screen.getByRole('button', { name: 'Inspect proof' }))
    expect(screen.getByRole('tooltip').parentElement).toBe(document.body)
  })

  it.each([
    ['evidence-assistant', 'assistant'],
    ['proof-drawer', 'proof'],
  ])('raises help above the active %s layer', (containerClass, expectedLayer) => {
    render(
      <div className={containerClass}>
        <Tooltip content="Layer-aware help">
          <button>Help</button>
        </Tooltip>
      </div>,
    )

    fireEvent.focus(screen.getByRole('button', { name: 'Help' }))
    expect(screen.getByRole('tooltip')).toHaveAttribute('data-layer', expectedLayer)
  })
})
