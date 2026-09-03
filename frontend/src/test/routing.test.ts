import { expect, it } from 'vitest'

import { isWorkspacePath, pageForPath, pathForPage } from '../app/routing'

it('keeps the public landing route separate from operational workspace routes', () => {
  expect(isWorkspacePath('/')).toBe(false)
  expect(isWorkspacePath('/workspace')).toBe(true)
  expect(isWorkspacePath('/workspace/exceptions')).toBe(true)
  expect(pathForPage('reconciliation')).toBe('/workspace')
  expect(pathForPage('investigate')).toBe('/workspace/assistant')
  expect(pageForPath('/workspace/close')).toBe('close')
})
