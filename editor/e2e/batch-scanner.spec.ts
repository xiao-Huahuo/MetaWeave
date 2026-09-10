/**
 * Batch scanner queue visual and interaction smoke test.
 *
 * Exercises the real Vue page with deterministic ScannerRecord HTTP fixtures,
 * captures all required responsive layouts, and verifies backend-owned slots.
 */
import { expect, test, type Page } from '@playwright/test'

const screenshotDirectory = '../docs/screenshots/batch-scanner'

interface MockScan {
  scan_id: string
  source_name: string
  cancelled: boolean
}

/** Install the stable application and scanner contracts used by this page. */
async function mockBatchScannerWorkspace(page: Page): Promise<void> {
  const scans: MockScan[] = []
  let batchStartedAt = 0
  let batchExportBody: unknown = null
  let savedCount = 0

  const record = (scan: MockScan, index: number) => {
    const finished = batchStartedAt > 0 && Date.now() - batchStartedAt > 1_200
    const status = scan.cancelled ? 'cancelled' : finished ? 'finished' : index < 2 ? 'running' : 'queued'
    return {
      scan_id: scan.scan_id, user_id: 'batch-smoke', library_id: 'default', source_kind: 'file', source_name: scan.source_name,
      source_path: `.mw/scan/${scan.scan_id}/source/${scan.source_name}`, source_url: '', size: 4096 + index * 713, ocr_enabled: true,
      status, stage: status === 'running' ? 'ocr' : status === 'finished' ? 'completed' : status,
      stage_label: status === 'running' ? `正在识别第 ${index + 1} 份文档` : status === 'finished' ? '解析完成' : status === 'cancelled' ? '已终止' : '等待扫描',
      progress: status === 'running' ? 36.4 + index * 18.7 : status === 'finished' ? 100 : 0,
      no_ocr_markdown: status === 'finished' ? `# ${scan.source_name}\n\n原始解析结果` : '',
      ocr_markdown: status === 'finished' ? `# ${scan.source_name}\n\nOCR 解析结果` : '', ocr_blocks: [], assets: [], error: '', source_text: null,
      created_at: `2026-09-10T08:0${index}:00Z`, updated_at: '2026-09-10T08:10:00Z', finished_at: status === 'finished' ? '2026-09-10T08:12:00Z' : null,
    }
  }
  const historicalRecord = () => ({
    ...record({ scan_id: 'scan-history', source_name: '昨日归档.pdf', cancelled: false }, 3),
    status: 'finished', stage: 'completed', stage_label: '解析完成', progress: 100,
    no_ocr_markdown: '# 昨日归档', ocr_markdown: '# 昨日归档',
    finished_at: '2026-09-09T08:12:00Z',
  })

  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.pathname === '/health') return route.fulfill({ status: 200, contentType: 'text/plain', body: 'ok' })
    if (url.pathname === '/settings/models/status' || url.pathname === '/settings/models/management') return json({ models: [] })
    if (url.pathname === '/settings/profile') return json({
      user_id: 'batch-smoke', knowledge_dir: 'D:/Knowledge', active_library_id: 'default', editor_image_assets_dir: './assets/',
      knowledge_libraries: [{ library_id: 'default', name: '批量扫描验收库', knowledge_dir: 'D:/Knowledge', library_storage_dir: '.mw/library', is_active: true }],
    })
    if (url.pathname === '/scanner/files' && request.method() === 'POST') {
      await new Promise(resolve => setTimeout(resolve, 120))
      const index = scans.length
      const scan = { scan_id: `scan-${index + 1}`, source_name: ['实验记录.pdf', '电路图.png', '会议纪要.docx'][index] ?? `文档-${index + 1}.txt`, cancelled: false }
      scans.push(scan)
      if (!batchStartedAt) batchStartedAt = Date.now()
      return json(record(scan, index))
    }
    if (url.pathname === '/scanner/export-batch' && request.method() === 'POST') {
      batchExportBody = request.postDataJSON()
      return route.fulfill({ status: 200, contentType: 'application/zip', headers: { 'Content-Disposition': "attachment; filename*=UTF-8''scanner-batch.zip" }, body: 'zip' })
    }
    if (/^\/scanner\/scan-\d+\/save$/u.test(url.pathname) && request.method() === 'POST') {
      savedCount += 1
      return json({ ok: true, path: `saved-${savedCount}.md`, assets: [] })
    }
    if (url.pathname === '/scanner' && request.method() === 'GET') return json({ scans: [...scans.map(record), historicalRecord()], max_concurrency: 2 })
    if (url.pathname === '/agent-queue/tasks') return json({ tasks: [], settings: { max_concurrency: 5 } })
    const cancelMatch = url.pathname.match(/^\/scanner\/(scan-\d+)\/cancel$/u)
    if (cancelMatch && request.method() === 'POST') {
      const scan = scans.find(item => item.scan_id === cancelMatch[1])
      if (scan) scan.cancelled = true
      return json(record(scan as MockScan, scans.indexOf(scan as MockScan)))
    }
    const detailMatch = url.pathname.match(/^\/scanner\/(scan-\d+)$/u)
    if (detailMatch && request.method() === 'GET') {
      const scan = scans.find(item => item.scan_id === detailMatch[1]) as MockScan
      return json(record(scan, scans.indexOf(scan)))
    }
    if (url.pathname === '/knowledge/files') return json({ tree: [] })
    if (url.pathname === '/knowledge/files/preview') return json({ kind: 'text', content: '原始文档', readonly: true })
    if (url.pathname === '/knowledge/files/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': smoke\n\n' })
    if (url.pathname === '/sessions' || url.pathname === '/todo/list' || url.pathname === '/automation/list') return json([])
    if (url.pathname === '/favorites') return json({ favorites: [] })
    if (url.pathname === '/privacy') return json({ privacy: [] })
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') return json({})
    return route.continue()
  })
  await page.addInitScript(() => localStorage.setItem('agent_editor_profile', JSON.stringify({
    userId: 'batch-smoke', knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default',
    knowledgeLibraries: [{ libraryId: 'default', name: '批量扫描验收库', knowledgeDir: 'D:/Knowledge', libraryStorageDir: '.mw/library', isActive: true }],
  })))
  await page.exposeFunction('batchScannerSmokeState', () => ({ batchExportBody, savedCount }))
}

/** Assert the queue page remains within its responsive content span. */
async function expectNoOverflow(page: Page): Promise<void> {
  const overflow = await page.locator('.queue-page-shell').evaluate(element => element.scrollWidth - element.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
}

test('batch scanner submits independent tasks and matches queue layouts responsively', async ({ page }) => {
  test.setTimeout(60_000)
  await mockBatchScannerWorkspace(page)
  await page.setViewportSize({ width: 1024, height: 820 })
  await page.goto('/')
  await page.getByRole('button', { name: '扫描', exact: true }).click()
  await expect(page.getByLabel('扫描菜单')).toBeVisible()
  await page.screenshot({ path: `${screenshotDirectory}/activity-scan-menu-1024.png`, fullPage: true })
  await page.getByRole('button', { name: '扫描队列', exact: true }).click()
  await expect(page.locator('.queue-page-shell')).toBeVisible()
  await page.getByRole('button', { name: '新建批量扫描' }).click()
  await expect(page.getByRole('dialog', { name: '新建批量扫描' }).locator('.scanner-drop-zone')).toBeVisible()
  await page.screenshot({ path: `${screenshotDirectory}/form-desktop-1024.png`, fullPage: true })

  for (const viewport of [{ width: 768, height: 820, name: 'form-tablet-768' }, { width: 480, height: 760, name: 'form-mobile-480' }]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    const dialogOverflow = await page.getByRole('dialog', { name: '新建批量扫描' }).evaluate(element => element.scrollWidth - element.clientWidth)
    expect(dialogOverflow).toBeLessThanOrEqual(1)
    await page.screenshot({ path: `${screenshotDirectory}/${viewport.name}.png`, fullPage: true })
  }
  await page.setViewportSize({ width: 1024, height: 820 })

  const chooser = page.getByRole('dialog', { name: '新建批量扫描' }).locator('input[type="file"][multiple]')
  await chooser.setInputFiles([
    { name: '实验记录.pdf', mimeType: 'application/pdf', buffer: Buffer.from('pdf') },
    { name: '电路图.png', mimeType: 'image/png', buffer: Buffer.from('png') },
    { name: '会议纪要.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: Buffer.from('docx') },
  ])
  await expect(page.getByText('正在创建扫描任务')).toBeVisible()
  await page.screenshot({ path: `${screenshotDirectory}/form-loader-1024.png`, fullPage: true })

  await expect(page.locator('.queue-lane').nth(0).locator('.queue-task-card')).toHaveCount(1)
  await expect(page.locator('.queue-lane').nth(1).locator('.queue-task-card')).toHaveCount(2)
  await expect(page.getByText('最大并行').locator('..')).toContainText('2')
  await expectNoOverflow(page)
  await page.screenshot({ path: `${screenshotDirectory}/desktop-1024.png`, fullPage: true })

  await expect(page.locator('.queue-lane').nth(2).locator('.queue-task-card')).toHaveCount(3, { timeout: 8_000 })
  await page.screenshot({ path: `${screenshotDirectory}/completed-actions-1024.png`, fullPage: true })
  await page.getByRole('button', { name: '批量保存到知识库' }).click()
  await expect.poll(async () => (await page.evaluate(async () => await (window as typeof window & { batchScannerSmokeState: () => Promise<{ savedCount: number }> }).batchScannerSmokeState())).savedCount).toBe(3)
  await page.getByRole('button', { name: '批量导出 ZIP' }).click()
  await expect.poll(async () => (await page.evaluate(async () => await (window as typeof window & { batchScannerSmokeState: () => Promise<{ batchExportBody: { items?: unknown[] } | null }> }).batchScannerSmokeState())).batchExportBody?.items?.length ?? 0).toBe(3)
  await page.locator('.queue-lane').nth(2).locator('.queue-task-card').first().click()
  await expect(page.getByRole('dialog', { name: '扫描结果' })).toBeVisible()
  await page.getByRole('dialog', { name: '扫描结果' }).getByRole('button', { name: '关闭', exact: true }).click()

  for (const viewport of [{ width: 768, height: 820, name: 'tablet-768' }, { width: 480, height: 760, name: 'mobile-480' }]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await expectNoOverflow(page)
    await page.screenshot({ path: `${screenshotDirectory}/${viewport.name}.png`, fullPage: true })
  }

  await page.setViewportSize({ width: 1024, height: 820 })
  await page.getByRole('button', { name: '切换为浅色主题' }).click()
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${screenshotDirectory}/light-1024.png`, fullPage: true })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const reducedDuration = await page.locator('.queue-page-slider').evaluate(element => Number.parseFloat(getComputedStyle(element).transitionDuration))
  expect(reducedDuration).toBeLessThan(0.001)

  await page.getByRole('button', { name: '历史', exact: true }).click()
  await expect(page.locator('.history-list .queue-lane')).toHaveCount(3)
  await expect(page.locator('.history-list .queue-lane').nth(2)).toContainText('昨日归档.pdf')
  await page.screenshot({ path: `${screenshotDirectory}/history-1024.png`, fullPage: true })

  await page.getByRole('button', { name: '娱乐功能' }).click()
  await page.getByRole('button', { name: '任务队列', exact: true }).click()
  await expect(page.getByText('Issue 看板', { exact: true })).toBeVisible()
})
