import { CircleCheck, CircleDashed, CircleX, Clock3, ShieldAlert, TriangleAlert } from 'lucide-react'

import { sentenceCase } from '../app/formatters'

const config = {
  AUTO_VERIFIED: { state: 'verified', Icon: CircleCheck },
  REVIEW_REQUIRED: { state: 'review', Icon: TriangleAlert },
  REFUSED: { state: 'refused', Icon: ShieldAlert },
  UNRESOLVED: { state: 'unresolved', Icon: CircleX },
  PENDING: { state: 'pending', Icon: Clock3 },
  SYSTEM_ERROR: { state: 'error', Icon: CircleX },
  OPEN: { state: 'review', Icon: TriangleAlert },
  LEFT_UNRESOLVED: { state: 'unresolved', Icon: CircleDashed, label: 'Reviewed unresolved' },
  APPROVED: { state: 'verified', Icon: CircleCheck },
  REJECTED: { state: 'refused', Icon: CircleX },
} as const

export function StatusLabel({ value }: { value: string }) {
  const item = config[value as keyof typeof config] ?? { state: 'pending', Icon: CircleDashed }
  return (
    <span className="status-label" data-state={item.state}>
      <item.Icon aria-hidden="true" size={13} strokeWidth={2} />
      {'label' in item ? item.label : sentenceCase(value)}
    </span>
  )
}
