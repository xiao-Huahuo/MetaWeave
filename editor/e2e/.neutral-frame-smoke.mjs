import { chromium } from 'playwright'

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 920 } })
const outputRoot = 'runtime/test-results/neutral-frame'

await page.addInitScript(() => localStorage.setItem('agent_editor_profile', JSON.stringify({
  userId: 'neutral-frame-smoke',
  knowledgeDir: 'D:/Knowledge',
  activeLibraryId: 'default',
  knowledgeLibraries: [{ libraryId: 'default', name: '视觉验收库', knowledgeDir: 'D:/Knowledge', isActive: true }],
})))
await page.route('**/*', async (route) => {
  const request = route.request()
  const pathname = new URL(request.url()).pathname
  const bodies = {
    '/settings/profile': { user_id: 'neutral-frame-smoke', knowledge_dir: 'D:/Knowledge', active_library_id: 'default', knowledge_libraries: [{ library_id: 'default', name: '视觉验收库', knowledge_dir: 'D:/Knowledge', is_active: true }] },
    '/settings/models/status': { embedding: 'ready', rerank: 'ready', paddleocr: 'ready', local_qwen: 'ready' },
    '/settings/models/management': { models: [] }, '/settings/llm/config': { model_name: 'deepseek-flash', context_window_tokens: 128000 },
    '/settings/web-search/config': { enabled: false }, '/privacy': { privacy: [] }, '/favorites': { favorites: [] },
    '/skills': { skills: [], count: 0 }, '/agent/children': { session_id: '', children: [] }, '/knowledge/files': { tree: [] },
    '/sessions': [], '/sessions/observability/history': [], '/todo/list': [], '/automation/list': [],
    '/library/items': { items: [], parent: null, breadcrumbs: [] }, '/library/tags': { tags: [] },
    '/component-library/components': { components: [], tags: [] }, '/knowledge/ingestion/jobs': { jobs: [] },
    '/knowledge/graph/rebuild/status': { status: 'idle', documents: [] },
  }
  if (pathname === '/knowledge/files/events') await route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': smoke\n\n' })
  else if (pathname in bodies) await route.fulfill({ json: bodies[pathname] })
  else if (pathname.endsWith('/messages')) await route.fulfill({ json: [] })
  else if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') await route.fulfill({ json: {} })
  else await route.continue()
})

async function frameStyle(selector) {
  const locator = page.locator(selector).first()
  await locator.waitFor({ state: 'visible' })
  return locator.evaluate((element) => ({
    outlineWidth: getComputedStyle(element).outlineWidth,
    outlineOffset: getComputedStyle(element).outlineOffset,
    boxShadow: getComputedStyle(element).boxShadow,
  }))
}

for (const viewport of [{ name: 'desktop', width: 1440, height: 920 }, { name: 'tablet', width: 768, height: 900 }, { name: 'mobile', width: 480, height: 900 }]) {
  await page.setViewportSize(viewport)
  await page.goto('http://127.0.0.1:5173')
  await page.waitForLoadState('networkidle')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'))
  console.log(viewport.name, await frameStyle('.main-shell.ide-panel'))
  await page.screenshot({ path: `${outputRoot}/agent-${viewport.name}.png`, fullPage: false })
}

await page.setViewportSize({ width: 1440, height: 920 })
await page.getByRole('navigation', { name: 'Editor activity bar' }).getByRole('button', { name: '主页', exact: true }).click()
await page.getByRole('button', { name: '进入看板', exact: true }).click()
console.log('dashboard', await frameStyle('.dashboard-card-surface'))
await page.screenshot({ path: `${outputRoot}/dashboard-desktop.png`, fullPage: false })

await page.getByRole('navigation', { name: 'Editor activity bar' }).getByRole('button', { name: '库', exact: true }).click()
await page.getByRole('button', { name: '组件库', exact: true }).click()
console.log('component-library', await frameStyle('.tag-sidebar'))
await page.screenshot({ path: `${outputRoot}/component-library-desktop.png`, fullPage: false })

await page.getByRole('navigation', { name: 'Editor activity bar' }).getByRole('button', { name: '入库进度', exact: true }).click()
console.log('ingestion', await frameStyle('.file-table'))
await page.screenshot({ path: `${outputRoot}/ingestion-desktop.png`, fullPage: false })

await browser.close()
