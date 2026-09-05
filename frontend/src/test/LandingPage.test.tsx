import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

import { LandingPage } from '../pages/LandingPage'

afterEach(cleanup)

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

  for (const implementationLabel of [
    'orders · recon · settlements · bank',
    'snapshot_hash = sha256(…)',
    'rule 2.0 · config 2.0',
    'artifact_fingerprint',
  ]) {
    expect(screen.queryByText(implementationLabel, { exact: true })).not.toBeInTheDocument()
  }
})

it('lets the visitor pause and resume decorative background motion', () => {
  const { container } = render(<LandingPage />)
  fireEvent.click(screen.getByRole('button', { name: 'Pause background animation' }))
  expect(container.querySelector('.landing-shell')).toHaveAttribute('data-motion-paused', 'true')
  expect(screen.getByRole('button', { name: 'Resume background animation' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Resume background animation' }))
  expect(container.querySelector('.landing-shell')).toHaveAttribute('data-motion-paused', 'false')
})

it('shows a real product capture with an explicit synthetic-data label before technical detail', () => {
  render(<LandingPage />)
  const preview = screen.getByRole('region', { name: 'From settlement to proof.' })
  expect(preview.querySelector('img')).toHaveAttribute('alt', expect.stringMatching(/reconciliation workspace/i))
  expect(preview).toHaveTextContent(/synthetic/i)
  expect(preview).toHaveTextContent(/offline/i)
  expect(screen.getByRole('table', { name: 'Synthetic regression results' })).toHaveTextContent('21 / 21')
})
