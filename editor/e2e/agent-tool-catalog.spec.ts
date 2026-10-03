/** Browser verification of Agent labels and Debug against the real catalog/settings REST. */
import { expect, test } from '@playwright/test'

test('shows recent native tools and the live registry without retired tool entries', async ({ page, request }, testInfo) => {
  const fixture = await (await request.get('/knowledge/tool-catalog-smoke/fixture')).json()
  const catalog = await (await request.get('/agent/tools')).json()
  const names = catalog.tools.map((tool: { name: string }) => tool.name)
  expect(names).toContain('get_knowledge_url')
  expect(names).toContain('request_user_input')
  expect(names).toContain('read_tool_result')
  expect(names).toContain('continue_child_agent')
  expect(names).not.toContain('get_knowledge_file_url')
  const newNames = ['read_tool_result', 'understand_image', 'request_user_input', 'continue_child_agent']
  await page.route('**/*', async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    // Catalog, categories and toggle persistence come from actual production routes/services.
    if (url.pathname === '/agent/tools' || url.pathname.startsWith('/settings/tools/')) {
      await route.continue()
      return
    }
    let body: unknown
    if (url.pathname === '/settings/profile') body = {
      user_id: fixture.user_id, knowledge_dir: fixture.knowledge_dir, active_library_id: fixture.library_id,
      knowledge_libraries: [{ library_id: fixture.library_id, knowledge_dir: fixture.knowledge_dir, name: '工具目录验收库', is_active: true }],
    }
    else if (url.pathname === '/knowledge/files') body = { tree: [] }
    else if (url.pathname === '/settings/models/management') body = { models: [] }
    else if (url.pathname === '/settings/models/status') body = { embedding: 'ready', rerank: 'ready' }
    else if (url.pathname === '/agent/children') body = { children: [] }
    else if (url.pathname === '/sessions') body = req.method() === 'POST'
      ? { session_id: 'tool-catalog-ui', user_id: fixture.user_id, session_name: '工具目录验收', created_at: '', updated_at: '' } : []
    else if (url.pathname.endsWith('/messages')) body = []
    else if (url.pathname === '/favorites') body = { favorites: [] }
    else if (url.pathname === '/privacy') body = { privacy: [] }
    else if (url.pathname === '/todo/list' || url.pathname === '/automation/list') body = []
    else if (url.pathname === '/agent/task-suggestions') body = { suggestions: [] }
    else if (url.pathname === '/agent/stream') {
      const traces = newNames.map((name, index) => ({
        event: 'tool_call_end', tool_name: name, tool_call_id: `catalog-${index}`,
        human_readable: '工具显示验收', raw_content: '完成',
      }))
      const events = [
        { node: 'action', content: '', trace: traces, tool_calls: [], metadata: {} },
        { node: 'agent', content: '工具条显示验收完成。', trace: [], tool_calls: [], metadata: {} },
      ]
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') + 'data: [DONE]\n\n' })
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
      knowledgeLibraries: [{ libraryId: fixture.library_id, name: '工具目录验收库', knowledgeDir: fixture.knowledge_dir, isActive: true }],
    }))
  }, fixture)
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.getByPlaceholder('输入消息...').fill('检查工具条')
  await page.getByRole('button', { name: '发送' }).click()
  for (const label of ['继续读取工具结果', '识图', '询问用户', '继续 DSH 子 Agent']) {
    await expect(page.locator('.tool-call-list')).toContainText(label)
  }
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('agent-current-tools.png') })
  await page.getByRole('button', { name: 'Debug', exact: true }).click()
  await page.getByRole('button', { name: '工具注册表', exact: true }).click()
  const panel = page.locator('.tool-registry-panel')
  await expect(panel.locator('.title-summary')).toContainText(`${catalog.tool_count} tools`)
  for (const name of ['get_knowledge_url', ...newNames]) {
    await panel.getByPlaceholder('搜索工具').fill(name)
    const title = catalog.tools.find((tool: { name: string; display_name: string }) => tool.name === name).display_name
    const row = panel.locator('.tool-list-item').filter({ has: page.getByText(title, { exact: true }) })
    await expect(row).toHaveCount(1)
    await row.getByRole('button').click()
    await expect(panel).toContainText(name)
  }
  await page.screenshot({ path: testInfo.outputPath('debug-current-tools.png') })
  await panel.getByPlaceholder('搜索工具').fill('get_knowledge_file_url')
  await expect(panel.locator('.tool-list-item')).toHaveCount(0)
  await panel.getByPlaceholder('搜索工具').fill('get_knowledge_url')
  const urlTool = panel.locator('.tool-list-item').filter({ has: page.getByText('获取知识URL', { exact: true }) })
  await urlTool.locator('.tool-toggle-label').click()
  await expect.poll(async () => (await (await request.get(`/settings/tools/disabled?user_id=${fixture.user_id}`)).json()).disabled_tools).toContain('get_knowledge_url')
  await panel.getByTitle('刷新', { exact: true }).click()
  await expect(urlTool.locator('input')).not.toBeChecked()
  await urlTool.locator('.tool-toggle-label').click()
  await expect.poll(async () => (await (await request.get(`/settings/tools/disabled?user_id=${fixture.user_id}`)).json()).disabled_tools).not.toContain('get_knowledge_url')
})
