/*
 * Agent buffered-stream responsiveness smoke test.
 *
 * Replays a tool call followed by a large SSE burst through the real Agent page
 * and verifies that timers, controls, incremental text, and the directional
 * word-reveal schedule keep updating.
 */
import { expect, test } from '@playwright/test'

test('keeps the Agent page interactive while draining buffered tool output', async ({ page }) => {
  const finalText = Array.from({ length: 24 }, (_, index) => `词${index + 1}`).join(' ')
  let sessionCreated = false
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/agent/stream') {
      const toolEvents = [
        {
          node: 'action', content: '', tool_calls: [],
          trace: [{ node: 'action', event: 'tool_call_start', tool_call_id: 'slow-tool', tool_name: 'get_current_time', display_name: '获取当前时间', chat_visible: true }],
        },
        {
          node: 'action', content: '', tool_calls: [],
          trace: [{ node: 'action', event: 'tool_call_end', tool_call_id: 'slow-tool', tool_name: 'get_current_time', display_name: '获取当前时间', raw_content: '2026-08-30T00:00:00+08:00', chat_visible: true }],
        },
      ]
      const deltas = [...finalText].map((content) => ({ type: 'delta', node: 'agent', content, tool_calls: [], trace: [] }))
      const body = `${[...toolEvents, ...deltas].map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')}data: [DONE]\n\n`
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body })
      return
    }
    if (url.pathname === '/settings/profile') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user_id: 'e2e-user', knowledge_dir: 'D:/Knowledge', active_library_id: 'default', knowledge_libraries: [] }) })
      return
    }
    if (url.pathname === '/sessions' && request.method() === 'POST') {
      sessionCreated = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'responsive-session', user_id: 'e2e-user', session_name: 'responsive', created_at: '', updated_at: '' }) })
      return
    }
    if (url.pathname === '/sessions' && request.method() === 'GET') {
      const sessions = sessionCreated ? [{ session_id: 'responsive-session', user_id: 'e2e-user', session_name: 'responsive', created_at: '', updated_at: '' }] : []
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sessions) })
      return
    }
    const mockBodies: Record<string, unknown> = {
      '/settings/models/status': { embedding: 'ready', rerank: 'ready', paddleocr: 'ready' },
      '/settings/models/management': { models: [] },
      '/privacy': { privacy: [] },
      '/favorites': { favorites: [] },
      '/skills': { skills: [], count: 0 },
      '/agent/children': { session_id: 'responsive-session', children: [] },
      '/knowledge/files': { tree: [] },
      '/todo/list': [],
      '/automation/list': [],
      '/settings/llm/config': { model_name: '', context_window_tokens: 128000 },
      '/settings/web-search/config': { enabled: false },
      '/git/status': { initialized: false, branches: [], remote_branches: [], remotes: [], changes: [], untracked: [], ignored: [], has_changes: false },
      '/git/history': { history: [], unpushed_commits: [], unpushed_files: [], upstream: '' },
    }
    if (url.pathname in mockBodies) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockBodies[url.pathname]) })
      return
    }
    if (url.pathname.endsWith('/messages') || url.pathname.endsWith('/changes') || url.pathname.endsWith('/task-list') || url.pathname.endsWith('/state') || url.pathname.includes('task-suggestions')) {
      const body = url.pathname.endsWith('/messages') ? [] : url.pathname.endsWith('/changes') ? { change_snapshot: null } : url.pathname.endsWith('/task-list') ? { task_list: null } : url.pathname.endsWith('/state') ? { session_state: null } : { suggestions: [] }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
      return
    }
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    await route.continue()
  })

  await page.addInitScript(() => {
    localStorage.setItem('agent_editor_profile', JSON.stringify({ userId: 'e2e-user', knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default', knowledgeLibraries: [] }))
    ;(window as typeof window & { __streamTimerTicks?: number }).__streamTimerTicks = 0
    window.setInterval(() => {
      const target = window as typeof window & { __streamTimerTicks?: number }
      target.__streamTimerTicks = (target.__streamTimerTicks ?? 0) + 1
    }, 20)
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.locator('textarea[placeholder="输入消息..."]').fill('检查竞态')
  await page.evaluate(() => {
    const lengths: number[] = []
    const revealSchedules: Array<{ delays: number[]; animationNames: string[] }> = []
    const observer = new MutationObserver(() => {
      const replies = document.querySelectorAll('.markdown-body')
      const reply = replies[replies.length - 1]
      const length = reply?.textContent?.length ?? 0
      if (length > 0 && lengths[lengths.length - 1] !== length) lengths.push(length)
      const revealWords = Array.from(reply?.querySelectorAll<HTMLElement>('.stream-reveal-word') ?? [])
      if (revealWords.length > 0) {
        revealSchedules.push({
          delays: revealWords.map((word) => Number.parseFloat(getComputedStyle(word).animationDelay) * 1_000),
          animationNames: revealWords.map((word) => getComputedStyle(word).animationName),
        })
      }
    })
    observer.observe(document.body, { childList: true, characterData: true, subtree: true })
    const diagnostics = window as typeof window & {
      __streamReplyLengths?: number[]
      __streamRevealSchedules?: Array<{ delays: number[]; animationNames: string[] }>
    }
    diagnostics.__streamReplyLengths = lengths
    diagnostics.__streamRevealSchedules = revealSchedules
  })
  await page.getByTitle('发送').click()
  await expect(page.getByTitle('中断输出')).toBeVisible()

  await page.getByTitle('Toggle sidebar').click()
  await expect(page.locator('.session-drawer')).toHaveClass(/open/)
  const finalReply = page.locator('.markdown-body').last()
  await page.waitForTimeout(120)
  expect(await page.evaluate(() => (window as typeof window & { __streamTimerTicks?: number }).__streamTimerTicks ?? 0)).toBeGreaterThan(0)
  await expect(page.getByTitle('中断输出')).toBeVisible()

  await expect(finalReply).toHaveText(finalText)
  await expect(page.locator('.tool-text')).toHaveText('获取当前时间：2026-08-30 00:00')
  const replyLengths = await page.evaluate(() => (window as typeof window & { __streamReplyLengths?: number[] }).__streamReplyLengths ?? [])
  expect(replyLengths.some((length) => length > 0 && length < finalText.length)).toBe(true)
  expect(replyLengths.some((length) => length >= finalText.length)).toBe(true)
  const revealSchedules = await page.evaluate(() => (
    (window as typeof window & {
      __streamRevealSchedules?: Array<{ delays: number[]; animationNames: string[] }>
    }).__streamRevealSchedules ?? []
  ))
  const widestSchedule = revealSchedules.sort((left, right) => right.delays.length - left.delays.length)[0]
  expect(widestSchedule?.delays.length).toBe(24)
  expect(widestSchedule?.delays[0]).toBe(0)
  expect(widestSchedule?.delays[23]).toBe(90)
  expect(widestSchedule?.delays).toEqual([...(widestSchedule?.delays ?? [])].sort((left, right) => left - right))
  expect(widestSchedule?.animationNames.every((name) => name !== 'none')).toBe(true)
  expect(pageErrors).toEqual([])
})
