/*
 * V1 circular toolbar-button browser acceptance.
 *
 * Usage:
 * Opens a real V1 consumer with deterministic API responses, verifies
 * computed circular geometry, and captures the toolbar hover state.
 */
import { expect, test, type Page } from '@playwright/test'

/** Supplies the minimum stable workspace contract required by the resource page. */
async function mockWorkspace(page: Page): Promise<void> {
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const json = (body: unknown) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })

    if (url.pathname === '/health') return route.fulfill({ status: 200, body: 'ok' })
    if (url.pathname === '/settings/models/status') return json({ embedding: 'ready', rerank: 'ready' })
    if (url.pathname === '/settings/profile') return json({
      user_id: 'v1-visual-smoke',
      knowledge_dir: 'D:/Knowledge',
      active_library_id: 'default',
      knowledge_libraries: [{ library_id: 'default', name: '视觉验收库', knowledge_dir: 'D:/Knowledge', is_active: true }],
    })
    if (url.pathname === '/knowledge/files') return json({ tree: [
      { name: '示例文档.md', path: '示例文档.md', isDir: false, size: 1024, mtime: '2026-09-10 12:00', indexStatus: 'indexed', graphStatus: 'graphed' },
    ] })
    if (url.pathname === '/knowledge/files/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': smoke\n\n' })
    if (url.pathname === '/favorites') return json({ favorites: [] })
    if (url.pathname === '/privacy') return json({ privacy: [] })
    if (url.pathname === '/knowledge/trash') return json({ entries: [] })
    if (url.pathname === '/sessions' && request.method() === 'GET') return json([])
    if (url.pathname === '/git/status') return json({ initialized: false, changes: [], branches: [], remote_branches: [], remotes: [] })
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') return json({})
    return route.continue()
  })

  await page.addInitScript(() => {
    localStorage.setItem('agent_editor_profile', JSON.stringify({
      userId: 'v1-visual-smoke',
      knowledgeDir: 'D:/Knowledge',
      activeLibraryId: 'default',
      knowledgeLibraries: [{ libraryId: 'default', name: '视觉验收库', knowledgeDir: 'D:/Knowledge', isActive: true }],
    }))
  })
}

test('V1 toolbar buttons are visibly circular', async ({ page }) => {
  test.setTimeout(15_000)
  await mockWorkspace(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: '进入MD-HTML', exact: true }).click()

  const buttons = page.locator('.visualization-toolbar button.v1-icon-button:visible')
  await expect(buttons.first()).toBeVisible()
  expect(await buttons.count()).toBeGreaterThanOrEqual(1)
  const styles = await buttons.evaluateAll((elements) => elements.map((element) => {
    const style = getComputedStyle(element)
    return {
      width: style.width,
      height: style.height,
      radius: style.borderRadius,
      border: style.borderStyle,
    }
  }))
  expect(styles.every((style) => (
    style.width === '28px'
    && style.height === '28px'
    && style.radius === '50%'
    && style.border === 'none'
  ))).toBe(true)
  await page.locator('.visualization-toolbar button.v1-icon-button:not(:disabled):visible').first().hover()
  await page.screenshot({ path: '../docs/acceptance/v1-buttons-circular.png', fullPage: true })
})
