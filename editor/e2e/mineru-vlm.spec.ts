/**
 * MinerU VLM settings and shared scanner-menu visual smoke test.
 *
 * Uses stable network fixtures around the real Vue routes and components;
 * the Vite proxy itself is verified separately against the live backend.
 */
import { expect, test, type Page } from '@playwright/test'

test.use({ headless: true })

const screenshotDirectory = '../docs/acceptance'

async function mockWorkspace(page: Page): Promise<void> {
  const config = {
    user_id: 'mineru-smoke', enabled: true, api_key: 'smoke-key', configured: true,
    base_url: 'https://mineru.net', model: 'vlm', max_concurrency: 2,
    max_file_bytes: 209715200, max_pages: 600, submit_rate_per_minute: 300,
    result_rate_per_minute: 1000, batch_max_files: 200, poll_interval_seconds: 3,
    timeout_seconds: 300, ocr_enabled: true,
  }
  const scan = {
    scan_id: 'mineru-result', user_id: 'mineru-smoke', library_id: 'default', source_kind: 'file',
    source_name: 'mineru-page.png', source_path: '.mw/scan/mineru-result/source/mineru-page.png', source_url: '', size: 1024,
    ocr_enabled: false, online_enabled: true, parser_engine: 'mineru', parser_fallback_reason: '', status: 'finished',
    stage: 'completed', stage_label: '解析完成', progress: 100, no_ocr_markdown: '# MinerU Markdown\n\n解析正文',
    ocr_markdown: '', ocr_blocks: [{ page: 1, type: 'title', content: 'MinerU Markdown', bbox: [80, 60, 720, 150], id: 1, order: 0, page_width: 800, page_height: 600 }],
    ocr_preview_path: '.mw/scan/mineru-result/source/mineru-page.png', assets: [], error: '', source_text: null,
    created_at: '2026-09-11T08:00:00Z', updated_at: '2026-09-11T08:01:00Z', finished_at: '2026-09-11T08:01:00Z',
  }
  await page.route('**/*', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.pathname === '/health') return route.fulfill({ status: 200, body: 'ok' })
    if (url.pathname === '/settings/profile') return json({
      user_id: 'mineru-smoke', knowledge_dir: 'D:/Knowledge', active_library_id: 'default',
      vlm_enabled: true, ocr_enabled: true, knowledge_supported_suffixes: ['.pdf', '.docx', '.png'],
      knowledge_libraries: [{ library_id: 'default', name: 'MinerU 验收库', knowledge_dir: 'D:/Knowledge', library_storage_dir: '.mw/library', is_active: true }],
    })
    if (url.pathname === '/settings/vlm/config') return json(config)
    if (url.pathname === '/settings/vlm/check') return json({ online: true, authorized: true, message: 'MinerU 可连接' })
    if (url.pathname === '/settings/vlm/local-ocr/ensure') return json({ ready: true })
    if (url.pathname === '/settings/models/status' || url.pathname === '/settings/models/management') return json({ models: [] })
    if (url.pathname === '/scanner') return json({ scans: [scan], max_concurrency: 2 })
    if (url.pathname === '/scanner/mineru-result') return json(scan)
    if (url.pathname === '/knowledge/files/preview') return json({
      path: scan.source_path, kind: 'image', data_url: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="800" height="600"%3E%3Crect width="800" height="600" fill="white"/%3E%3C/svg%3E',
      mtime: '', size: 1024, extension: '.png', readonly: true,
    })
    if (url.pathname === '/knowledge/files') return json({ tree: [] })
    if (url.pathname === '/knowledge/files/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': smoke\n\n' })
    if (url.pathname === '/sessions' || url.pathname === '/todo/list' || url.pathname === '/automation/list') return json([])
    if (url.pathname === '/favorites') return json({ favorites: [] })
    if (url.pathname === '/privacy') return json({ privacy: [] })
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') return json({})
    return route.continue()
  })
  await page.addInitScript(() => localStorage.setItem('agent_editor_profile', JSON.stringify({
    userId: 'mineru-smoke', knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default', vlmEnabled: true,
    knowledgeLibraries: [{ libraryId: 'default', name: 'MinerU 验收库', knowledgeDir: 'D:/Knowledge', libraryStorageDir: '.mw/library', isActive: true }],
  })))
}

test('OCR/VLM settings and scanner menus remain usable at all target widths', async ({ page }) => {
  test.setTimeout(60_000)
  await mockWorkspace(page)
  await page.setViewportSize({ width: 1024, height: 820 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByRole('button', { name: 'OCR/VLM 设置' }).click()
  await expect(page.getByText('当前生效')).toBeVisible()
  await expect(page.getByLabel('MinerU API Key')).toHaveValue('smoke-key')
  await expect(page.getByLabel('模型')).toHaveValue('vlm')
  await page.getByRole('button', { name: '切换为浅色主题' }).click()
  await page.screenshot({ path: `${screenshotDirectory}/mineru-vlm-settings-light-1024.png`, fullPage: true })
  await page.getByRole('button', { name: '切换为深色主题' }).click()
  await page.emulateMedia({ reducedMotion: 'reduce' })

  for (const viewport of [{ width: 1024, name: '1024' }, { width: 768, name: '768' }, { width: 480, name: '480' }]) {
    await page.setViewportSize({ width: viewport.width, height: 820 })
    const overflow = await page.locator('.settings-page').evaluate(element => element.scrollWidth - element.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)
    await expect(page.getByRole('button', { name: 'OCR/VLM 设置' })).toBeInViewport()
    await page.screenshot({ path: `${screenshotDirectory}/mineru-vlm-settings-${viewport.name}.png`, fullPage: true })
    if (viewport.width === 480) {
      await page.getByRole('button', { name: '保存', exact: true }).scrollIntoViewIfNeeded()
      await expect(page.getByRole('button', { name: '保存', exact: true })).toBeInViewport()
      await page.screenshot({ path: `${screenshotDirectory}/mineru-vlm-settings-480-bottom.png`, fullPage: true })
    }
  }

  await page.setViewportSize({ width: 1024, height: 820 })
  await page.getByRole('button', { name: '扫描', exact: true }).click()
  await page.getByRole('button', { name: '扫描器', exact: true }).click()
  await page.getByRole('button', { name: '解析设置' }).click()
  await expect(page.getByText('联网', { exact: true })).toBeVisible()
  await expect(page.getByText('MinerU', { exact: true })).toBeVisible()
  await page.screenshot({ path: `${screenshotDirectory}/mineru-scanner-menu-1024.png`, fullPage: true })
  await page.keyboard.press('Escape')
  await page.locator('.scanner-history-card').focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('.scanner-source-pane rect[data-block-id="1:1"]')).toBeVisible()
  await expect(page.locator('.scanner-markdown-pane [data-ocr-block-id="1:1"]')).toBeVisible()
  await page.screenshot({ path: `${screenshotDirectory}/mineru-result-blocks-1024.png`, fullPage: true })
  await page.getByRole('button', { name: '返回上传页' }).click()

  await page.getByRole('button', { name: '扫描', exact: true }).click()
  await page.getByRole('button', { name: '扫描队列', exact: true }).click()
  await page.getByRole('button', { name: '解析设置' }).click()
  await expect(page.getByText('联网', { exact: true })).toBeVisible()
  await page.screenshot({ path: `${screenshotDirectory}/mineru-queue-menu-1024.png`, fullPage: true })
})
