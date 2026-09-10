/** Guards the literature-reading toolbar against unstyled menus and text regressions. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'src/views/LiteratureReadingView.vue'), 'utf8')

describe('LiteratureReadingView module', () => {
  it('uses the shared themed dropdown-menu components', () => {
    expect(source).toContain("from '@/components/ui/dropdown-menu'")
    expect(source).not.toContain("from 'reka-ui'")
  })

  it('keeps refresh and create as accessible icon-only actions', () => {
    expect(source).toContain('title="刷新" aria-label="刷新文献库"')
    expect(source).toContain('title="新建" aria-label="新建文献"')
    expect(source).not.toContain('<span>刷新</span>')
    expect(source).not.toContain('<span>新建</span>')
  })
})
