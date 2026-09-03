import type { ReactNode } from 'react'

export function InvestigatePage({ assistant }: { assistant: ReactNode }) {
  return (
    <main className="page investigate-page" aria-labelledby="investigate-title">
      <div className="page-heading"><div><p className="eyebrow">Expanded evidence workspace</p><h1 id="investigate-title">Evidence Assistant</h1><p>The same proof-linked conversation, with more room to inspect canonical facts.</p></div></div>
      <div className="expanded-assistant-wrap">{assistant}</div>
    </main>
  )
}
