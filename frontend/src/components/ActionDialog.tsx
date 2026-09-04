import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { X } from 'lucide-react'

export interface ActionDialogOption {
  value: string
  label: string
}

interface Props {
  title: string
  description: string
  fieldLabel: string
  confirmLabel: string
  optionLabel?: string
  options?: readonly ActionDialogOption[]
  initialOption?: string
  onClose: () => void
  onSubmit: (text: string, option?: string) => Promise<void>
}

const visibleCharacterCount = (value: string) => Array.from(value)
  .filter((character) => !/[\s\p{C}]/u.test(character)).length

export function ActionDialog({
  title,
  description,
  fieldLabel,
  confirmLabel,
  optionLabel,
  options = [],
  initialOption,
  onClose,
  onSubmit,
}: Props) {
  const titleId = useId()
  const descriptionId = useId()
  const dialog = useRef<HTMLElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const closeRef = useRef(onClose)
  const submittingRef = useRef(false)
  const [text, setText] = useState('')
  const [option, setOption] = useState(initialOption ?? options[0]?.value ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  closeRef.current = onClose

  const trimmed = text.trim()
  const valid = visibleCharacterCount(trimmed) >= 5 && (options.length === 0 || options.some((item) => item.value === option))

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const layer = dialog.current?.parentElement
    const siblings = layer?.parentElement
      ? Array.from(layer.parentElement.children).filter((element): element is HTMLElement => element instanceof HTMLElement && element !== layer)
      : []
    const priorInert = siblings.map((element) => element.inert)
    const previousOverflow = document.body.style.overflow
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !submittingRef.current) {
        event.preventDefault()
        event.stopPropagation()
        closeRef.current()
      }
    }

    siblings.forEach((element) => { element.inert = true })
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKey, true)
    textarea.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey, true)
      siblings.forEach((element, index) => { element.inert = priorInert[index] ?? false })
      document.body.style.overflow = previousOverflow
      previous?.focus()
    }
  }, [])

  const trapFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Tab' || !dialog.current) return
    const focusable = Array.from(dialog.current.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )).filter((element) => !element.hidden)
    const first = focusable[0]
    const last = focusable.at(-1)
    if (!first || !last) return
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!valid || submittingRef.current) return
    submittingRef.current = true
    setSubmitting(true)
    setError(null)
    try {
      await onSubmit(trimmed, options.length ? option : undefined)
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The action could not be recorded. Try again.')
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  return (
    <div
      className="action-dialog-layer"
      role="presentation"
      onMouseDown={(event) => event.target === event.currentTarget && !submittingRef.current && onClose()}
    >
      <section
        ref={dialog}
        className="action-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={submitting}
        onKeyDown={trapFocus}
      >
        <header>
          <div><span className="section-kicker">Accountable operator action</span><h2 id={titleId}>{title}</h2></div>
          <button type="button" className="icon-button" aria-label="Close dialog" disabled={submitting} onClick={onClose}><X aria-hidden="true" size={17} /></button>
        </header>
        <p id={descriptionId} className="action-dialog-description">{description}</p>
        <form onSubmit={(event) => void submit(event)}>
          {options.length > 0 && <label className="action-dialog-field">
            <span>{optionLabel}</span>
            <select value={option} onChange={(event) => setOption(event.target.value)} disabled={submitting}>
              {options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>}
          <label className="action-dialog-field">
            <span>{fieldLabel}</span>
            <textarea
              ref={textarea}
              value={text}
              maxLength={2000}
              rows={5}
              disabled={submitting}
              aria-invalid={text.length > 0 && !valid}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <div className="action-dialog-guidance"><span>Minimum 5 visible characters</span><span>{text.length}/2000</span></div>
          {error && <p className="action-dialog-error" role="alert">{error}</p>}
          <footer>
            <button type="button" className="secondary-action" disabled={submitting} onClick={onClose}>Cancel</button>
            <button type="submit" className="primary-action" disabled={!valid || submitting}>{submitting ? 'Recording…' : confirmLabel}</button>
          </footer>
        </form>
      </section>
    </div>
  )
}
