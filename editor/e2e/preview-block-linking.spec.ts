/**
 * Scanner preview block-linking browser smoke.
 *
 * Verifies image-space and Markdown-semantic blocks share hover/selection and
 * that the Markdown block layer disappears when its pane leaves Preview.
 */
import path from 'node:path'

import { expect, test } from '@playwright/test'

test('links image and markdown blocks only while panes are in preview', async ({ page }) => {
  const userId = 'block-smoke'
  const scan = {
    scan_id: 'scan-blocks', user_id: userId, library_id: 'default', source_kind: 'file',
    source_name: 'page.png', source_path: '.mw/scan/scan-blocks/source/page.png', source_url: '', size: 1024,
    ocr_enabled: true, status: 'finished', stage: 'completed', stage_label: '解析完成', progress: 100,
    no_ocr_markdown: '![page](./assets/page.png)', ocr_markdown: '# Heading\n\nHello world', assets: [], error: '', source_text: null,
    ocr_blocks: [
      { page: 1, type: 'doc_title', content: 'Heading', bbox: [60, 40, 420, 120], id: 1, order: 0, page_width: 800, page_height: 600 },
      { page: 1, type: 'text', content: 'Hello world', bbox: [80, 180, 700, 300], id: 2, order: 1, page_width: 800, page_height: 600 },
    ],
    created_at: '2026-09-09T10:00:00Z', updated_at: '2026-09-09T10:00:01Z', finished_at: '2026-09-09T10:00:01Z',
  }
  await page.addInitScript((profile) => localStorage.setItem('agent_editor_profile', JSON.stringify(profile)), {
    userId, knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default', knowledgeLibraries: [],
  })
  await page.route('**/*', async (route) => {
    const request = route.request()
    const requestUrl = new URL(request.url())
    const pathname = requestUrl.pathname
    if (pathname === '/knowledge/files/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
    if (!['fetch', 'xhr'].includes(request.resourceType())) return route.continue()
    if (pathname === '/health') return route.fulfill({ json: { ok: true } })
    if (pathname === '/scanner') return route.fulfill({ json: { scans: [scan] } })
    if (pathname === '/scanner/scan-blocks') return route.fulfill({ json: scan })
    if (pathname === '/knowledge/files/preview') return route.fulfill({ json: {
      path: scan.source_path, kind: 'image', data_url: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="800" height="600"%3E%3Crect width="800" height="600" fill="white"/%3E%3C/svg%3E',
      mtime: '', size: 1024, extension: '.png', readonly: true,
    } })
    if (pathname === '/settings/profile') return route.fulfill({ json: { user_id: userId, knowledge_dir: 'D:/Knowledge', knowledge_libraries: [] } })
    if (pathname === '/knowledge/files') return route.fulfill({ json: { tree: [] } })
    if (pathname === '/sessions' || pathname === '/todo/list' || pathname === '/automation/list') return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '扫描', exact: true }).click()
  await page.getByRole('button', { name: '扫描器', exact: true }).click()
  await page.getByText('page.png', { exact: true }).click()
  const leftBlock = page.locator('.scanner-source-pane rect[data-block-id="1:1"]')
  const rightBlock = page.locator('.scanner-markdown-pane [data-ocr-block-id="1:1"]')
  await expect(leftBlock).toBeVisible()
  await expect(rightBlock).toBeVisible()
  const image = page.locator('.scanner-source-pane .previewer-image')
  const beforeImage = await image.boundingBox()
  const beforeBlock = await leftBlock.boundingBox()
  expect(beforeImage && beforeBlock).toBeTruthy()
  expect((beforeBlock!.x - beforeImage!.x) / beforeImage!.width).toBeCloseTo(60 / 800, 2)
  await page.locator('.scanner-source-pane .previewer-stage').hover({ position: { x: 10, y: 10 } })
  await page.mouse.wheel(0, -100)
  const afterImage = await image.boundingBox()
  const afterBlock = await leftBlock.boundingBox()
  expect(afterImage && afterBlock).toBeTruthy()
  expect((afterBlock!.x - afterImage!.x) / afterImage!.width).toBeCloseTo(60 / 800, 2)
  expect(afterBlock!.width / afterImage!.width).toBeCloseTo(360 / 800, 2)
  await leftBlock.hover()
  await expect(rightBlock).toHaveClass(/active/u)
  await leftBlock.click()
  await page.mouse.move(0, 0)
  await expect(rightBlock).toHaveClass(/locked/u)

  for (const width of [1024, 768, 480]) {
    await page.setViewportSize({ width, height: 820 })
    await page.screenshot({ path: path.resolve(`../docs/acceptance/preview-block-linking-${width}.png`), fullPage: true })
  }

  await page.locator('.scanner-markdown-pane').getByRole('button', { name: '编辑' }).click()
  await expect(page.locator('.scanner-markdown-pane [data-ocr-block-id]')).toHaveCount(0)
  await expect(leftBlock).toBeVisible()
})
