/**
 * Agent page frame and scrollbar browser regression.
 *
 * Usage:
 * Renders the real Agent workspace, verifies it inherits the shared 4px panel
 * ring, and physically drags the native message-list scrollbar.
 */
import { expect, test } from '@playwright/test'

test('Agent workspace has the shared frame and a draggable scrollbar', async ({ page }) => {
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/settings/llm/config') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          model_name: 'deepseek-chat',
          effective_model_name: 'deepseek-chat',
          effective_model_source: 'remote',
          context_window_tokens: 32768,
          updated_at: new Date().toISOString(),
        }),
      })
      return
    }
    if (url.pathname === '/health') {
      await route.fulfill({ status: 200, body: 'ok' })
      return
    }
    if (url.pathname === '/settings/models/status') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ embedding: 'ready', rerank: 'ready' }),
      })
      return
    }
    if (url.pathname === '/settings/profile') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user_id: 'e2e-user',
          knowledge_dir: 'D:/Knowledge',
          active_library_id: 'default',
          knowledge_libraries: [],
        }),
      })
      return
    }
    if (url.pathname === '/sessions' || url.pathname === '/todo/list' || url.pathname === '/automation/list') {
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
    if (url.pathname === '/knowledge/files/events') {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
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
      userId: 'e2e-user',
      knowledgeDir: 'D:/Knowledge',
      activeLibraryId: 'default',
      knowledgeLibraries: [],
    }))
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()

  const modelLabel = page.locator('.model-config-trigger span')
  await expect(modelLabel).toBeVisible()
  await expect(modelLabel).toHaveText('deepseek-chat')
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent('agent-model-config-updated', {
      detail: { modelName: 'remote-model-after-save' },
    }))
  })
  await expect(modelLabel).toHaveText('remote-model-after-save')

  const workspace = page.locator('.main-shell.agent-page-main-shell')
  await expect(workspace).toBeVisible()
  const frame = await workspace.evaluate((element) => {
    const style = getComputedStyle(element)
    return { borderWidth: style.borderWidth, borderRadius: style.borderRadius, boxShadow: style.boxShadow }
  })
  expect(frame.borderWidth).toBe('1px')
  expect(frame.boxShadow).toContain('4px')

  await page.getByTitle('Toggle sidebar').click()
  const sessionDrawer = page.locator('.session-drawer.page-mode')
  await expect(sessionDrawer).toBeVisible()
  await expect(sessionDrawer).toHaveCSS('border-radius', frame.borderRadius)

  const messageList = page.locator('.message-list')
  await expect(messageList).toBeVisible()
  const scrollbar = await messageList.evaluate((element) => {
    const filler = document.createElement('div')
    filler.style.minHeight = '3000px'
    filler.style.flex = 'none'
    element.append(filler)
    const style = getComputedStyle(element)
    const pseudo = getComputedStyle(element, '::-webkit-scrollbar')
    return {
      overflowY: style.overflowY,
      scrollbarWidth: style.scrollbarWidth,
      webkitWidth: pseudo.width,
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
    }
  })
  expect(scrollbar.overflowY).toBe('auto')
  expect(scrollbar.scrollbarWidth).toBe('thin')
  expect(scrollbar.webkitWidth).toBe('10px')
  expect(scrollbar.scrollHeight).toBeGreaterThan(scrollbar.clientHeight)

  const bounds = await messageList.boundingBox()
  expect(bounds).not.toBeNull()
  const visibleBounds = bounds!
  await page.mouse.move(visibleBounds.x + visibleBounds.width - 4, visibleBounds.y + 18)
  await page.mouse.down()
  await page.mouse.move(visibleBounds.x + visibleBounds.width - 4, visibleBounds.y + 180, { steps: 8 })
  await page.mouse.up()
  await expect.poll(() => messageList.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)

  const environmentButton = page.getByRole('button', { name: '环境变更', exact: true })
  await environmentButton.click()
  await expect(environmentButton).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('.environment-card-shell')).toBeVisible()
  await expect(page.locator('.task-list-card')).toBeVisible()
  await expect(page.locator('.child-agent-card')).toBeVisible()

  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent('agent-change-updated', {
      detail: {
        snapshot_id: 'e2e-snapshot',
        session_id: '',
        run_id: 'e2e-run',
        additions: 1,
        deletions: 1,
        is_undone: false,
        created_at: new Date().toISOString(),
        files: [{
          path: 'example.ts', additions: 1, deletions: 1,
          edits: [{ path: 'example.ts', before: 'old', after: 'new', additions: 1, deletions: 1 }],
        }],
        edits: [{ path: 'example.ts', before: 'old', after: 'new', additions: 1, deletions: 1 }],
      },
    }))
  })
  await page.locator('.change-row').click()
  const changeDetail = page.locator('.change-detail')
  await changeDetail.waitFor({ state: 'attached' })
  const enteringWidth = await changeDetail.evaluate((element) => element.getBoundingClientRect().width)
  await page.waitForTimeout(300)
  const settledBounds = await changeDetail.boundingBox()
  expect(settledBounds).not.toBeNull()
  expect(settledBounds!.width).toBeGreaterThan(enteringWidth)

  await changeDetail.locator('header button').click()
  await page.waitForTimeout(40)
  await expect(changeDetail).toBeAttached()
  const leavingBounds = await changeDetail.boundingBox()
  expect(leavingBounds).not.toBeNull()
  expect(leavingBounds!.x).toBeGreaterThan(settledBounds!.x)
  await expect(changeDetail).toHaveCount(0)

  await environmentButton.click()
  await expect(environmentButton).toHaveAttribute('aria-pressed', 'false')
  await expect(page.locator('.agent-sidebar')).not.toHaveClass(/open/)
  await expect(page.locator('.environment-card-shell')).toBeHidden()
  await expect(page.locator('.task-list-card')).toBeHidden()
  await expect(page.locator('.child-agent-card')).toBeHidden()
})
