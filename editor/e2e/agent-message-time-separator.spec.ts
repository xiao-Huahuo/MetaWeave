/**
 * Agent 历史消息时间分隔浏览器回归。
 *
 * 用途：在真实 Agent 页面加载同一组持久化历史两次，验证 30 分钟分隔、
 * 完整年月日时分和旧气泡角落时间均符合界面约定。
 */
import { expect, test } from '@playwright/test'

const session = {
  session_id: 'time-separator-session',
  user_id: 'e2e-user',
  session_name: '时间分隔验收',
  created_at: '2026-08-30T08:01:00',
  updated_at: '2026-08-30T09:01:00',
}

const messages = [
  { message_id: 'm1', session_id: session.session_id, role: 'user', content: '第一条', created_at: '2026-08-30T08:01:00', metadata: {} },
  { message_id: 'm2', session_id: session.session_id, role: 'assistant', content: '相隔不足三十分钟', created_at: '2026-08-30T08:30:59', metadata: { node: 'agent' } },
  { message_id: 'm3', session_id: session.session_id, role: 'user', content: '正好相隔三十分钟', created_at: '2026-08-30T09:00:59', metadata: {} },
  { message_id: 'm4', session_id: session.session_id, role: 'assistant', content: '同一时间段内', created_at: '2026-08-30T09:01:00', metadata: { node: 'agent' } },
]

test('restores sparse full-date separators with persisted history', async ({ page }) => {
  await page.route('**/*', async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname === '/settings/profile') {
      await route.fulfill({ json: { user_id: 'e2e-user', knowledge_dir: 'D:/Knowledge', knowledge_libraries: [] } })
      return
    }
    if (pathname === '/sessions') {
      await route.fulfill({ json: [session] })
      return
    }
    if (pathname === `/sessions/${session.session_id}/messages`) {
      await route.fulfill({ json: messages })
      return
    }
    if (pathname === '/knowledge/files/events') {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
      return
    }
    const mockBodies: Record<string, unknown> = {
      '/settings/models/status': { embedding: 'ready', rerank: 'ready', paddleocr: 'ready' },
      '/settings/models/management': { models: [] },
      '/privacy': { privacy: [] },
      '/favorites': { favorites: [] },
      '/skills': { skills: [], count: 0 },
      '/agent/children': { session_id: session.session_id, children: [] },
      '/knowledge/files': { tree: [] },
      '/todo/list': [],
      '/automation/list': [],
      '/settings/llm/config': { model_name: '', context_window_tokens: 128000 },
      '/settings/web-search/config': { enabled: false },
    }
    if (pathname in mockBodies) {
      await route.fulfill({ json: mockBodies[pathname] })
      return
    }
    if (pathname.endsWith('/changes') || pathname.endsWith('/task-list') || pathname.endsWith('/state') || pathname.includes('task-suggestions')) {
      const body = pathname.endsWith('/changes') ? { change_snapshot: null } : pathname.endsWith('/task-list') ? { task_list: null } : pathname.endsWith('/state') ? { session_state: null } : { suggestions: [] }
      await route.fulfill({ json: body })
      return
    }
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      await route.fulfill({ json: {} })
      return
    }
    await route.continue()
  })
  await page.addInitScript(() => {
    localStorage.setItem('agent_editor_theme_mode', 'light')
    localStorage.setItem('agent_editor_chat_mode', 'chat')
    localStorage.setItem('agent_editor_profile', JSON.stringify({
      userId: 'e2e-user',
      knowledgeDir: 'D:/Knowledge',
      knowledgeLibraries: [],
    }))
  })

  async function openHistory() {
    await page.getByRole('button', { name: 'Agent', exact: true }).click()
    await page.getByTitle('Toggle sidebar').click()
    await page.getByText(session.session_name, { exact: true }).click()
    await expect(page.locator('.message-time-separator')).toHaveText([
      '2026年08月30日 08:01',
      '2026年08月30日 09:00',
    ])
    await expect(page.locator('.message-time')).toHaveCount(0)
  }

  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/')
  await openHistory()
  await page.screenshot({ path: '../docs/acceptance/agent-message-time-separator.png', fullPage: false })

  await page.reload()
  await openHistory()
})
