import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StatusLabel } from '../components/StatusLabel'

describe('StatusLabel', () => {
  it('pairs semantic color with explicit text', () => {
    render(<StatusLabel value="REFUSED" />)
    expect(screen.getByText('Refused')).toHaveAttribute('data-state', 'refused')
  })

  it('makes a completed unresolved disposition visibly different from an open review', () => {
    render(<StatusLabel value="LEFT_UNRESOLVED" />)
    expect(screen.getByText('Reviewed unresolved')).toHaveAttribute('data-state', 'unresolved')
    expect(screen.queryByText('Left Unresolved')).not.toBeInTheDocument()
  })
})
