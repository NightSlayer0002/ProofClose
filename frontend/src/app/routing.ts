import type { Page } from './types'

const paths: Record<Page, string> = {
  reconciliation: '/workspace',
  exceptions: '/workspace/exceptions',
  investigate: '/workspace/assistant',
  close: '/workspace/close',
  diagnostics: '/workspace/ops',
}

export function isWorkspacePath(pathname: string): boolean {
  return pathname === '/workspace' || pathname.startsWith('/workspace/')
}

export function pathForPage(page: Page): string {
  return paths[page]
}

export function pageForPath(pathname: string): Page {
  const normalized = pathname.length > 1 ? pathname.replace(/\/$/, '') : pathname
  return (Object.entries(paths).find(([, path]) => path === normalized)?.[0] as Page | undefined) ?? 'reconciliation'
}
