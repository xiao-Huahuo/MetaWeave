/**
 * Agent Markdown link browser smoke: real rendering, streaming, hover, and navigation.
 * Network fixtures supply an assistant reply; GitHub's favicon uses the live provider.
 */
import { expect, test } from '@playwright/test'

test.use({ headless: true })

test('shows link icons and theme hover colors throughout an Agent reply', async ({ page }, testInfo) => {
  const content = '[AgentCore](D:/Knowledge/agent_core.py:203) · [组件](./View.vue)\n\n'
    + '[GitHub](https://github.com/private/path?token=private#section) · [无法加载的网站](https://favicon-failure.invalid)\n\n'
    + '本地资料：source.md\n\n![正文图片](https://example.com/diagram.png)'
  const faviconOrigins: string[] = []
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.hostname === 't0.gstatic.com') {
      const origin = url.searchParams.get('url') ?? ''
      faviconOrigins.push(origin)
      if (origin.includes('favicon-failure.invalid')) return route.abort()
      return route.continue()
    }
    if (url.pathname === '/diagram.png') return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="48"><rect width="160" height="48" fill="#476bf7"/></svg>' })
    if (url.pathname === '/knowledge/files/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
    if (url.pathname === '/settings/profile') return route.fulfill({ json: { user_id: 'link-icons-user', knowledge_dir: 'D:/Knowledge', knowledge_libraries: [] } })
    if (url.pathname === '/knowledge/files') return route.fulfill({ json: { tree: [{ name: 'source.md', path: 'source.md', isDir: false }] } })
    if (url.pathname === '/knowledge/files/preview') return route.fulfill({ json: { path: 'source.md', kind: 'markdown', content: '# 本地资料', readonly: false } })
    if (url.pathname === '/sessions' && request.method() === 'POST') return route.fulfill({ json: { session_id: 'link-icons-session', user_id: 'link-icons-user', session_name: 'links', created_at: '', updated_at: '' } })
    if (url.pathname === '/sessions' || url.pathname.endsWith('/messages') || url.pathname === '/todo/list' || url.pathname === '/automation/list') return route.fulfill({ json: [] })
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') return route.fulfill({ json: {} })
    return route.continue()
  })
  await page.addInitScript((text) => {
    localStorage.setItem('agent_editor_profile', JSON.stringify({ userId: 'link-icons-user', knowledgeDir: 'D:/Knowledge', knowledgeLibraries: [] }))
    const nativeFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const requestUrl = input instanceof Request ? input.url : String(input)
      if (new URL(requestUrl, window.location.href).pathname !== '/agent/stream') return nativeFetch(input, init)
      const encoder = new TextEncoder()
      const event = { type: 'delta', node: 'agent', content: text, tool_calls: [], trace: [], metadata: {} }
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
          ;(window as typeof window & { finishLinkReply?: () => void }).finishLinkReply = () => {
            controller.enqueue(encoder.encode('data: [DONE]\n\n'))
            controller.close()
          }
        },
      })
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
    }
  }, content)

  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.getByPlaceholder('输入消息...').fill('验证链接图标')
  await page.getByTitle('发送').click()
  const markdown = page.locator('.markdown-body').last()
  await expect(markdown.locator('.markdown-link-icon')).toHaveCount(4)
  await expect(markdown.locator('a').first().locator('.markdown-link-icon')).toHaveClass(/is-loaded/)
  expect(await markdown.locator('a').first().locator('img').evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  const github = markdown.getByRole('link', { name: 'GitHub', exact: true })
  await expect(github.locator('.markdown-link-icon')).toHaveClass(/is-loaded/, { timeout: 15000 })
  expect(faviconOrigins).toContain('https://github.com')
  expect(faviconOrigins.every((origin) => !origin.includes('private') && !origin.includes('token'))).toBe(true)
  const failed = markdown.getByRole('link', { name: '无法加载的网站', exact: true })
  await expect(failed.locator('.markdown-link-icon img')).toHaveCount(0)
  await expect(failed.locator('.markdown-link-icon__fallback')).toBeVisible()
  await page.evaluate(() => (window as typeof window & { finishLinkReply?: () => void }).finishLinkReply?.())
  await expect(page.getByTitle('中断输出')).toBeHidden()
  await expect(markdown.locator('.markdown-link-icon')).toHaveCount(5)

  for (const mode of ['Tool', 'Chat']) {
    await page.setViewportSize({ width: 1024, height: 900 })
    await page.getByRole('button', { name: `${mode} mode`, exact: true }).click()
    for (const theme of ['light', 'dark']) {
      await page.evaluate((value) => document.documentElement.setAttribute('data-theme', value), theme)
      for (const link of [github, markdown.getByRole('link', { name: 'AgentCore', exact: true }), markdown.getByRole('button', { name: 'source.md', exact: true })]) {
        await page.mouse.move(0, 0)
        const original = await link.evaluate((el) => getComputedStyle(el).color)
        await link.hover()
        await expect.poll(() => link.evaluate((el) => getComputedStyle(el).color)).not.toBe(original)
      }
      await page.mouse.move(0, 0)
      for (const width of [1024, 768, 480]) {
        await page.setViewportSize({ width, height: 900 })
        await expect(github).toBeVisible()
        expect(await markdown.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
        await page.screenshot({ path: testInfo.outputPath(`links-${mode.toLowerCase()}-${theme}-${width}.png`), fullPage: true })
      }
    }
  }
  await markdown.getByRole('button', { name: 'source.md', exact: true }).click({ position: { x: 6, y: 6 } })
  await expect(page.locator('.editor-sidebar-content')).toHaveAttribute('aria-hidden', 'false')
  await expect(page.locator('.image-previewer-overlay')).toHaveCount(0)
})
