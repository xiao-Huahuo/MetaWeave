/**
 * Agent parallel attachment upload browser regression.
 *
 * Drops two files together, holds each mocked upload until both requests have
 * started, and verifies uploaded/unparsed attachments do not enter a polling or
 * parsing-progress state.
 */
import { expect, test } from '@playwright/test'

test('uploads multiple attachments concurrently and stops at uploaded state', async ({ page }, testInfo) => {
  let uploadStarts = 0
  let statusPolls = 0
  let streamStarts = 0
  let releaseUploads: (() => void) | undefined
  const uploadGate = new Promise<void>((resolve) => { releaseUploads = resolve })

  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/agent/attachments/upload') {
      const uploadIndex = ++uploadStarts
      await uploadGate
      const filename = uploadIndex === 1 ? 'alpha.txt' : 'beta.txt'
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        ok: true,
        attachment: {
          attachment_id: `att-${uploadIndex}`, user_id: 'e2e-user', session_id: 'parallel-session',
          library_id: 'default', library_name: '默认知识库', filename, stored_name: filename,
          uri: `session-upload://e2e-user/default/parallel-session/${filename}`, mime_type: 'text/plain',
          size: 5, source_type: 'attachment', created_at: '2026-09-17T08:00:00Z',
          metadata: { processing_status: 'uploaded', processing_stage: 'uploaded', processing_progress: 100, content_status: 'unparsed' },
        },
      }) })
      return
    }
    if (url.pathname === '/agent/stream') {
      streamStarts += 1
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: [DONE]\n\n' })
      return
    }
    if (/^\/agent\/attachments\/att-/.test(url.pathname)) {
      statusPolls += 1
      await route.fulfill({ status: 500, body: 'unexpected poll' })
      return
    }
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
    if (url.pathname === '/sessions' && request.method() === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        session_id: 'parallel-session', user_id: 'e2e-user', session_name: 'parallel', created_at: '', updated_at: '',
      }) })
      return
    }
    if (url.pathname === '/sessions' && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (url.pathname.endsWith('/messages')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (url.pathname === '/favorites') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"favorites":[]}' })
      return
    }
    if (url.pathname === '/knowledge/files') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"tree":[]}' })
      return
    }
    if (url.pathname === '/skills') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"skills":[],"count":0}' })
      return
    }
    if (url.pathname === '/todo/list' || url.pathname === '/automation/list') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (url.pathname === '/health') {
      await route.fulfill({ status: 200, body: 'ok' })
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
  await page.setViewportSize({ width: 1024, height: 768 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.locator('.agent-panel').evaluate((element) => {
    const transfer = new DataTransfer()
    transfer.items.add(new File(['alpha'], 'alpha.txt', { type: 'text/plain' }))
    transfer.items.add(new File(['beta'], 'beta.txt', { type: 'text/plain' }))
    element.dispatchEvent(new DragEvent('dragenter', { bubbles: true, dataTransfer: transfer }))
    element.dispatchEvent(new DragEvent('drop', { bubbles: true, dataTransfer: transfer }))
  })

  await expect.poll(() => uploadStarts).toBe(2)
  await page.getByPlaceholder('输入消息...').fill('读取这两个附件')
  await page.getByRole('button', { name: '发送' }).click()
  await new Promise((resolve) => setTimeout(resolve, 150))
  expect(streamStarts).toBe(0)
  releaseUploads?.()
  await expect(page.locator('.attachment-name')).toHaveCount(2)
  await expect(page.locator('.attachment-processing')).toHaveCount(0)
  await expect.poll(() => streamStarts).toBe(1)
  await new Promise((resolve) => setTimeout(resolve, 700))
  expect(statusPolls).toBe(0)
  await page.screenshot({ path: testInfo.outputPath('parallel-uploaded.png'), fullPage: true })
})
