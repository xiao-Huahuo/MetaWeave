/** Real MCP UI acceptance against separately owned Vite/backend processes; one worker, no mocks. */
import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './e2e', testMatch: ['mcp-settings.spec.ts', 'mcp-style.spec.ts'], workers: 1, fullyParallel: false,
  retries: 0, maxFailures: 1, timeout: 120_000, reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:5177', headless: true, viewport: { width: 1280, height: 900 }, trace: 'off' },
})
