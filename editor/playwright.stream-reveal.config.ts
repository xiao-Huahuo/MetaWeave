/**
 * Temporary headless configuration for the stream-reveal UI acceptance run.
 *
 * Usage: reuses the explicitly managed Vite process and is deleted after the
 * focused Chromium test completes.
 */
import { defineConfig } from '@playwright/test'

import baseConfig from './playwright.config'

export default defineConfig({
  ...baseConfig,
  use: {
    ...baseConfig.use,
    baseURL: 'http://127.0.0.1:5174',
    headless: true,
  },
  webServer: undefined,
})
