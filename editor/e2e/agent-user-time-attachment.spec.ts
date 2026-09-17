/**
 * Agent user-message time and attachment history browser regression.
 *
 * Usage:
 * Loads one persisted user message through the real Agent page, then verifies
 * its attachment and local-time label remain visible at desktop, tablet, and
 * narrow mobile widths without horizontal clipping.
 */
import { expect, test } from '@playwright/test'

test('restores user time and attachments responsively', async ({ page }) => {
  let messageRequests = 0
  const attachment = {
    attachment_id: 'att-history', user_id: 'e2e-user', session_id: 'session-history',
    library_id: 'default', library_name: '默认知识库', filename: '历史报告.pdf', stored_name: '历史报告.pdf',
    uri: 'session-upload://e2e-user/default/session-history/历史报告.pdf', mime_type: 'application/pdf',
    size: 42, source_type: 'document', created_at: '2026-08-30T08:00:00Z',
  }
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/settings/profile') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        user_id: 'e2e-user', knowledge_dir: 'D:/Knowledge', active_library_id: 'default', knowledge_libraries: [],
      }) })
      return
    }
    if (url.pathname === '/settings/llm/config') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        model_name: 'Test Model', effective_model_name: 'Test Model', effective_model_source: 'remote', context_window_tokens: 32768,
      }) })
      return
    }
    if (url.pathname === '/sessions') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{
        session_id: 'session-history', user_id: 'e2e-user', session_name: '时间附件验收',
        created_at: '2026-08-30T08:00:00Z', updated_at: '2026-08-30T08:01:00Z',
      }]) })
      return
    }
    if (url.pathname.replace(/\/$/, '') === '/sessions/session-history/messages') {
      messageRequests += 1
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{
        message_id: 'message-history', session_id: 'session-history', role: 'user', content: '请分析历史附件',
        metadata: { attachments: [attachment] }, created_at: '2026-08-30T08:01:00Z', tool_calls: [],
      }]) })
      return
    }
    if (url.pathname === '/health') {
      await route.fulfill({ status: 200, body: 'ok' })
      return
    }
    if (url.pathname === '/knowledge/files/events') {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
      return
    }
    if (url.pathname === '/todo/list' || url.pathname === '/automation/list') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (url.pathname === '/favorites') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"favorites":[]}' })
      return
    }
    if (url.pathname === '/privacy') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"privacy":[]}' })
      return
    }
    if (url.pathname === '/knowledge/files') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"tree":[]}' })
      return
    }
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    await route.continue()
  })
  await page.addInitScript(() => {
    localStorage.setItem('agent_editor_profile', JSON.stringify({
      userId: 'e2e-user', knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default', knowledgeLibraries: [],
    }))
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.getByTitle('Toggle sidebar').click({ force: true, timeout: 5000 })
  await page.locator('.session-item').filter({ hasText: '时间附件验收' }).click()
  await expect.poll(() => messageRequests).toBeGreaterThan(0)

  const row = page.locator('.bubble-row.user')
  const timestamp = row.locator('.message-time')
  const attachmentName = row.locator('.attachment-name')
  await expect(timestamp).toBeVisible()
  await expect(attachmentName).toHaveText('历史报告.pdf')
  await page.getByTitle('收起侧边栏').click({ timeout: 5000 })

  for (const viewport of [
    { name: 'desktop', width: 1280, height: 800 },
    { name: 'tablet', width: 820, height: 900 },
    { name: 'mobile', width: 390, height: 844 },
    { name: 'narrow', width: 320, height: 700 },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await expect(timestamp).toBeVisible()
    await expect(attachmentName).toBeVisible()
    const positions = await row.evaluate((element) => {
      const time = element.querySelector('.message-time')?.getBoundingClientRect()
      const column = element.querySelector('.bubble-col')?.getBoundingClientRect()
      return { timeRight: time?.right ?? 0, columnLeft: column?.left ?? 0 }
    })
    expect(positions.timeRight).toBeLessThanOrEqual(positions.columnLeft)
    const messageListOverflow = await page.locator('.message-list').evaluate(
      (element) => element.scrollWidth - element.clientWidth,
    )
    expect(messageListOverflow).toBeLessThanOrEqual(1)
    if (process.env.METAWEAVE_ACCEPTANCE_SCREENSHOTS === '1') {
      await page.screenshot({ path: `test-results/agent-user-time-${viewport.name}.png`, fullPage: true })
    }
  }
})
