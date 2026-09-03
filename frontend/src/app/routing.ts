import type { Page } from './types'

const paths: Record<Page, string> = {
  reconciliation: '/',
  exceptions: '/exceptions',
  investigate: '/investigate',
  close: '/close',
  diagnostics: '/ops',
}

export function pathForPage(page: Page): string {
  return paths[page]
}

export function pageForPath(pathname: string): Page {
  return (Object.entries(paths).find(([, path]) => path === pathname)?.[0] as Page | undefined) ?? 'reconciliation'
}

