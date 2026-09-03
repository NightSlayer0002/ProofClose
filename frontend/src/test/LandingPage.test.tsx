import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import { LandingPage } from '../pages/LandingPage'

it('dramatizes evidence provenance while keeping AI outside the hero', () => {
  render(<LandingPage />)

  const hero = screen.getByRole('region', { name: 'Evidence-first settlement close' })
  expect(hero).toHaveTextContent('Merchant orders')
  expect(hero).toHaveTextContent('Razorpay recon')
  expect(hero).toHaveTextContent('Bank credits')
  expect(hero).toHaveTextContent('Frozen snapshot')
  expect(hero).toHaveTextContent('Versioned proof')
  expect(hero).not.toHaveTextContent(/AI|copilot|LLM/i)

  expect(screen.getByRole('heading', { name: 'One financial fact. Every source bound.' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Measured on synthetic evidence—not marketed as production accuracy.' })).toBeVisible()
  expect(screen.getByText('Read-only Evidence Assistant')).toBeVisible()
})
