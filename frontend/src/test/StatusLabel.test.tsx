import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StatusLabel } from '../components/StatusLabel'

describe('StatusLabel', () => {
  it('pairs semantic color with explicit text', () => {
    render(<StatusLabel value="REFUSED" />)
    expect(screen.getByText('Refused')).toHaveAttribute('data-state', 'refused')
  })
})
