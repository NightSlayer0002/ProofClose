import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import { ActionDialog } from '../components/ActionDialog'

afterEach(() => {
  cleanup()
  document.body.style.overflow = ''
})

const renderDialog = (onSubmit = vi.fn().mockResolvedValue(undefined)) => render(
  <ActionDialog
    title="Record review"
    description="Record the accountable operator decision."
    fieldLabel="Operator reason"
    confirmLabel="Record decision"
    onClose={vi.fn()}
    onSubmit={onSubmit}
  />,
)

it('requires five visible non-whitespace characters before confirmation', async () => {
  const user = userEvent.setup()
  renderDialog()
  const reason = screen.getByRole('textbox', { name: 'Operator reason' })
  const confirm = screen.getByRole('button', { name: 'Record decision' })

  expect(confirm).toBeDisabled()
  await user.type(reason, '   ')
  expect(confirm).toBeDisabled()
  await user.clear(reason)
  await user.type(reason, 'a b c d')
  expect(confirm).toBeDisabled()
  await user.type(reason, ' e')
  expect(confirm).toBeEnabled()
})

it('submits exact trimmed text once while a request is running', async () => {
  let resolve!: () => void
  const onSubmit = vi.fn(() => new Promise<void>((done) => { resolve = done }))
  const onClose = vi.fn()
  render(
    <ActionDialog
      title="Record review"
      description="Record the accountable operator decision."
      fieldLabel="Operator reason"
      confirmLabel="Record decision"
      onClose={onClose}
      onSubmit={onSubmit}
    />,
  )
  await userEvent.type(screen.getByRole('textbox', { name: 'Operator reason' }), '  Evidence checked by controller.  ')
  const confirm = screen.getByRole('button', { name: 'Record decision' })

  fireEvent.click(confirm)
  fireEvent.click(confirm)

  expect(onSubmit).toHaveBeenCalledTimes(1)
  expect(onSubmit).toHaveBeenCalledWith('Evidence checked by controller.', undefined)
  expect(confirm).toBeDisabled()
  await act(async () => resolve())
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
})

it('keeps the dialog open with a useful error after a failed request', async () => {
  const onSubmit = vi.fn().mockRejectedValue(new Error('The review item is no longer open.'))
  const onClose = vi.fn()
  render(
    <ActionDialog
      title="Record review"
      description="Record the accountable operator decision."
      fieldLabel="Operator reason"
      confirmLabel="Record decision"
      onClose={onClose}
      onSubmit={onSubmit}
    />,
  )
  await userEvent.type(screen.getByRole('textbox', { name: 'Operator reason' }), 'Checked source records')
  await userEvent.click(screen.getByRole('button', { name: 'Record decision' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('The review item is no longer open.')
  expect(screen.getByRole('dialog', { name: 'Record review' })).toBeVisible()
  expect(screen.getByRole('textbox', { name: 'Operator reason' })).toHaveValue('Checked source records')
  expect(onClose).not.toHaveBeenCalled()
})

it('traps focus, supports keyboard submission and restores focus after Escape', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined)

  function Harness() {
    const [open, setOpen] = useState(false)
    return <div>
      <button onClick={() => setOpen(true)}>Open review</button>
      {open && <ActionDialog
        title="Record review"
        description="Record the accountable operator decision."
        fieldLabel="Operator reason"
        confirmLabel="Record decision"
        onClose={() => setOpen(false)}
        onSubmit={onSubmit}
      />}
    </div>
  }

  const user = userEvent.setup()
  render(<Harness />)
  const trigger = screen.getByRole('button', { name: 'Open review' })
  await user.click(trigger)
  const reason = screen.getByRole('textbox', { name: 'Operator reason' })
  expect(screen.getByRole('dialog', { name: 'Record review' })).toHaveAccessibleDescription('Record the accountable operator decision.')
  expect(reason).toHaveFocus()
  expect(document.body.style.overflow).toBe('hidden')

  await user.type(reason, 'Reviewed against bank evidence')
  screen.getByRole('button', { name: 'Close dialog' }).focus()
  await user.tab({ shift: true })
  expect(screen.getByRole('button', { name: 'Record decision' })).toHaveFocus()
  await user.tab()
  expect(screen.getByRole('button', { name: 'Close dialog' })).toHaveFocus()
  reason.focus()
  await user.keyboard('{Escape}')

  expect(screen.queryByRole('dialog', { name: 'Record review' })).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  expect(document.body.style.overflow).toBe('')

  await user.click(trigger)
  await user.type(screen.getByRole('textbox', { name: 'Operator reason' }), 'Reviewed using keyboard')
  await user.tab()
  await user.tab()
  await user.keyboard('{Enter}')
  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('Reviewed using keyboard', undefined))
  expect(screen.queryByRole('dialog', { name: 'Record review' })).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
})

it('submits an allowlisted selection with the exact trimmed comment', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  render(
    <ActionDialog
      title="Challenge proof"
      description="Record append-only feedback."
      fieldLabel="Operator comment"
      confirmLabel="Submit challenge"
      optionLabel="Feedback type"
      options={[
        { value: 'INCORRECT_MATCH', label: 'Incorrect match' },
        { value: 'PROOF_UNCLEAR', label: 'Proof unclear' },
      ]}
      initialOption="INCORRECT_MATCH"
      onClose={vi.fn()}
      onSubmit={onSubmit}
    />,
  )

  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Feedback type' }), 'PROOF_UNCLEAR')
  await userEvent.type(screen.getByRole('textbox', { name: 'Operator comment' }), '  Missing source explanation.  ')
  await userEvent.click(screen.getByRole('button', { name: 'Submit challenge' }))

  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('Missing source explanation.', 'PROOF_UNCLEAR'))
})
