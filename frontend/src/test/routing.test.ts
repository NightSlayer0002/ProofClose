import { describe, expect, it } from 'vitest'

import { pageForPath, pathForPage } from '../app/routing'

describe('operations routes', () => {
  it('maps every workspace page to a stable bookmarkable path', () => {
    expect(pathForPage('reconciliation')).toBe('/')
    expect(pathForPage('exceptions')).toBe('/exceptions')
    expect(pathForPage('investigate')).toBe('/investigate')
    expect(pathForPage('close')).toBe('/close')
    expect(pathForPage('diagnostics')).toBe('/ops')
    expect(pageForPath('/exceptions')).toBe('exceptions')
    expect(pageForPath('/unknown')).toBe('reconciliation')
  })
})

