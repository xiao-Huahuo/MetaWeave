/** Browser acceptance for knowledge-work cards, prefix rows, draft resampling and responsive widths. */
import { expect, test } from '@playwright/test'

test('Agent knowledge starters support all functions and responsive new drafts', async ({ page }) => {
  let createdSessions = 0
  const sessions: Array<Record<string, string>> = []
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/sessions' && request.method() === 'POST') {
      createdSessions += 1
      const session = {
        session_id: `first-bubble-session-${createdSessions}`,
        user_id: 'e2e-user',
        session_name: `第 ${createdSessions} 个对话`,
        created_at: '2026-09-01T00:00:00Z',
        updated_at: '2026-09-01T00:00:00Z',
      }
      sessions.unshift(session)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(session),
      })
      return
    }
    if (url.pathname === '/sessions') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(sessions),
      })
      return
    }
    if (url.pathname === '/agent/stream') {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
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
    if (url.pathname === '/settings/models/management') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"models":[]}' })
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
    if (url.pathname === '/agent/children') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: url.searchParams.get('session_id') || '', children: [] }),
      })
      return
    }
    if (url.pathname === '/todo/list' || url.pathname === '/automation/list') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
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


  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  const cards = page.locator('.prompt-starter-card')
  const input = page.getByPlaceholder('输入消息...')
  await expect(cards).toHaveCount(4)
  const initial = await cards.allTextContents()
  expect(new Set(initial).size).toBe(4)
  const selected = cards.first()
  const icon = await selected.locator('[data-icon-name]').getAttribute('data-icon-name')
  const color = await selected.locator('[data-icon-name]').evaluate(el => getComputedStyle(el).color)
  await selected.click()
  await expect(page.locator('.prompt-waterfall-item')).toHaveCount(4)
  await expect(page.locator('.prompt-waterfall-icon').first()).toHaveAttribute('data-icon-name', icon!)
  await expect(page.locator('.prompt-waterfall-icon').first()).toHaveCSS('color', color)
  await page.locator('.prompt-waterfall-item').first().click()
  await expect(input).toHaveValue(/.+/)
  expect(createdSessions).toBe(0)
  const prefixes = ['检索', '整理', '阅读', '提取', '关联', '撰写', '绘制', '规划']
  const colors = new Set<string>()
  const icons = new Set<string>()
  for (const prefix of prefixes) {
    await input.fill(prefix)
    const rows = page.locator('.prompt-waterfall-item')
    await expect(rows).toHaveCount(4)
    expect((await rows.allTextContents()).every(text => text.trim().startsWith(prefix))).toBeTruthy()
    colors.add(await rows.first().locator('[data-icon-name]').evaluate(el => getComputedStyle(el).color))
    icons.add((await rows.first().locator('[data-icon-name]').getAttribute('data-icon-name'))!)
  }
  expect(colors.size).toBe(8)
  expect(icons.size).toBe(8)
  await input.fill('')
  await expect(cards).toHaveCount(4)
  expect(await cards.allTextContents()).toEqual(initial)
  const draws = new Set<string>([initial.join('|')])
  for (let i = 0; i < 5; i++) {
    await page.locator('.panel-new-session').click()
    await expect(cards).toHaveCount(4)
    await page.waitForTimeout(250)
    draws.add((await cards.allTextContents()).join('|'))
  }
  expect(draws.size).toBeGreaterThan(1)
  expect(createdSessions).toBe(0)
  for (const width of [1440, 1024, 768, 480, 360, 280]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(cards.first()).toBeVisible()
    await page.waitForTimeout(450)
    const count = await cards.count()
    expect(count).toBeGreaterThanOrEqual(1)
    expect(count).toBeLessThanOrEqual(4)
    for (const card of await cards.all()) {
      const bounds = await card.boundingBox()
      expect(bounds!.x).toBeGreaterThanOrEqual(0)
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width)
    }
    await page.screenshot({ path: 'test-results/agent-starters-' + width + '.png' })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.getByRole('navigation', { name: 'Editor activity bar' }).getByRole('button', { name: '主页', exact: true }).click()
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await expect(cards).toHaveCount(4)
  await input.fill('检索')
  await expect(page.locator('.prompt-waterfall-item')).toHaveCount(4)
  await page.waitForTimeout(450)
  await page.screenshot({ path: 'test-results/agent-starter-rows.png' })
  await page.getByRole('button', { name: '切换为浅色主题' }).click()
  await page.screenshot({ path: 'test-results/agent-starter-rows-light.png' })
  await page.setViewportSize({ width: 280, height: 900 })
  await expect(page.locator('.prompt-waterfall-item')).toHaveCount(4)
  await page.waitForTimeout(450)
  await page.screenshot({ path: 'test-results/agent-starter-rows-narrow.png' })
})
