import { cloneElement, useEffect, useId, useLayoutEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

type TooltipTriggerProps = {
  'aria-describedby'?: string
}

type TooltipLayer = 'base' | 'assistant' | 'proof'

interface TooltipProps {
  content: ReactNode
  children: ReactElement
  side?: 'top' | 'bottom'
}

export function Tooltip({ content, children, side = 'top' }: TooltipProps) {
  const id = useId()
  const anchor = useRef<HTMLSpanElement>(null)
  const bubble = useRef<HTMLSpanElement>(null)
  const timer = useRef<number | null>(null)
  const [open, setOpen] = useState(false)
  const [layer, setLayer] = useState<TooltipLayer>('base')
  const [position, setPosition] = useState({ top: 0, left: 0, ready: false })

  const cancelTimer = () => {
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
  }

  const hide = () => {
    cancelTimer()
    setOpen(false)
  }

  const show = () => {
    const container = anchor.current
    setLayer(container?.closest('.proof-drawer')
      ? 'proof'
      : container?.closest('.evidence-assistant')
        ? 'assistant'
        : 'base')
    setOpen(true)
  }

  useEffect(() => cancelTimer, [])

  useLayoutEffect(() => {
    if (!open) return

    const place = () => {
      if (!anchor.current || !bubble.current) return
      const triggerRect = anchor.current.getBoundingClientRect()
      const tooltipRect = bubble.current.getBoundingClientRect()
      const gap = 8
      const inset = 12
      const topPlacement = triggerRect.top - tooltipRect.height - gap
      const bottomPlacement = triggerRect.bottom + gap
      let top = side === 'top' ? topPlacement : bottomPlacement

      if (top < inset) top = bottomPlacement
      if (top + tooltipRect.height > window.innerHeight - inset) top = Math.max(inset, topPlacement)

      const centeredLeft = triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2
      const maximumLeft = Math.max(inset, window.innerWidth - tooltipRect.width - inset)
      const left = Math.min(Math.max(inset, centeredLeft), maximumLeft)
      setPosition({ top, left, ready: true })
    }

    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open, side])

  const trigger = cloneElement(children as ReactElement<TooltipTriggerProps>, {
    'aria-describedby': open ? id : undefined,
  })

  return (
    <span
      ref={anchor}
      className="tooltip-anchor"
      onPointerEnter={() => {
        cancelTimer()
        timer.current = window.setTimeout(show, 300)
      }}
      onPointerLeave={hide}
      onFocusCapture={() => {
        cancelTimer()
        show()
      }}
      onBlurCapture={hide}
      onKeyDownCapture={(event) => {
        if (event.key === 'Escape') {
          event.stopPropagation()
          hide()
        }
      }}
    >
      {trigger}
      {open && createPortal(
        <span
          ref={bubble}
          id={id}
          role="tooltip"
          className="tooltip"
          data-layer={layer}
          data-ready={position.ready}
          style={{ top: position.top, left: position.left }}
        >
          {content}
        </span>,
        document.body,
      )}
    </span>
  )
}
