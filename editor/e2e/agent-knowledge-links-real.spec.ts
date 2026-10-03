/** Browser smoke through Vite's proxy and formal services seeded in a temporary SQLite library.
 * Run alongside tests.knowledge_url_smoke_server on the configured Vite proxy target.
 * Only chat transport/profile scaffolding is controlled; knowledge data/URLs are real REST.
 */
import { expect, test } from '@playwright/test'
import type { UnifiedSearchResult } from '../src/types/unifiedSearch'

interface KnowledgeFixture {
  user_id: string
  library_id: string
  knowledge_dir: string
  citation_map: Record<string, { source_uri: string; content: string; search_result: UnifiedSearchResult }>
  links: Record<'files' | 'book' | 'collection' | 'components' | 'literature', { url: string; result: UnifiedSearchResult }>
}

test('real knowledge URLs mount selected native blocks and keep citations separate', async ({ page, request }, testInfo) => {
  const fixtureResponse = await request.get('/knowledge/url-smoke/fixture')
  expect(fixtureResponse.ok()).toBe(true)
  const fixture: KnowledgeFixture = await fixtureResponse.json()
  for (const link of Object.values(fixture.links)) {
    const response = await request.get(link.url)
    expect(response.ok()).toBe(true)
    if (link.result.source !== 'files') expect((await response.json()).item).toEqual(link.result.item)
  }
  const citationMap = fixture.citation_map
  const errors: string[] = []
  page.on('pageerror', (error) => {
    errors.push(error.message)
    void testInfo.attach('page-error', { body: error.stack ?? error.message, contentType: 'text/plain' })
  })
  let replies = 0
  await page.route('**/*', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    // All file/resolve/search operations reach production REST through the actual dev proxy.
    if (['/knowledge', '/library', '/component-library', '/smart-forms', '/literature-reading'].some((prefix) => url.pathname.startsWith(prefix)) || url.pathname === '/search') {
      await route.continue()
      return
    }
    let body: unknown
    if (url.pathname === '/settings/profile') body = {
      user_id: fixture.user_id, knowledge_dir: fixture.knowledge_dir, active_library_id: fixture.library_id,
      knowledge_libraries: [{ library_id: fixture.library_id, knowledge_dir: fixture.knowledge_dir, name: '知识链接验收库', is_active: true }],
    }
    else if (url.pathname === '/settings/models/status') body = { embedding: 'ready', rerank: 'ready' }
    else if (url.pathname === '/settings/models/management') body = { models: [] }
    else if (url.pathname === '/agent/children') body = { children: [] }
    else if (url.pathname === '/sessions') body = req.method() === 'POST'
      ? { session_id: 'knowledge-links-ui', user_id: fixture.user_id, session_name: '知识链接验收', created_at: '', updated_at: '' }
      : []
    else if (url.pathname.endsWith('/messages')) body = []
    else if (url.pathname === '/favorites') body = { favorites: [] }
    else if (url.pathname === '/privacy') body = { privacy: [] }
    else if (url.pathname === '/agent/task-suggestions') body = { suggestions: [] }
    else if (url.pathname === '/agent/stream') {
      replies += 1
      const content = replies === 1 ? `搜索找到资料，使用编号引用 ${Object.keys(citationMap).map((id) => `[${id}]`).join(' ')}。`
        : '下面单独展示选定知识。\n\n' + Object.values(fixture.links).map(({ url, result }) => `[${result.title}](${url})`).join('\n\n')
      const event = { node: 'agent', content, tool_calls: [], trace: [], metadata: { citation_map: citationMap, used_citations: Object.keys(citationMap) } }
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: `data: ${JSON.stringify(event)}\n\ndata: [DONE]\n\n` })
      return
    }
    else if (req.resourceType() === 'fetch' || req.resourceType() === 'xhr') body = {}
    if (body !== undefined) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
      return
    }
    await route.continue()
  })
  await page.addInitScript((fixture) => {
    if (window.top !== window) return
    localStorage.setItem('agent_editor_profile', JSON.stringify({
      userId: fixture.user_id, knowledgeDir: fixture.knowledge_dir, activeLibraryId: fixture.library_id,
      knowledgeLibraries: [{ libraryId: fixture.library_id, name: '知识链接验收库', knowledgeDir: fixture.knowledge_dir, isActive: true }],
    }))
  }, fixture)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.getByPlaceholder('输入消息...').fill('仅搜索并引用来源')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.locator('.markdown-body').last()).toContainText('搜索找到资料')
  await expect(page.locator('.agent-knowledge-block, .agent-mounted-file, .agent-search-result-section')).toHaveCount(0)
  await page.getByPlaceholder('输入消息...').fill('单独挂载这几个知识形态')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.locator('.agent-knowledge-block')).toHaveCount(4)
  await expect(page.locator('.agent-mounted-file')).toHaveCount(1)
  await expect(page.locator('.agent-knowledge-block .library-card')).toHaveCount(2)
  await expect(page.locator('.agent-knowledge-block .component-card')).toHaveCount(1)
  await expect(page.locator('.agent-knowledge-block .literature-card')).toHaveCount(1)
  await expect(page.locator('.agent-search-result-section')).toHaveCount(0)
  const cover = page.locator('.agent-knowledge-block .library-card .cover-image')
  await expect(cover).toHaveCount(1)
  await expect.poll(() => cover.evaluate((image) => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  // The native cover retains its own image sizing, rather than Markdown image styles.
  await expect(cover).toHaveCSS('max-height', '520px')
  await expect(cover).toHaveCSS('border-radius', '0px')

  for (const width of [1024, 768, 480, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    for (const block of await page.locator('.agent-knowledge-block, .agent-mounted-file').all()) {
      await block.scrollIntoViewIfNeeded()
      const box = await block.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1)
      expect(await block.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
    }
    await page.screenshot({ path: testInfo.outputPath(`real-knowledge-${width}.png`) })
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  for (const [index, block] of (await page.locator('.agent-mounted-file, .agent-knowledge-block').all()).entries()) {
    await block.screenshot({ path: testInfo.outputPath(`real-block-${index}.png`) })
  }
  // Cover clicks are owned by the native card and must not open Markdown's image gallery.
  await cover.click()
  await expect(page.locator('.search-result-sidebar[data-source="library"]')).toBeVisible()
  await page.getByRole('button', { name: '关闭编辑区侧边栏' }).click()
  await page.locator('.agent-knowledge-block .component-card .detail-button').click()
  await expect(page.locator('.search-result-sidebar[data-source="components"]')).toBeVisible()
  await page.getByRole('button', { name: '关闭编辑区侧边栏' }).click()
  await page.locator('.agent-knowledge-block .literature-card').click()
  await expect(page.locator('.search-result-sidebar[data-source="literature"]')).toBeVisible()
  await page.getByRole('button', { name: '关闭编辑区侧边栏' }).click()
  await page.locator('.agent-mounted-file').click()
  await expect(page.locator('.editor-sidebar-content')).toHaveAttribute('aria-hidden', 'false')
  await expect(page.locator('.agent-page-mode')).toBeVisible()
  expect(errors).toEqual([])
})
