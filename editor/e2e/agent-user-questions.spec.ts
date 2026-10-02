/*
 * Actual question smoke: start tests/user_question_smoke_server.py on 8002 first.
 * Only unrelated UI services are stubbed; questions, SSE, answers, cancellation
 * and persisted result inspection use the real backend through the Vite proxy.
 */
import { expect, test, type Page } from '@playwright/test'
import { resolve } from 'node:path'

test.use({ headless: true })

/** Mount the real workspace while isolating unrelated libraries and model downloads. */
async function openAgent(page: Page, sessionId: string) {
  let created = false
  const session = { session_id: sessionId, user_id: 'question-smoke-user', session_name: '提问验收', created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
  await page.route('**/*', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.startsWith('/agent/questions') || ['/agent/stream', '/agent/cancel', '/agent/question-smoke/status'].includes(path)) {
      await route.continue()
      return
    }
    if (!['fetch', 'xhr', 'eventsource'].includes(request.resourceType())) { await route.continue(); return }
    let body: unknown = {}
    if (path === '/settings/profile') body = { user_id: 'question-smoke-user', knowledge_dir: 'D:/Knowledge', active_library_id: 'default', knowledge_libraries: [] }
    if (path === '/settings/llm/config') body = { model_name: 'question-test-model', effective_model_name: 'question-test-model', effective_model_source: 'remote', context_window_tokens: 32768 }
    if (path === '/settings/models/status') body = { embedding: 'ready', rerank: 'ready' }
    if (path === '/settings/models/management') body = { models: [] }
    if (path === '/agent/children') body = { children: [] }
    if (path === '/sessions') {
      if (request.method() === 'POST') { created = true; body = session } else body = created ? [session] : []
    }
    if (path.endsWith('/messages') || path === '/todo/list' || path === '/automation/list') body = []
    if (path.startsWith('/favorites')) body = { favorites: [] }
    if (path === '/privacy') body = { privacy: [] }
    if (path === '/knowledge/files') body = { tree: [] }
    if (path === '/agent/task-suggestions') body = { suggestions: [] }
    await route.fulfill({ status: 200, contentType: path === '/knowledge/files/events' ? 'text/event-stream' : 'application/json', body: path === '/knowledge/files/events' ? '' : JSON.stringify(body) })
  })
  await page.addInitScript(() => localStorage.setItem('agent_editor_profile', JSON.stringify({ userId: 'question-smoke-user', knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default', knowledgeLibraries: [] })))
  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await expect(page.locator('.chat-input-wrap .input-area')).toBeVisible()
}

/** Read actual SQLite-backed events using the same dev port as the browser. */
async function persisted(page: Page, sessionId: string) {
  const response = await page.request.get(`/agent/question-smoke/status?user_id=question-smoke-user&session_id=${sessionId}`)
  expect(response.status()).toBe(200)
  return response.json()
}

test('single choice pauses the graph and resumes the same run with a durable answer', async ({ page }) => {
  const sessionId = `smoke-single-${Date.now()}`
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await openAgent(page, sessionId)
  await page.locator('.input-area').fill('单题验收')
  await page.locator('.input-area').press('Enter')
  const box = page.getByRole('form', { name: 'Agent 提问' })
  await expect(box).toBeVisible()
  await expect(page.locator('.thinking-flow')).toHaveText('等待回答')
  const state = await persisted(page, sessionId)
  expect(state.questions[0].status).toBe('pending')
  expect(state.final).toEqual([])
  const proxyResponse = await page.request.get(`/agent/questions?user_id=question-smoke-user&session_id=${sessionId}`)
  expect((await proxyResponse.json()).requests[0].request_id).toBe(state.questions[0].request_id)
  await expect(box.getByRole('button', { name: '确定' })).toHaveCount(0)
  await box.getByText('阅读并总结', { exact: true }).click()
  await expect(box).toHaveCount(0)
  await expect.poll(async () => (await persisted(page, sessionId)).final.length).toBe(1)
  const completed = await persisted(page, sessionId)
  expect(completed.questions[0].status).toBe('answered')
  expect(completed.questions[0].run_id).toBe(state.questions[0].run_id)
  expect(completed.questions[0].answers.q1.selected_options).toEqual(['阅读并总结'])
  await expect(page.locator('.thinking-flow')).toHaveCount(0)
  expect(errors).toEqual([])
})

for (const width of [1024, 768, 480, 320]) {
  test(`multi-question navigation, confirmation and actual layout at ${width}px`, async ({ page }) => {
    const sessionId = `smoke-multi-${width}-${Date.now()}`
    await page.setViewportSize({ width, height: 900 })
    await openAgent(page, sessionId)
    await page.locator('.input-area').fill('多题验收')
    await page.locator('.input-area').press('Enter')
    const box = page.getByRole('form', { name: 'Agent 提问' })
    await expect(box).toBeVisible()
    await expect(page.locator('.question-extension')).toHaveCSS('transform', 'none')
    await expect(box.locator('.question-number')).toHaveText('1 / 3')
    const confirm = box.getByRole('button', { name: '确定', exact: true })
    await expect(confirm).toBeDisabled()
    await expect(box.getByRole('button', { name: '上一个问题' })).toBeDisabled()
    const geometry = await box.evaluate(element => {
      const rect = element.getBoundingClientRect()
      const input = document.querySelector('.input-container')!
      const inputRect = input.getBoundingClientRect()
      const styles = getComputedStyle(element)
      const extension = getComputedStyle(element.parentElement!)
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, inputTop: inputRect.top,
        radius: styles.borderRadius, inputRadius: getComputedStyle(input).borderRadius, border: styles.borderWidth,
        overflow: element.scrollWidth > element.clientWidth, slideOffset: extension.getPropertyValue('--settings-slide-offset') }
    })
    expect(geometry.left).toBeGreaterThanOrEqual(0)
    expect(geometry.right).toBeLessThanOrEqual(width)
    expect(geometry.top).toBeGreaterThanOrEqual(0)
    expect(geometry.bottom).toBeLessThan(geometry.inputTop)
    expect(geometry.radius).toBe(geometry.inputRadius)
    expect(geometry.border).toBe('0px')
    expect(geometry.overflow).toBe(false)
    expect(geometry.slideOffset.trim()).toBe('8px')
    await page.screenshot({ path: resolve(`../docs/acceptance/agent-user-question-${width}.png`) })
    await box.getByText('阅读并总结', { exact: true }).click()
    await expect(confirm).toBeDisabled()
    await box.getByRole('button', { name: '下一个问题' }).click()
    await expect(box.locator('.question-number')).toHaveText('2 / 3')
    await box.getByText('摘要', { exact: true }).click()
    await box.getByText('引用', { exact: true }).click()
    await box.getByRole('button', { name: '上一个问题' }).click()
    await expect(box.getByRole('radio', { name: '阅读并总结' })).toBeChecked()
    await box.getByRole('button', { name: '下一个问题' }).click()
    await expect(box.getByRole('checkbox', { name: '摘要' })).toBeChecked()
    await expect(box.getByRole('checkbox', { name: '引用' })).toBeChecked()
    await box.getByRole('button', { name: '下一个问题' }).click()
    await expect(box.getByRole('button', { name: '下一个问题' })).toBeDisabled()
    await expect(confirm).toBeDisabled()
    await box.getByLabel('手动输入', { exact: true }).fill('保留中文、日文「資料」及引用')
    await expect(confirm).toBeEnabled()
    await page.screenshot({ path: resolve(`../docs/acceptance/agent-user-question-${width}-confirm.png`) })
    const before = await persisted(page, sessionId)
    expect(before.final).toEqual([])
    const submission = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/answer'))
    await confirm.click()
    expect((await submission).postDataJSON().answers.q2.selected_options).toEqual(['摘要', '引用'])
    await expect(box).toHaveCount(0)
    await expect.poll(async () => (await persisted(page, sessionId)).final.length).toBe(1)
    expect((await persisted(page, sessionId)).questions[0].answers.q3.text).toBe('保留中文、日文「資料」及引用')
  })
}

test('stop releases the actual waiting tool and persists cancellation', async ({ page }) => {
  const sessionId = `smoke-cancel-${Date.now()}`
  await openAgent(page, sessionId)
  await page.locator('.input-area').fill('单题取消验收')
  await page.locator('.input-area').press('Enter')
  await expect(page.getByRole('form', { name: 'Agent 提问' })).toBeVisible()
  await page.getByTitle('中断输出', { exact: true }).click()
  await expect(page.getByRole('form', { name: 'Agent 提问' })).toHaveCount(0)
  await expect.poll(async () => (await persisted(page, sessionId)).questions[0].status).toBe('cancelled')
})

for (const kind of ['多选', '输入']) {
  test(`single ${kind} requires explicit confirmation`, async ({ page }) => {
    const sessionId = `smoke-${kind}-${Date.now()}`
    await openAgent(page, sessionId)
    await page.locator('.input-area').fill(`${kind}验收`)
    await page.locator('.input-area').press('Enter')
    const box = page.getByRole('form', { name: 'Agent 提问' })
    const confirm = box.getByRole('button', { name: '确定', exact: true })
    await expect(confirm).toBeDisabled()
    if (kind === '多选') {
      await box.getByText('阅读并总结', { exact: true }).click()
      await box.getByText('保留原文', { exact: true }).click()
    } else {
      await box.getByLabel('手动输入', { exact: true }).fill('保留方法部分')
    }
    expect((await persisted(page, sessionId)).final).toEqual([])
    await expect(confirm).toBeEnabled()
    await confirm.click()
    await expect(box).toHaveCount(0)
    await expect.poll(async () => (await persisted(page, sessionId)).final.length).toBe(1)
  })
}

test('server rejection preserves the draft and permits a real retry', async ({ page }) => {
  const sessionId = `smoke-retry-${Date.now()}`
  await openAgent(page, sessionId)
  let rejected = false
  await page.route('**/agent/questions/*/answer', async route => {
    if (rejected) { await route.continue(); return }
    rejected = true
    // Exercise the actual REST validator, with an intentionally incomplete request.
    await route.continue({ postData: JSON.stringify({ ...route.request().postDataJSON(), answers: {} }) })
  })
  await page.locator('.input-area').fill('单题重试验收')
  await page.locator('.input-area').press('Enter')
  const box = page.getByRole('form', { name: 'Agent 提问' })
  await expect(box).toBeVisible()
  await box.getByText('阅读并总结', { exact: true }).click()
  await expect(box.getByRole('alert')).toContainText('请回答所有问题')
  await expect(box.getByRole('radio', { name: '阅读并总结' })).toBeChecked()
  expect((await persisted(page, sessionId)).final).toEqual([])
  await box.getByRole('button', { name: '确定', exact: true }).click()
  await expect(box).toHaveCount(0)
  await expect.poll(async () => (await persisted(page, sessionId)).final.length).toBe(1)
})

test('light theme uses the shared settings rise motion and reduced motion respects accessibility', async ({ page }) => {
  const sessionId = `smoke-motion-${Date.now()}`
  await page.addInitScript(() => localStorage.setItem('agent_editor_theme_mode', 'light'))
  await openAgent(page, sessionId)
  await page.evaluate(() => {
    const samples: Array<{ y: number; opacity: number }> = []
    Object.assign(window, { questionMotion: samples })
    const observer = new MutationObserver(() => {
      const extension = document.querySelector('.question-extension')
      if (!extension) return
      observer.disconnect()
      const started = performance.now()
      const sample = () => {
        const style = getComputedStyle(extension)
        samples.push({ y: new DOMMatrix(style.transform === 'none' ? undefined : style.transform).m42, opacity: Number(style.opacity) })
        if (performance.now() - started < 350) requestAnimationFrame(sample)
      }
      requestAnimationFrame(sample)
    })
    observer.observe(document.querySelector('.chat-input-wrap')!, { subtree: true, childList: true })
  })
  await page.locator('.input-area').fill('单题上浮动效验收')
  await page.locator('.input-area').press('Enter')
  const box = page.getByRole('form', { name: 'Agent 提问' })
  await expect(box).toBeVisible()
  await expect(page.locator('.question-extension')).toHaveCSS('transform', 'none')
  const motion = await page.evaluate(() => (window as unknown as { questionMotion: Array<{ y: number; opacity: number }> }).questionMotion)
  expect(motion.some(sample => sample.y > 0 && sample.opacity < 1)).toBe(true)
  expect(motion.at(-1)?.y).toBe(0)
  await page.screenshot({ path: resolve('../docs/acceptance/agent-user-question-light.png') })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const reduced = await page.locator('.question-extension').evaluate(element => {
    element.classList.add('settings-disclosure-enter-active')
    const duration = getComputedStyle(element).transitionDuration
    element.classList.remove('settings-disclosure-enter-active')
    return duration
  })
  // The global accessibility stylesheet keeps a 0.01ms transition to deliver lifecycle events.
  expect(Number.parseFloat(reduced)).toBeLessThanOrEqual(0.00001)
  await box.getByText('保留原文', { exact: true }).click()
  await expect(box).toHaveCount(0)
})
