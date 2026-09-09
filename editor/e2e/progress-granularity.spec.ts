/**
 * Progress precision responsive browser smoke.
 *
 * Renders backend-shaped fractional scanner and ingestion states, then checks
 * the scanner surface, ingestion table, and compact top bar at three widths.
 */
import path from 'node:path'

import { expect, test } from '@playwright/test'

test('shows truthful stages and one-decimal progress across all three surfaces', async ({ page }) => {
  const profile = { userId: 'progress-smoke', knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default', knowledgeLibraries: [] }
  const scan = {
    scan_id: 'scan-1', user_id: profile.userId, library_id: 'default', source_kind: 'file',
    source_name: 'scan.png', source_path: '.mw/scan/scan-1/source/scan.png', source_url: '', size: 1024,
    ocr_enabled: true, status: 'running', stage: 'ocr_inference',
    stage_label: '正在运行文字识别模型 · 20/35 行 · 已裁决 6/8', progress: 67.4,
    no_ocr_markdown: '', ocr_markdown: '', assets: [], error: '', source_text: null,
    created_at: '2026-09-09T10:00:00Z', updated_at: '2026-09-09T10:00:01Z', finished_at: null,
  }
  const job = {
    job_id: 'ingest-1', user_id: profile.userId, library_id: 'default', path: 'papers/paper.pdf',
    name: 'paper.pdf', pipeline: 'pdf', status: 'running', stage: 'ocr_inference',
    stage_label: '正在分析版面、文字、表格与公式', progress: 37.26,
    stage_current: 3, stage_total: 8, size: 2048, mtime: '2026-09-09 18:00', message: '', error: '',
    created_at: '2026-09-09T10:00:00Z', started_at: '2026-09-09T10:00:01Z', finished_at: null,
    updated_at: '2026-09-09T10:00:02Z',
  }
  await page.addInitScript((value) => localStorage.setItem('agent_editor_profile', JSON.stringify(value)), profile)
  await page.route('**/*', async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname === '/knowledge/files/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
    if (!['fetch', 'xhr'].includes(request.resourceType())) return route.continue()
    if (pathname === '/health') return route.fulfill({ json: { ok: true } })
    if (pathname === '/scanner') return route.fulfill({ json: { scans: [scan] } })
    if (pathname === '/scanner/scan-1') return route.fulfill({ json: scan })
    if (pathname === '/knowledge/ingestion/jobs') return route.fulfill({ json: { jobs: [job] } })
    if (pathname === '/settings/profile') return route.fulfill({ json: { user_id: profile.userId, knowledge_dir: profile.knowledgeDir, knowledge_libraries: [] } })
    if (pathname === '/knowledge/files') return route.fulfill({ json: { tree: [] } })
    if (pathname === '/sessions' || pathname === '/todo/list' || pathname === '/automation/list') return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '扫描器' }).click()
  await page.getByText('scan.png', { exact: true }).click()
  await expect(page.getByText('正在运行文字识别模型 · 20/35 行 · 已裁决 6/8', { exact: true })).toBeVisible()
  await expect(page.getByText('67.4%', { exact: true })).toBeVisible()
  for (const width of [1024, 768, 480]) {
    await page.setViewportSize({ width, height: 820 })
    await page.screenshot({ path: path.resolve(`../docs/acceptance/scanner-progress-${width}.png`), fullPage: true })
    await expect.poll(() => page.locator('.scanner-view').evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
  }

  await page.getByRole('button', { name: '入库进度' }).click()
  await expect(page.locator('.ingestion-progress-cell').getByText('37.3%', { exact: true })).toBeVisible()
  await expect(page.locator('.topbar').getByText('37.3%', { exact: true })).toBeVisible()

  for (const width of [1024, 768, 480]) {
    await page.setViewportSize({ width, height: 820 })
    await page.screenshot({ path: path.resolve(`../docs/acceptance/progress-granularity-${width}.png`), fullPage: true })
    await expect.poll(() => page.locator('.ingestion-page').evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1)
  }
})
