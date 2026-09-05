import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  // Browser scenarios share one local demo backend and must not swap each
  // other's selected snapshots while another scenario is still running.
  workers: 1,
  retries: 0,
  reporter: 'line',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:5173',
    channel: 'msedge',
    viewport: { width: 1280, height: 800 },
    trace: 'retain-on-failure',
  },
})
