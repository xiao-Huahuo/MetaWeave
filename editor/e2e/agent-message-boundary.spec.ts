/**
 * Agent message/composer boundary browser regression.
 *
 * Usage:
 * Streams a long reply through the real Agent page and verifies at desktop,
 * tablet, and mobile sizes that the message viewport ends above the composer.
 */
import { expect, test } from '@playwright/test'

test('keeps new Agent lines above the composer', async ({ page }) => {
  const finalText = Array.from(
    { length: 40 },
    (_, index) => `第 ${index + 1} 行：这是一段用于验证输入框上沿边界的流式回复。${index === 39 ? ' [1]' : ''}`,
  ).join('\n\n')
  let sessionCreated = false

  await page.route('**/*', async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname === '/settings/profile') {
      await route.fulfill({ json: { user_id: 'e2e-user', knowledge_dir: 'D:/Knowledge', knowledge_libraries: [] } })
      return
    }
    if (pathname === '/knowledge/files/events') {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
      return
    }
    if (pathname === '/sessions' && request.method() === 'POST') {
      sessionCreated = true
      await route.fulfill({ json: { session_id: 'boundary-session', user_id: 'e2e-user', session_name: 'boundary', created_at: '', updated_at: '' } })
      return
    }
    if (pathname === '/sessions') {
      await route.fulfill({ json: sessionCreated ? [{ session_id: 'boundary-session', user_id: 'e2e-user', session_name: 'boundary', created_at: '', updated_at: '' }] : [] })
      return
    }
    const mockBodies: Record<string, unknown> = {
      '/settings/models/status': { embedding: 'ready', rerank: 'ready', paddleocr: 'ready' },
      '/settings/models/management': { models: [] },
      '/privacy': { privacy: [] },
      '/favorites': { favorites: [] },
      '/skills': { skills: [], count: 0 },
      '/agent/children': { session_id: 'boundary-session', children: [] },
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
    if (pathname.endsWith('/messages') || pathname.endsWith('/changes') || pathname.endsWith('/task-list') || pathname.endsWith('/state') || pathname.includes('task-suggestions')) {
      const body = pathname.endsWith('/messages') ? [] : pathname.endsWith('/changes') ? { change_snapshot: null } : pathname.endsWith('/task-list') ? { task_list: null } : pathname.endsWith('/state') ? { session_state: null } : { suggestions: [] }
      await route.fulfill({ json: body })
      return
    }
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      await route.fulfill({ json: {} })
      return
    }
    await route.continue()
  })

  await page.addInitScript(({ streamedText }) => {
    const nativeFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const requestUrl = input instanceof Request ? input.url : String(input)
      if (new URL(requestUrl, window.location.href).pathname !== '/agent/stream') {
        return nativeFetch(input, init)
      }
      const encoder = new TextEncoder()
      const event = {
        type: 'delta',
        node: 'agent',
        content: streamedText,
        tool_calls: [],
        trace: [],
        metadata: {
          used_citations: ['1'],
          citation_map: {
            1: { source_uri: 'file:///D:/Knowledge/source.md', title: '验收来源', content: '完成态来源摘要' },
          },
        },
      }
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
          ;(window as typeof window & { finishAgentStream?: () => void }).finishAgentStream = () => {
            controller.enqueue(encoder.encode('data: [DONE]\n\n'))
            controller.close()
          }
        },
      })
      return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    }
    localStorage.setItem('agent_editor_profile', JSON.stringify({
      userId: 'e2e-user',
      knowledgeDir: 'D:/Knowledge',
      knowledgeLibraries: [],
    }))
  }, { streamedText: finalText })
  for (const viewport of [
    { name: 'desktop', width: 1280, height: 720 },
    { name: 'tablet', width: 768, height: 900 },
    { name: 'mobile', width: 480, height: 900 },
  ]) {
    await page.setViewportSize(viewport)
    await page.goto('/')
    await page.getByRole('button', { name: 'Agent', exact: true }).click()
    await page.getByPlaceholder('输入消息...').fill('验证新行位置')
    await page.getByTitle('发送').click()
    await expect(page.getByTitle('中断输出')).toBeVisible()
    const finalReply = page.locator('.markdown-body').last()
    await expect(finalReply).toContainText('第 40 行')
    const messageList = page.locator('.message-list')
    const composer = page.locator('.chat-input-wrap:not(.centered)')
    const finalLine = finalReply.locator('p').last()
    await expect(composer).toBeVisible()
    await expect.poll(async () => {
      const [composerBounds, finalLineBounds] = await Promise.all([
        composer.boundingBox(),
        finalLine.boundingBox(),
      ])
      return finalLineBounds!.y + finalLineBounds!.height - composerBounds!.y
    }).toBeLessThanOrEqual(1)
    await expect.poll(() => messageList.evaluate(
      (element) => element.scrollHeight - element.scrollTop - element.clientHeight,
    )).toBeLessThanOrEqual(24)
    const streamingScrollTop = await messageList.evaluate((element) => element.scrollTop)
    await page.evaluate(() => {
      ;(window as typeof window & { finishAgentStream?: () => void }).finishAgentStream?.()
    })
    await expect(page.getByTitle('中断输出')).toBeHidden()
    await expect.poll(async () => {
      const [composerBounds, finalLineBounds] = await Promise.all([
        composer.boundingBox(),
        finalLine.boundingBox(),
      ])
      return finalLineBounds!.y + finalLineBounds!.height - composerBounds!.y
    }).toBeLessThanOrEqual(1)
    await expect.poll(() => messageList.evaluate(
      (element) => element.scrollHeight - element.scrollTop - element.clientHeight,
    )).toBeLessThanOrEqual(24)
    expect(await messageList.evaluate((element) => element.scrollTop)).toBeGreaterThanOrEqual(streamingScrollTop)
    const [messageBounds, composerBounds, finalLineBounds] = await Promise.all([
      messageList.boundingBox(),
      composer.boundingBox(),
      finalLine.boundingBox(),
    ])
    expect(messageBounds).not.toBeNull()
    expect(composerBounds).not.toBeNull()
    expect(finalLineBounds).not.toBeNull()
    expect(messageBounds!.y + messageBounds!.height).toBeLessThanOrEqual(composerBounds!.y + 1)
    expect(finalLineBounds!.y + finalLineBounds!.height).toBeLessThanOrEqual(composerBounds!.y + 1)
    expect(finalLineBounds!.y + finalLineBounds!.height).toBeGreaterThan(messageBounds!.y)
    await page.screenshot({
      path: `../docs/acceptance/agent-message-boundary-${viewport.name}.png`,
      fullPage: false,
    })
  }

  const messageList = page.locator('.message-list')
  await page.getByPlaceholder('输入消息...').fill('验证主动上滚')
  await page.getByTitle('发送').click()
  await expect(page.getByTitle('中断输出')).toBeVisible()
  await expect(page.locator('.markdown-body').last()).toContainText('第 40 行')
  await expect.poll(() => messageList.evaluate(
    (element) => element.scrollHeight - element.scrollTop - element.clientHeight,
  )).toBeLessThanOrEqual(24)
  await messageList.evaluate((element) => {
    element.scrollTop = Math.max(0, element.scrollTop - 300)
    element.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: -300 }))
  })
  await page.waitForTimeout(50)
  expect(await messageList.evaluate(
    (element) => element.scrollHeight - element.scrollTop - element.clientHeight,
  )).toBeGreaterThan(24)
  await page.evaluate(() => {
    ;(window as typeof window & { finishAgentStream?: () => void }).finishAgentStream?.()
  })
  await expect(page.getByTitle('中断输出')).toBeHidden()
  await page.waitForTimeout(150)
  expect(await messageList.evaluate(
    (element) => element.scrollHeight - element.scrollTop - element.clientHeight,
  )).toBeGreaterThan(24)
})
