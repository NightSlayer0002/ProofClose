import { describe, expect, it } from 'vitest'

import { formatINR } from '../app/formatters'

describe('formatINR', () => {
  it('formats integer paise with Indian grouping and preserves the sign', () => {
    expect(formatINR(84_239_100)).toBe('₹8,42,391.00')
    expect(formatINR(-25_050)).toBe('-₹250.50')
  })
})
