import { useEffect, useRef } from 'react'

/** Background-only parallax: CSS loops; pointer updates are capped to one browser frame. */
export function LandingBackdrop({ paused }: { paused: boolean }) {
  const backdrop = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = backdrop.current
    if (!element) return
    let frame = 0
    let active = false
    let pointerX = 0
    let pointerY = 0

    const paintPointer = () => {
      frame = 0
      element.style.setProperty('--pointer-x', `${pointerX.toFixed(2)}px`)
      element.style.setProperty('--pointer-y', `${pointerY.toFixed(2)}px`)
    }
    const updatePointer = (event: PointerEvent) => {
      if (!active || event.pointerType === 'touch') return
      pointerX = Math.max(-1, Math.min(1, event.clientY / Math.max(window.innerHeight, 1) * 2 - 1)) * -8
      pointerY = Math.max(-1, Math.min(1, event.clientX / Math.max(window.innerWidth, 1) * 2 - 1)) * 12
      if (!frame) frame = window.requestAnimationFrame(paintPointer)
    }
    const resetPointer = () => {
      if (frame) window.cancelAnimationFrame(frame)
      frame = 0
      element.style.removeProperty('--pointer-x')
      element.style.removeProperty('--pointer-y')
    }
    const updateMotion = () => {
      // The page owns the OS preference and an explicit visitor opt-in.
      active = !paused && !document.hidden
      element.dataset.motion = active ? 'running' : 'paused'
      if (!active) resetPointer()
    }
    updateMotion()
    window.addEventListener('pointermove', updatePointer, { passive: true })
    document.documentElement.addEventListener('pointerleave', resetPointer)
    document.addEventListener('visibilitychange', updateMotion)
    return () => {
      resetPointer()
      window.removeEventListener('pointermove', updatePointer)
      document.documentElement.removeEventListener('pointerleave', resetPointer)
      document.removeEventListener('visibilitychange', updateMotion)
    }
  }, [paused])

  return (
    <div className="landing-backdrop" ref={backdrop} aria-hidden="true">
      <div className="pc-parallax"><div className="pc-background-plane pc-plane-near" /><div className="pc-background-plane pc-plane-far" /></div>
    </div>
  )
}
