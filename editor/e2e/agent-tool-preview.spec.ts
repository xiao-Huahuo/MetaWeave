/*
 * Agent tool preview browser regression.
 *
 * Usage:
 * Replays an announcement/start/end burst through the real workspace UI and
 * verifies that Agent prose stays visible while the unified read_file toolbar
 * paints its locked shimmer state before changing to the completed file summary.
 */
import { expect, test } from '@playwright/test'

interface ToolbarTransition {
  rowId: number
  text: string
  pending: boolean
  expandable: boolean
  atMs: number
}

for (const chatMode of ['tool', 'chat'] as const) {
test(`paints a locked tool preview in ${chatMode} mode before completing in place`, async ({ page }, testInfo) => {
  let sessionCreated = false
  let streamServed = false
  const pageErrors: string[] = []
  const apiRequests: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      apiRequests.push(`${request.method()} ${url.pathname}`)
    }
    if (url.pathname === '/agent/stream') {
      streamServed = true
      const events = [
        {
          node: 'agent',
          content: '我先保留这段中间输出。',
          tool_calls: [{ id: 'call_e2e_read', name: 'read_file', args: { path: 'attachment://att_e2e' } }],
          trace: [],
        },
        {
          node: 'action',
          content: '',
          tool_calls: [],
          trace: [{
            node: 'action',
            event: 'tool_call_start',
            tool_call_id: 'call_e2e_read',
            tool_name: 'read_file',
            display_name: '阅读文件',
            chat_visible: true,
          }],
        },
        {
          node: 'action',
          content: '',
          tool_calls: [],
          trace: [{
            node: 'action',
            event: 'tool_call_end',
            tool_call_id: 'call_e2e_read',
            tool_name: 'read_file',
            display_name: '阅读文件',
            raw_content: JSON.stringify({ path: 'attachment://att_e2e', filename: 'report.pdf', content: '正文' }),
            chat_visible: true,
          }],
        },
        {
          node: 'agent',
          content: '这是工具返回后的流式回答。',
          tool_calls: [],
          trace: [],
        },
      ]
      const body = `${events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')}data: [DONE]\n\n`
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body })
      return
    }
    if (url.pathname === '/health') {
      await route.fulfill({ status: 200, body: 'ok' })
      return
    }
    if (url.pathname === '/settings/models/status') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ embedding: 'ready', rerank: 'ready' }) })
      return
    }
    if (url.pathname === '/settings/profile') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user_id: 'e2e-user', knowledge_dir: 'D:/Knowledge', active_library_id: 'default', knowledge_libraries: [] }),
      })
      return
    }
    if (url.pathname === '/sessions' && request.method() === 'POST') {
      sessionCreated = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: 'e2e-session', user_id: 'e2e-user', session_name: 'preview', created_at: '', updated_at: '' }),
      })
      return
    }
    if (url.pathname === '/sessions' && request.method() === 'GET') {
      const sessions = sessionCreated
        ? [{ session_id: 'e2e-session', user_id: 'e2e-user', session_name: 'preview', created_at: '', updated_at: '' }]
        : []
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sessions) })
      return
    }
    if (url.pathname.endsWith('/messages')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (url.pathname === '/favorites') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ favorites: [] }) })
      return
    }
    if (url.pathname === '/knowledge/files') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ tree: [] }) })
      return
    }
    if (url.pathname === '/skills') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ skills: [], count: 0 }) })
      return
    }
    if (url.pathname === '/agent/children') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'e2e-session', children: [] }) })
      return
    }
    if (url.pathname === '/todo/list' || url.pathname === '/automation/list') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (url.pathname.endsWith('/changes')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ change_snapshot: null }) })
      return
    }
    if (url.pathname.endsWith('/task-list')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ task_list: null }) })
      return
    }
    if (url.pathname.endsWith('/state')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_state: null }) })
      return
    }
    if (url.pathname === '/git/status') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ initialized: false, branches: [], remote_branches: [], remotes: [], changes: [], untracked: [], ignored: [], has_changes: false }),
      })
      return
    }
    if (url.pathname === '/git/history') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ history: [], unpushed_commits: [], unpushed_files: [], upstream: '' }) })
      return
    }
    if (url.pathname === '/settings/llm/config') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ model_name: '', context_window_tokens: 128000 }) })
      return
    }
    if (url.pathname === '/settings/web-search/config') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ enabled: false }) })
      return
    }
    if (url.pathname.includes('task-suggestions')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ suggestions: [] }) })
      return
    }
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    await route.continue()
  })

  await page.addInitScript((selectedChatMode) => {
    localStorage.setItem('agent_editor_profile', JSON.stringify({
      userId: 'e2e-user',
      knowledgeDir: 'D:/Knowledge',
      activeLibraryId: 'default',
      knowledgeLibraries: [],
    }))
    localStorage.setItem('agent_editor_chat_mode', selectedChatMode)
  }, chatMode)
  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.locator('textarea[placeholder="输入消息..."]').fill('检查工具预告')

  await page.evaluate(() => {
    const transitions: ToolbarTransition[] = []
    const rowIds = new WeakMap<Element, number>()
    let nextRowId = 1
    let previousSignature = ''
    const capture = () => {
      for (const row of document.querySelectorAll('.tool-call-box')) {
        let rowId = rowIds.get(row)
        if (!rowId) {
          rowId = nextRowId
          nextRowId += 1
          rowIds.set(row, rowId)
        }
        const textElement = row.querySelector('.tool-text')
        const transition: ToolbarTransition = {
          rowId,
          text: textElement?.textContent?.trim() ?? '',
          pending: textElement?.classList.contains('pending') === true,
          expandable: row.querySelector('.tool-expand-btn') !== null,
          atMs: performance.now(),
        }
        const signature = JSON.stringify([transition.rowId, transition.text, transition.pending, transition.expandable])
        if (signature !== previousSignature) {
          transitions.push(transition)
          previousSignature = signature
        }
      }
    }
    const observer = new MutationObserver(capture)
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] })
    ;(window as typeof window & { __toolbarTransitions?: ToolbarTransition[] }).__toolbarTransitions = transitions
  })

  await page.getByRole('button', { name: '发送' }).click()
  await expect.poll(() => streamServed).toBe(true)
  await expect(page.getByText('我先保留这段中间输出。')).toBeVisible()
  await expect(page.getByText('这是工具返回后的流式回答。')).toBeVisible()
  await expect(page.locator('.tool-text.pending')).toHaveText('正在阅读文件')
  await expect(page.locator('.tool-call-box .tool-expand-btn')).toHaveCount(0)
  const categoryIcon = page.locator('.tool-static-icon .tool-category-icon')
  await expect(categoryIcon).toBeVisible()
  const categoryIconMarkup = await categoryIcon.evaluate((element) => ({
    hasGraphic: element.querySelector('path, circle, rect, polygon, polyline, line') !== null,
    hasRemoteReference: element.querySelector('image, use') !== null || /https?:/i.test(element.innerHTML),
  }))
  expect(categoryIconMarkup.hasGraphic).toBe(true)
  expect(categoryIconMarkup.hasRemoteReference).toBe(false)
  await expect(page.locator('.tool-text.pending')).toHaveClass(/thinking-shimmer-text/)
  await expect(page.locator('.thinking-flow span')).toHaveClass(/thinking-shimmer-text/)
  const shimmerStyles = await page.locator('.thinking-shimmer-text').evaluateAll((elements) => (
    elements.map((element) => {
      const style = getComputedStyle(element, '::after')
      return {
        backgroundImage: style.backgroundImage,
        animationDuration: style.animationDuration,
        animationTimingFunction: style.animationTimingFunction,
      }
    })
  ))
  expect(shimmerStyles).toHaveLength(2)
  for (const shimmerStyle of shimmerStyles) {
    expect(shimmerStyle.backgroundImage).toContain('linear-gradient')
    expect(shimmerStyle.animationDuration).toBe('1.4s')
    expect(shimmerStyle.animationTimingFunction).toBe('linear')
  }
  expect(shimmerStyles[1]).toEqual(shimmerStyles[0])
  const pendingStyle = await page.locator('.tool-text.pending').evaluate((element) => {
    const style = getComputedStyle(element)
    const shimmer = getComputedStyle(element, '::after')
    const header = element.closest('.tool-call-header')
    return {
      backgroundImage: shimmer.backgroundImage,
      flexGrow: style.flexGrow,
      textWidth: element.getBoundingClientRect().width,
      headerWidth: header?.getBoundingClientRect().width ?? 0,
    }
  })
  expect(pendingStyle.backgroundImage).toContain('linear-gradient')
  expect(pendingStyle.flexGrow).toBe('0')
  expect(pendingStyle.textWidth).toBeLessThan(pendingStyle.headerWidth / 2)
  await page.screenshot({ path: testInfo.outputPath(`${chatMode}-pending.png`), fullPage: true })
  await expect(page.locator('.tool-text')).toHaveText('阅读文件：report.pdf')
  expect(pageErrors, apiRequests.join('\n')).toEqual([])

  const transitions = await page.evaluate(() => (
    (window as typeof window & { __toolbarTransitions?: ToolbarTransition[] }).__toolbarTransitions ?? []
  ))
  const pending = transitions.find((transition) => transition.pending && transition.text === '正在阅读文件')
  const completed = transitions.find((transition) => !transition.pending && transition.text === '阅读文件：report.pdf')
  expect(pending).toBeDefined()
  expect(pending?.expandable).toBe(false)
  expect(completed).toBeDefined()
  expect(completed?.rowId).toBe(pending?.rowId)
  expect((completed?.atMs ?? 0) - (pending?.atMs ?? 0)).toBeGreaterThanOrEqual(650)
})
}
