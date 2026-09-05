import { useEffect, useRef } from 'react'

const faces = ['front', 'back', 'left', 'right', 'top', 'bottom'] as const

/** Decorative CSS 3D scene: no network, financial data or continuous JS render loop. */
export function LandingBackdrop({ paused }: { paused: boolean }) {
  const backdrop = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = backdrop.current
    if (!element) return
    const motion = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    let frame = 0
    let active = false
    let pointerX = 0
    let pointerY = 0

    const paintPointer = () => {
      frame = 0
      element.style.setProperty('--pointer-x', `${pointerX.toFixed(2)}deg`)
      element.style.setProperty('--pointer-y', `${pointerY.toFixed(2)}deg`)
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
      active = !paused && !motion?.matches && !document.hidden
      element.dataset.motion = active ? 'running' : 'paused'
      if (!active) resetPointer()
    }
    updateMotion()
    window.addEventListener('pointermove', updatePointer, { passive: true })
    document.documentElement.addEventListener('pointerleave', resetPointer)
    document.addEventListener('visibilitychange', updateMotion)
    motion?.addEventListener('change', updateMotion)
    return () => {
      resetPointer()
      window.removeEventListener('pointermove', updatePointer)
      document.documentElement.removeEventListener('pointerleave', resetPointer)
      document.removeEventListener('visibilitychange', updateMotion)
      motion?.removeEventListener('change', updateMotion)
    }
  }, [paused])

  return (
    <div className="landing-backdrop" ref={backdrop} aria-hidden="true">
      <div className="landing-ambient"><span /><span /><span /></div>
      {['primary', 'secondary', 'distant'].map((position) => (
        <div className={`evidence-orbit evidence-orbit-${position}`} key={position}>
          <div className="evidence-tilt">
            <div className="evidence-cube">
              {faces.map((face) => <span className={`evidence-face evidence-face-${face}`} key={face} />)}
            </div>
            <div className="evidence-orbit-ring"><i /></div>
            <div className="evidence-orbit-ring evidence-orbit-ring-cross"><i /></div>
          </div>
        </div>
      ))}
    </div>
  )
}
