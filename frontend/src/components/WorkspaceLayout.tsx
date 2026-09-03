import { MessageSquareText } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

const narrowQuery = '(max-width: 1080px)'

export function WorkspaceLayout({
  children,
  assistant,
  assistantOpen,
  onOpenAssistant,
  onCloseAssistant,
}: {
  children: ReactNode
  assistant: (modal: boolean) => ReactNode
  assistantOpen: boolean
  onOpenAssistant: () => void
  onCloseAssistant: () => void
}) {
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(narrowQuery).matches ?? false)
  const layoutRef = useRef<HTMLDivElement>(null)
  const mainRef = useRef<HTMLDivElement>(null)
  const reopenRef = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(assistantOpen)

  useEffect(() => {
    if (!window.matchMedia) return
    const query = window.matchMedia(narrowQuery)
    const update = () => setNarrow(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    const modalOpen = narrow && assistantOpen
    const layout = layoutRef.current
    const main = mainRef.current
    const siblings = layout?.parentElement
      ? Array.from(layout.parentElement.children).filter((element): element is HTMLElement => element instanceof HTMLElement && element !== layout)
      : []
    const priorInert = siblings.map((element) => element.inert)
    const previousMainInert = main?.inert ?? false
    const previousOverflow = document.body.style.overflow
    if (main) main.inert = modalOpen
    if (!modalOpen) return
    siblings.forEach((element) => { element.inert = true })
    document.body.style.overflow = 'hidden'
    return () => {
      if (main) main.inert = previousMainInert
      siblings.forEach((element, index) => { element.inert = priorInert[index] ?? false })
      document.body.style.overflow = previousOverflow
    }
  }, [assistantOpen, narrow])

  useEffect(() => {
    if (wasOpen.current && !assistantOpen && narrow) reopenRef.current?.focus()
    wasOpen.current = assistantOpen
  }, [assistantOpen, narrow])

  return (
    <div ref={layoutRef} className={`workspace-layout ${assistantOpen ? 'assistant-open' : ''}`} data-assistant-open={assistantOpen}>
      <div ref={mainRef} className="workspace-main">{children}</div>
      {assistantOpen && narrow && <button className="assistant-backdrop" onClick={onCloseAssistant} aria-label="Close Evidence Assistant" />}
      {assistantOpen ? <div className={`assistant-dock ${narrow ? 'assistant-modal' : 'assistant-column'}`}>{assistant(narrow)}</div> : <button ref={reopenRef} className="assistant-reopen" onClick={onOpenAssistant} aria-label="Open Evidence Assistant"><MessageSquareText aria-hidden="true" size={17} />Evidence Assistant</button>}
    </div>
  )
}
