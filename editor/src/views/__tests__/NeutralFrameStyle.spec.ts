/*
 * Neutral frame migration contract.
 *
 * Usage:
 * Guards the accepted two-by-two neutral frame across frontend sources while
 * preserving the left activity bar's dedicated four-pixel ring.
 */
import { globSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import activityBarSource from '@/components/editor_workspace/ActivityBar.vue?raw'

const frontendSources = globSync('src/**/*.{css,ts,vue}')
  .filter((path) => !path.includes('/__tests__/') && !path.includes('\\__tests__\\'))
  .map((path) => [path, readFileSync(resolve(process.cwd(), path), 'utf8')] as const)
const uiSystemSource = readFileSync(resolve(process.cwd(), 'src/assets/ui-system.css'), 'utf8')

describe('neutral frame styling', () => {
  it('removes every legacy neutral four-pixel frame', () => {
    const legacyFrame = /0 0 0 4px var\(--(?:library-form-ring|workspace-panel-ring|color-border)\)|border:\s*4px solid var\(--library-form-ring\)/g
    const matches = frontendSources
      .flatMap(([path, source]) => [...source.matchAll(legacyFrame)].map((match) => `${path}:${match[0]}`))

    expect(matches).toEqual([])
  })

  it('defines the shared two-by-two frame and preserves the activity bar ring', () => {
    expect(uiSystemSource).toContain('--workspace-panel-outline: color-mix(in srgb, var(--color-text) 35%, transparent);')
    expect(uiSystemSource).toMatch(/\.library-form-surface,[\s\S]*?outline: 2px solid var\(--workspace-panel-outline\);[^}]*outline-offset: 2px;[^}]*box-shadow: 0 0 0 2px var\(--library-form-ring\);/s)
    expect(activityBarSource.match(/0 0 0 4px var\(--color-activity-bar-ring\)/g)).toHaveLength(2)
  })
})
