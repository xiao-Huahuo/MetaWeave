/*
 * Cross-page UI normalization browser acceptance.
 *
 * Usage:
 * Verifies the requested circular controls and Dashboard typography against
 * deterministic responses, then saves full-page visual evidence.
 */
import { expect, test, type Page } from '@playwright/test'

async function mockUiData(page: Page): Promise<void> {
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.pathname === '/health') return route.fulfill({ status: 200, body: 'ok' })
    if (url.pathname === '/settings/models/status') return json({ embedding: 'ready', rerank: 'ready' })
    if (url.pathname === '/settings/profile') return json({
      user_id: 'ui-normalization-smoke', knowledge_dir: 'D:/Knowledge', active_library_id: 'default',
      knowledge_libraries: [{ library_id: 'default', name: '视觉验收库', knowledge_dir: 'D:/Knowledge', is_active: true }],
    })
    if (url.pathname === '/knowledge/files') return json({ tree: [] })
    if (url.pathname === '/knowledge/files/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': smoke\n\n' })
    if (url.pathname === '/favorites') return json({ favorites: [] })
    if (url.pathname === '/privacy') return json({ privacy: [] })
    if (url.pathname === '/sessions' || url.pathname === '/sessions/observability/history') return json([])
    if (url.pathname === '/library/items') return json({ items: [], parent: null, breadcrumbs: [] })
    if (url.pathname === '/library/tags') return json({ tags: [] })
    if (url.pathname === '/smart-forms/list') return json([])
    if (url.pathname === '/literature-reading/entries') return json([])
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') return json({})
    return route.continue()
  })
  await page.addInitScript(() => localStorage.setItem('agent_editor_profile', JSON.stringify({
    userId: 'ui-normalization-smoke', knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default',
    knowledgeLibraries: [{ libraryId: 'default', name: '视觉验收库', knowledgeDir: 'D:/Knowledge', isActive: true }],
  })))
}

async function expectCircular(locator: ReturnType<Page['locator']>): Promise<void> {
  const styles = await locator.evaluateAll((elements) => elements.map((element) => {
    const style = getComputedStyle(element)
    return { width: style.width, height: style.height, radius: style.borderRadius, border: style.borderStyle }
  }))
  expect(styles.length).toBeGreaterThan(0)
  expect(styles.every((style) => style.width === '28px' && style.height === '28px' && style.radius === '50%' && style.border === 'none')).toBe(true)
}

test('library, Dashboard, command search, and literature controls are visually normalized', async ({ page }) => {
  test.setTimeout(25_000)
  await mockUiData(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')

  const commandSearch = page.locator('.search-wrapper:not(.page-variant) .search-bar')
  await commandSearch.hover()
  await expect(commandSearch).toHaveCSS('border-radius', '50%')

  await page.getByRole('button', { name: '进入图书馆', exact: true }).click()
  const libraryButtons = page.locator('.library-actions button.v1-icon-button:visible')
  await expect(libraryButtons).toHaveCount(5)
  await expectCircular(libraryButtons)
  await page.screenshot({ path: '../docs/acceptance/library-v1-buttons.png', fullPage: true })

  await page.getByRole('navigation', { name: 'Editor activity bar' }).getByRole('button', { name: '主页', exact: true }).click()
  await page.getByRole('button', { name: '进入看板', exact: true }).click()
  await expect(page.locator('.dashboard-view')).toBeVisible()
  const dashboardTextSizes = await page.locator('.dashboard-view *:visible').evaluateAll((elements) => elements
    .filter((element) => !(element instanceof SVGElement) && element.children.length === 0 && (element.textContent ?? '').trim().length > 0)
    .map((element) => Number.parseFloat(getComputedStyle(element).fontSize))
    .filter(Number.isFinite))
  expect(Math.min(...dashboardTextSizes)).toBeGreaterThanOrEqual(10)
  await page.screenshot({ path: '../docs/acceptance/dashboard-readable-type.png', fullPage: true })

  await page.getByRole('navigation', { name: 'Editor activity bar' }).getByRole('button', { name: '主页', exact: true }).click()
  await page.getByRole('button', { name: '进入文献阅读', exact: true }).click()
  const literatureButtons = page.locator('.literature-toolbar .toolbar-actions button.v1-icon-button:visible')
  await expect(literatureButtons).toHaveCount(2)
  await expectCircular(literatureButtons)
  await page.screenshot({ path: '../docs/acceptance/literature-v1-buttons.png', fullPage: true })
})
