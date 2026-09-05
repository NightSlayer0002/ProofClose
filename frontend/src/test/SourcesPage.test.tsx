import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SourcesPage } from '../pages/SourcesPage'

const mock = vi.hoisted(() => ({ sourceSchema: vi.fn(), sources: vi.fn(), uploadSource: vi.fn() }))
vi.mock('../app/api', () => ({ api: mock }))
const roles = ['merchant_orders', 'razorpay_recon', 'settlements', 'bank_statement']
beforeEach(() => {
  vi.resetAllMocks()
  mock.sourceSchema.mockResolvedValue({ currency: 'INR', max_bytes: 5242880, max_rows: 5000, normalization_version: '1.0', sources: roles.map((role) => ({ source_type: role, label: role, required_columns: ['id'], optional_columns: [], money_columns: [], template_csv: 'id\n' })) })
  mock.sources.mockResolvedValue({ items: roles.map((role) => ({ source_id: role + '-new', source_type: role, state: 'ACCEPTED', filename: role + '.csv', row_count: 7, content_hash: 'abcd1234', error: null, created_at: '2026-09-05T00:00:00Z' })) })
})
afterEach(cleanup)

it('requires every source to be selected and passes only the chosen snapshot inputs', async () => {
  const onRun = vi.fn().mockResolvedValue(undefined)
  render(<SourcesPage onRun={onRun} running={false} />)
  const run = await screen.findByRole('button', { name: 'Create snapshot & reconcile' })
  expect(run).toBeDisabled()
  for (const role of roles) await userEvent.selectOptions(await screen.findByLabelText(`Select ${role}`), `${role}-new`)
  expect(run).toBeEnabled()
  await userEvent.click(run)
  expect(onRun).toHaveBeenCalledWith(roles.map((role) => `${role}-new`), undefined)
})

it('shows validation errors without selecting rejected evidence or starting a run', async () => {
  mock.uploadSource.mockRejectedValue(new Error('Row 2: amount must be a whole paise integer'))
  const onRun = vi.fn()
  render(<SourcesPage onRun={onRun} running={false} />)
  await userEvent.upload(await screen.findByLabelText('Upload settlements'), new File(['bad'], 'new.csv', { type: 'text/csv' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('whole paise integer')
  expect(screen.getByLabelText('Select settlements')).toHaveValue('')
  expect(onRun).not.toHaveBeenCalled()
})
