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
    if (path === '/skills') body = { count: 1, skills: [{ skill_id: 'ponytail', name: 'Ponytail', description: '复用项目已有组件与样式。', source: 'builtin', path: '.agents/skills/ponytail', enabled: true, metadata: {}, has_scripts: false, has_references: false, has_assets: false }] }
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
  await expect(page.locator('.thinking-flow')).toHaveCount(0)
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
      const surface = element.querySelector('.question-surface')!
      const body = element.querySelector('.question-body')!
      const rect = surface.getBoundingClientRect()
      const input = document.querySelector('.input-container')!
      const inputRect = input.getBoundingClientRect()
      const styles = getComputedStyle(surface)
      const extension = getComputedStyle(element.parentElement!)
      const covering = document.elementFromPoint(rect.left + rect.width / 2, inputRect.top + 16)
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, inputWidth: inputRect.width, inputTop: inputRect.top,
        radius: styles.borderRadius, border: styles.borderWidth, outline: styles.outlineWidth, outlineOffset: styles.outlineOffset,
        shadow: styles.boxShadow, inputLayer: getComputedStyle(input).zIndex, surfaceLayer: styles.zIndex, bodyLayer: getComputedStyle(body).zIndex,
        bodyBottom: body.getBoundingClientRect().bottom, inputCoversSurface: Boolean(covering?.closest('.input-container')),
        overflow: body.scrollWidth > body.clientWidth, slideOffset: extension.getPropertyValue('--settings-slide-offset') }
    })
    expect(geometry.left).toBeGreaterThanOrEqual(0)
    expect(geometry.right).toBeLessThanOrEqual(width)
    expect(geometry.top).toBeGreaterThanOrEqual(0)
    expect(geometry.width).toBeLessThan(geometry.inputWidth)
    expect(geometry.inputWidth - geometry.width).toBe(width <= 480 ? 16 : 24)
    expect(geometry.bottom).toBeGreaterThan(geometry.inputTop)
    expect(geometry.bodyBottom).toBeLessThan(geometry.inputTop)
    expect(geometry.radius).toBe('28px')
    expect(geometry.border).toBe('1px')
    expect(geometry.outline).toBe('2px')
    expect(geometry.outlineOffset).toBe('2px')
    expect(geometry.shadow).not.toBe('none')
    expect(geometry.inputCoversSurface).toBe(true)
    expect(Number(geometry.surfaceLayer)).toBeLessThan(Number(geometry.inputLayer))
    expect(Number(geometry.bodyLayer)).toBeGreaterThan(Number(geometry.inputLayer))
    expect(geometry.overflow).toBe(false)
    expect(geometry.slideOffset.trim()).toBe('8px')
    const titleSize = await box.locator('.question-title.is-active').evaluate(element => getComputedStyle(element).fontSize)
    await expect(page.locator('.markdown-body p').first()).toHaveCSS('font-size', titleSize)
    await box.locator('.question-option').first().hover()
    await expect(box.locator('.question-option').first()).toHaveCSS('border-radius', '999px')
    await expect(confirm).toHaveCSS('border-radius', '999px')
    await page.screenshot({ path: resolve(`../docs/acceptance/agent-question-refined-${width}.png`) })
    await box.getByText('阅读并总结', { exact: true }).click()
    await expect(confirm).toBeDisabled()
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
    const manual = box.getByPlaceholder('试试手动输入', { exact: true })
    await expect(box.getByText('手动输入', { exact: true })).toHaveCount(0)
    await expect(box.getByRole('checkbox')).toHaveCount(0)
    await expect(box.getByRole('radio')).toHaveCount(0)
    await expect(manual).toHaveCSS('border-radius', '999px')
    await manual.fill('芙宁娜')
    await expect(confirm).toBeEnabled()
    await expect.poll(() => box.locator('.form-height-transition').evaluate(element => (element as HTMLElement).style.height)).toBe('auto')
    await page.screenshot({ path: resolve(`../docs/acceptance/agent-question-refined-${width}-input.png`) })
    if (width === 1024) await page.locator('.question-extension').screenshot({ path: resolve('../docs/acceptance/agent-question-refined-detail.png') })
    const before = await persisted(page, sessionId)
    expect(before.final).toEqual([])
    const submission = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/answer'))
    await confirm.click()
    expect((await submission).postDataJSON().answers.q2.selected_options).toEqual(['摘要', '引用'])
    await expect(box).toHaveCount(0)
    await expect.poll(async () => (await persisted(page, sessionId)).final.length).toBe(1)
    expect((await persisted(page, sessionId)).questions[0].answers.q3).toEqual({ selected_options: [], text: '芙宁娜' })
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
      await box.getByPlaceholder('试试手动输入', { exact: true }).fill('芙宁娜')
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

for (const continuation of [true, false]) {
  test(`a dependent input follows the choice only when needed: ${continuation}`, async ({ page }) => {
    const sessionId = `smoke-conditional-${continuation}-${Date.now()}`
    await openAgent(page, sessionId)
    await page.locator('.input-area').fill('条件追问验收')
    await page.locator('.input-area').press('Enter')
    const box = page.getByRole('form', { name: 'Agent 提问' })
    await expect(box).toBeVisible()
    await expect(box.getByPlaceholder('试试手动输入')).toHaveCount(0)
    await box.getByText(continuation ? '比较角色机制' : '结束任务', { exact: true }).click()
    if (continuation) {
      const input = box.getByPlaceholder('试试手动输入')
      await expect(input).toBeVisible()
      await expect(box.getByRole('radio')).toHaveCount(0)
      const pending = await persisted(page, sessionId)
      expect(pending.questions.map((item: { status: string }) => item.status)).toEqual(['answered', 'pending'])
      expect(pending.final).toEqual([])
      await expect(box.getByRole('button', { name: '确定', exact: true })).toBeDisabled()
      await input.fill('芙宁娜')
      await box.getByRole('button', { name: '确定', exact: true }).click()
    }
    await expect(box).toHaveCount(0)
    await expect.poll(async () => (await persisted(page, sessionId)).final.length).toBe(1)
    const completed = await persisted(page, sessionId)
    expect(completed.questions).toHaveLength(continuation ? 2 : 1)
    if (continuation) expect(completed.questions[1].answers.role).toEqual({ selected_options: [], text: '芙宁娜' })
  })
}

test('question shell and input reuse the actual settings Skill and capsule surfaces', async ({ page }) => {
  const sessionId = `smoke-settings-style-${Date.now()}`
  await openAgent(page, sessionId)
  await page.locator('.input-area').fill('输入样式验收')
  await page.locator('.input-area').press('Enter')
  const box = page.getByRole('form', { name: 'Agent 提问' })
  await expect(box).toBeVisible()
  const surface = await box.locator('.question-surface').evaluate(element => {
    const style = getComputedStyle(element)
    return [style.border, style.borderRadius, style.outline, style.outlineOffset, style.boxShadow, style.backgroundColor]
  })
  const input = box.getByPlaceholder('试试手动输入')
  await input.focus()
  await input.evaluate(element => Promise.all(element.getAnimations().map(animation => animation.finished)))
  await expect.poll(() => input.evaluate(element => getComputedStyle(element).boxShadow.endsWith('3px'))).toBe(true)
  const inputStyle = await input.evaluate(element => {
    const style = getComputedStyle(element)
    return [style.border, style.borderRadius, style.backgroundColor, style.boxShadow]
  })
  await page.getByTitle('中断输出', { exact: true }).click()
  await expect(box).toHaveCount(0)
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await page.getByRole('button', { name: 'Skills', exact: true }).click()
  const skill = page.locator('.skill-card.settings-block-surface').first()
  await expect(skill).toBeVisible()
  await page.mouse.move(0, 0)
  const reference = await skill.evaluate(element => {
    const style = getComputedStyle(element)
    return [style.border, style.borderRadius, style.outline, style.outlineOffset, style.boxShadow, style.backgroundColor]
  })
  expect(surface).toEqual(reference)
  await page.getByRole('button', { name: '基础设置', exact: true }).click()
  const field = page.locator('.settings-body .setting-row > input').first()
  await expect(field).toBeVisible()
  await field.focus()
  await field.evaluate(element => Promise.all(element.getAnimations().map(animation => animation.finished)))
  await expect.poll(() => field.evaluate(element => getComputedStyle(element).boxShadow.endsWith('3px'))).toBe(true)
  const fieldStyle = await field.evaluate(element => {
    const style = getComputedStyle(element)
    return [style.border, style.borderRadius, style.backgroundColor, style.boxShadow]
  })
  expect(inputStyle).toEqual(fieldStyle)
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
  await page.screenshot({ path: resolve('../docs/acceptance/agent-question-refined-light.png') })
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

for (const width of [1024, 320]) {
  test(`question and table text match the main body and font scaling at ${width}px`, async ({ page }) => {
    const sessionId = `smoke-font-${width}-${Date.now()}`
    await page.setViewportSize({ width, height: 900 })
    await openAgent(page, sessionId)
    await page.locator('.input-area').fill('多题宽表长选项字号验收')
    await page.locator('.input-area').press('Enter')
    const box = page.getByRole('form', { name: 'Agent 提问' })
    await expect(box).toBeVisible()
    await expect(page.locator('.question-extension')).toHaveCSS('transform', 'none')
    const sizes = async () => page.evaluate(() => {
      const paragraph = document.querySelector('.markdown-body p')!
      const table = document.querySelector('.markdown-body table')!
      const scroller = table.parentElement!
      const markdown = table.closest('.markdown-body')!
      const title = document.querySelector('.question-title.is-active')!
      return { paragraph: getComputedStyle(paragraph).fontSize, title: getComputedStyle(title).fontSize,
        cells: Array.from(table.querySelectorAll('th,td')).map(element => getComputedStyle(element).fontSize),
        tableWidth: table.getBoundingClientRect().width, markdownWidth: markdown.getBoundingClientRect().width,
        scrollWidth: scroller.scrollWidth, clientWidth: scroller.clientWidth, overflow: getComputedStyle(scroller).overflowX }
    })
    const normal = await sizes()
    expect(normal.title).toBe(normal.paragraph)
    expect(normal.cells.every(size => size === normal.paragraph)).toBe(true)
    await page.evaluate(() => document.documentElement.style.setProperty('--font-scale', '1.5'))
    const larger = await sizes()
    expect(Number.parseFloat(larger.paragraph)).toBeGreaterThan(Number.parseFloat(normal.paragraph))
    expect(larger.title).toBe(larger.paragraph)
    expect(larger.cells.every(size => size === larger.paragraph)).toBe(true)
    expect(larger.clientWidth).toBeLessThanOrEqual(larger.markdownWidth + 1)
    expect(larger.overflow).toBe('auto')
    await page.locator('.markdown-table-scroll').evaluate(element => { element.scrollLeft = element.scrollWidth })
    await expect.poll(() => page.locator('.markdown-table-scroll').evaluate(element => element.scrollLeft)).toBeGreaterThan(0)
    const columnsAligned = await page.locator('.markdown-body table').evaluate(element => {
      const headings = Array.from(element.querySelectorAll('th'))
      const cells = Array.from(element.querySelectorAll('tbody tr:first-child td'))
      return headings.every((heading, index) => {
        const a = heading.getBoundingClientRect(), b = cells[index]!.getBoundingClientRect()
        return Math.abs(a.x - b.x) < 1 && Math.abs(a.width - b.width) < 1
      })
    })
    expect(columnsAligned).toBe(true)
    await page.locator('.markdown-table-scroll').evaluate(element => { element.scrollLeft = 0 })
    await box.locator('.question-option').first().hover()
    await expect(box.locator('.question-header')).toBeInViewport()
    await expect(box.getByRole('button', { name: '下一个问题' })).toBeInViewport()
    await expect(box.getByRole('button', { name: '确定', exact: true })).toBeInViewport()
    await page.screenshot({ path: resolve(`../docs/acceptance/agent-question-refined-${width}-font.png`) })
    await box.locator('.question-option > label:not(.creative-checkbox)').first().click()
    await box.getByText('摘要', { exact: true }).click()
    await box.getByRole('button', { name: '下一个问题' }).click()
    await box.getByPlaceholder('试试手动输入').fill('芙宁娜')
    await box.getByRole('button', { name: '确定', exact: true }).click()
    await expect(box).toHaveCount(0)
  })
}

for (const width of [1024, 320]) {
  test(`answers auto-advance with a full-width carousel and preserve review at ${width}px`, async ({ page }) => {
    const sessionId = `smoke-carousel-${width}-${Date.now()}`
    await page.setViewportSize({ width, height: 900 })
    await openAgent(page, sessionId)
    await page.locator('.input-area').fill('多题轮播验收')
    await page.locator('.input-area').press('Enter')
    const box = page.getByRole('form', { name: 'Agent 提问' })
    await expect(box).toBeVisible()
    await page.evaluate(() => {
      const track = document.querySelector('.question-content')!.parentElement!
      const samples: Array<{ x: number; width: number }> = []
      Object.assign(window, { carouselSamples: samples })
      const start = performance.now()
      const sample = () => {
        const style = getComputedStyle(track)
        samples.push({ x: new DOMMatrix(style.transform).m41, width: track.getBoundingClientRect().width })
        if (performance.now() - start < 850) requestAnimationFrame(sample)
      }
      requestAnimationFrame(sample)
    })
    await box.getByText('阅读并总结', { exact: true }).click()
    await expect(box.locator('.question-number')).toHaveText('2 / 3')
    await expect(box.getByRole('button', { name: '下一个问题' })).toBeEnabled()
    const samples = await page.evaluate(() => (window as unknown as { carouselSamples: Array<{ x: number; width: number }> }).carouselSamples)
    expect(samples.some(sample => sample.x < -1 && sample.x > -sample.width + 1)).toBe(true)
    const matrix = await box.locator('.question-content').first().locator('..').evaluate(element => {
      const x = new DOMMatrix(getComputedStyle(element).transform).m41
      return { x, width: element.getBoundingClientRect().width }
    })
    expect(Math.abs(matrix.x + matrix.width)).toBeLessThan(1)
    await box.getByText('摘要', { exact: true }).click()
    await box.getByText('引用', { exact: true }).click()
    await expect(box.locator('.question-number')).toHaveText('2 / 3')
    await box.getByRole('checkbox', { name: '引用', exact: true }).press('Enter')
    await expect(box.locator('.question-number')).toHaveText('3 / 3')
    const input = box.getByPlaceholder('试试手动输入')
    await input.fill('芙宁娜')
    await input.press('Enter')
    await expect(box.locator('.question-number')).toHaveText('3 / 3')
    expect((await persisted(page, sessionId)).final).toEqual([])
    await box.getByRole('button', { name: '上一个问题' }).click()
    await expect(box.getByRole('checkbox', { name: '引用', exact: true })).toBeChecked()
    await box.getByRole('button', { name: '上一个问题' }).click()
    await expect(box.getByRole('radio', { name: '阅读并总结', exact: true })).toBeChecked()
    await expect(box.locator('.question-number')).toHaveText('1 / 3')
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await box.getByRole('button', { name: '下一个问题' }).click()
    await expect(box.getByRole('button', { name: '下一个问题' })).toBeEnabled()
    await box.getByRole('button', { name: '下一个问题' }).click()
    await expect(input).toHaveValue('芙宁娜')
    await page.screenshot({ path: resolve(`../docs/acceptance/agent-question-carousel-${width}.png`) })
    await box.getByRole('button', { name: '确定', exact: true }).click()
    await expect(box).toHaveCount(0)
    await expect.poll(async () => (await persisted(page, sessionId)).final.length).toBe(1)
  })
}
