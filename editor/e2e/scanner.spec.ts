/**
 * Scanner page visual and interaction smoke test.
 *
 * Uses deterministic network fixtures around the real Vue components, then
 * captures the requested 1024/768/480 layouts and exercises upload-to-result.
 */
import { expect, test, type Page } from '@playwright/test'

const screenshotDirectory = '../docs/screenshots/scanner'

/** Install the smallest stable backend contract needed by the scanner page. */
async function mockScannerWorkspace(page: Page, autoFinish = true): Promise<void> {
  let uploadedAt = 0
  let cancelled = false
  const record = (status: 'running' | 'cancelled' | 'finished') => ({
    scan_id: 'scan-smoke', user_id: 'scanner-smoke', library_id: 'default', source_kind: 'file',
    source_name: '课堂笔记.docx', source_path: '.mw/scan/scan-smoke/source/课堂笔记.docx', source_url: '', size: 28,
    ocr_enabled: true, status, stage: status === 'running' ? 'extract' : status === 'cancelled' ? 'cancelled' : 'completed',
    stage_label: status === 'running' ? '正在解析文件内容' : status === 'cancelled' ? '已终止' : '解析完成', progress: status === 'running' ? 44 : status === 'cancelled' ? 0 : 100,
    no_ocr_markdown: status === 'finished' ? '# No OCR\n\n原始文字\n\n![image1.png](./assets/image1.png)' : '',
    ocr_markdown: status === 'finished' ? '# OCR\n\n识别文字' : '', assets: [], error: '',
    source_text: null,
    created_at: '2026-09-08T06:20:00Z', updated_at: '2026-09-08T06:21:00Z',
    finished_at: status === 'running' ? null : '2026-09-08T06:21:00Z',
  })
  const currentStatus = (): 'running' | 'cancelled' | 'finished' => cancelled ? 'cancelled' : autoFinish && Date.now() - uploadedAt > 1_000 ? 'finished' : 'running'

  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.pathname === '/health') return route.fulfill({ status: 200, contentType: 'text/plain', body: 'ok' })
    if (url.pathname === '/settings/models/status' || url.pathname === '/settings/models/management') return json({ models: [] })
    if (url.pathname === '/settings/profile') return json({
      user_id: 'scanner-smoke', knowledge_dir: 'D:/Knowledge', active_library_id: 'default', editor_image_assets_dir: './assets/',
      knowledge_libraries: [{ library_id: 'default', name: '扫描验收库', knowledge_dir: 'D:/Knowledge', library_storage_dir: '.mw/library', is_active: true }],
    })
    if (url.pathname === '/knowledge/files') return json({ tree: [] })
    if (url.pathname === '/knowledge/files/preview') return json({ kind: 'document', path: '.mw/scan/scan-smoke/source/课堂笔记.docx', html: '<p>课堂原始内容</p>', readonly: true })
    if (url.pathname === '/knowledge/files/raw') return route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64'),
    })
    if (url.pathname === '/knowledge/files/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': smoke\n\n' })
    if (url.pathname === '/sessions' || url.pathname === '/todo/list' || url.pathname === '/automation/list') return json([])
    if (url.pathname === '/favorites') return json({ favorites: uploadedAt ? [{ favorite_id: 'fav-scan', user_id: 'scanner-smoke', library_id: 'default', target_type: 'scanner', target_id: 'scan-smoke', created_at: '2026-09-08T06:22:00Z' }] : [] })
    if (url.pathname === '/privacy') return json({ privacy: [] })
    if (url.pathname === '/scanner/files' && request.method() === 'POST') { uploadedAt = Date.now(); return json(record('running')) }
    if (url.pathname === '/scanner' && request.method() === 'GET') return json({ scans: uploadedAt ? [record(currentStatus())] : [] })
    if (url.pathname === '/scanner/scan-smoke/cancel' && request.method() === 'POST') { cancelled = true; return json(record('cancelled')) }
    if (url.pathname === '/scanner/scan-smoke' && request.method() === 'GET') return json(record(currentStatus()))
    if (url.pathname.endsWith('/draft') || url.pathname.endsWith('/source')) return json(record('finished'))
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') return json({})
    return route.continue()
  })
  await page.addInitScript(() => localStorage.setItem('agent_editor_profile', JSON.stringify({
    userId: 'scanner-smoke', knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default',
    knowledgeLibraries: [{ libraryId: 'default', name: '扫描验收库', knowledgeDir: 'D:/Knowledge', libraryStorageDir: '.mw/library', isActive: true }],
  })))
}

/** Open scanner through its real top-level activity entry below Agent. */
async function openScanner(page: Page): Promise<void> {
  await page.getByRole('button', { name: '扫描器', exact: true }).click()
  await expect(page.locator('.scanner-view')).toBeVisible()
}

/** Assert the scanner root does not introduce horizontal overflow. */
async function expectNoScannerOverflow(page: Page): Promise<void> {
  const overflow = await page.locator('.scanner-view').evaluate((element) => element.scrollWidth - element.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
}

test('scanner upload, result editing, examples, and responsive layouts', async ({ page }) => {
  test.setTimeout(60_000)
  await mockScannerWorkspace(page)
  await page.setViewportSize({ width: 1024, height: 820 })
  await page.goto('/')
  await openScanner(page)

  await expect(page.locator('.scanner-rail-titlebar')).toContainText('扫描器')
  await expect(page.locator('.scanner-example').first()).toBeVisible()
  expect(await page.locator('.scanner-example').count()).toBeLessThanOrEqual(3)
  await expect(page.getByRole('button', { name: '上传文件', exact: true })).toBeVisible()
  const surfaceChooserPromise = page.waitForEvent('filechooser')
  await page.locator('.scanner-drop-zone').click({ position: { x: 120, y: 120 } })
  await (await surfaceChooserPromise).setFiles([])
  const uploadGeometry = await page.locator('.scanner-drop-zone').evaluate((zone) => {
    const button = zone.querySelector('button:not(.scanner-settings)')?.getBoundingClientRect()
    const logo = zone.querySelector('.scanner-logo')?.getBoundingClientRect()
    const root = zone.getBoundingClientRect()
    return { root: [root.left, root.top, root.right, root.bottom], button: button && [button.left, button.top, button.right, button.bottom], logo: logo && [logo.left, logo.top, logo.right, logo.bottom] }
  })
  expect(uploadGeometry.button, JSON.stringify(uploadGeometry)).toBeTruthy()
  expect(uploadGeometry.button?.[0], JSON.stringify(uploadGeometry)).toBeGreaterThanOrEqual(0)
  expect(uploadGeometry.button?.[0], JSON.stringify(uploadGeometry)).toBeLessThan(1024)
  await expect(page.getByRole('button', { name: '上传文件', exact: true })).toBeInViewport()
  await expect(page.locator('.scanner-logo')).toBeInViewport()
  const baseBorder = await page.locator('.scanner-example').first().evaluate((element) => getComputedStyle(element).borderColor)
  await page.locator('.scanner-example').first().hover()
  const hoverStyle = await page.locator('.scanner-example').first().evaluate((element) => ({
    borderColor: getComputedStyle(element).borderColor,
    boxShadow: getComputedStyle(element).boxShadow,
    imageLayer: getComputedStyle(element.querySelector('.scanner-example-image')!).zIndex,
    copyLayer: getComputedStyle(element.querySelector('.scanner-example-copy')!).zIndex,
  }))
  expect(hoverStyle.borderColor).not.toBe(baseBorder)
  expect(hoverStyle.boxShadow).not.toBe('none')
  expect(Number(hoverStyle.copyLayer)).toBeGreaterThan(Number(hoverStyle.imageLayer))
  const firstPage = await page.locator('.scanner-example-copy strong').allTextContents()
  await page.waitForTimeout(3_800)
  const secondPage = await page.locator('.scanner-example-copy strong').allTextContents()
  expect(secondPage).not.toEqual(firstPage)
  const uploadOverflow = await page.locator('.scanner-start').evaluate((element) => element.scrollHeight - element.clientHeight)
  expect(uploadOverflow).toBeLessThanOrEqual(1)
  await page.getByRole('button', { name: '网页链接', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '解析网页链接' })).toBeVisible()
  expect(await page.locator('.scanner-url-dialog').evaluate((element) => getComputedStyle(element).borderTopWidth)).toBe('4px')
  await page.screenshot({ path: `${screenshotDirectory}/url-form-1024.png`, fullPage: true })
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  if (await page.locator('.scanner-history-rail').evaluate((element) => element.classList.contains('open'))) {
    await page.getByRole('button', { name: '收起侧边栏' }).click()
  }
  await expect(page.getByRole('button', { name: '展开侧边栏' })).toBeVisible()
  await page.getByRole('button', { name: '展开侧边栏' }).click()
  await page.waitForTimeout(250)
  await expectNoScannerOverflow(page)
  await page.screenshot({ path: `${screenshotDirectory}/idle-1024.png`, fullPage: true })
  await page.getByRole('button', { name: '切换为浅色主题' }).click()
  await page.screenshot({ path: `${screenshotDirectory}/idle-light-1024.png`, fullPage: true })
  await page.getByRole('button', { name: '切换为深色主题' }).click()

  for (const viewport of [{ name: '768', width: 768, height: 820 }, { name: '480', width: 480, height: 820 }]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    if (await page.locator('.scanner-history-rail').evaluate((element) => element.classList.contains('open'))) {
      await page.getByRole('button', { name: '收起侧边栏' }).click()
    }
    const mobileLogo = await page.locator('.scanner-logo').boundingBox()
    const mobileZone = await page.locator('.scanner-drop-zone').boundingBox()
    const mobileMain = await page.locator('.scanner-main').boundingBox()
    expect(mobileLogo?.y, JSON.stringify(mobileLogo)).toBeGreaterThanOrEqual(0)
    expect(mobileLogo?.y, JSON.stringify({ mobileLogo, mobileZone })).toBeGreaterThanOrEqual(mobileZone?.y ?? 0)
    expect(mobileZone?.y, JSON.stringify({ mobileZone, mobileMain })).toBeGreaterThanOrEqual(mobileMain?.y ?? 0)
    expect((mobileLogo?.y ?? 0) + (mobileLogo?.height ?? 0), JSON.stringify(mobileLogo)).toBeLessThanOrEqual(viewport.height)
    await expect(page.locator('.scanner-logo')).toBeInViewport()
    expect(await page.locator('.scanner-start').evaluate((element) => element.scrollHeight - element.clientHeight)).toBeLessThanOrEqual(1)
    await expectNoScannerOverflow(page)
    await page.screenshot({ path: `${screenshotDirectory}/idle-${viewport.name}.png`, fullPage: true })
  }

  await page.setViewportSize({ width: 1024, height: 820 })
  const chooserPromise = page.waitForEvent('filechooser')
  if (await page.getByRole('button', { name: '展开侧边栏' }).isVisible()) await page.getByRole('button', { name: '展开侧边栏' }).click()
  await page.getByRole('button', { name: '上传解析', exact: true }).click()
  const chooser = await chooserPromise
  await chooser.setFiles({ name: '课堂笔记.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: Buffer.from('docx-smoke') })
  await expect(page.locator('.scanner-running')).toBeVisible()
  await expect(page.locator('.scanner-history-card .scanner-history-status')).toHaveText('解析中')
  expect(await page.locator('.scanner-history-card').evaluate((element) => getComputedStyle(element).animationName)).toContain('scanner-history-enter')
  await page.screenshot({ path: `${screenshotDirectory}/running-1024.png`, fullPage: true })
  await expect(page.locator('.scanner-result')).toBeVisible({ timeout: 8_000 })
  await expect(page.locator('.scanner-source-pane .editor-pane-toolbar')).toBeVisible()
  await expect(page.locator('.scanner-markdown-pane .editor-pane-toolbar')).toBeVisible()
  await expect(page.locator('.scanner-source-pane .editor-mode-switch')).toBeVisible()
  await expect(page.locator('.scanner-markdown-pane .editor-mode-switch')).toBeVisible()
  await expect(page.getByRole('button', { name: 'OCR', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'No OCR', exact: true })).toBeVisible()
  if (!await page.locator('.scanner-history-rail').evaluate((element) => element.classList.contains('open'))) {
    await page.getByRole('button', { name: '展开侧边栏' }).click()
  }
  const uploadButtonBox = await page.getByRole('button', { name: '上传解析', exact: true }).boundingBox()
  const historyCardBox = await page.locator('.scanner-history-card').boundingBox()
  expect(
    Math.abs((uploadButtonBox?.width ?? 0) - (historyCardBox?.width ?? 0)),
    JSON.stringify({ uploadButtonBox, historyCardBox }),
  ).toBeLessThanOrEqual(1)
  await page.getByRole('button', { name: 'No OCR', exact: true }).hover()
  await page.waitForTimeout(220)
  const ocrHover = await page.getByRole('button', { name: 'No OCR', exact: true }).evaluate((element) => ({
    background: getComputedStyle(element).backgroundColor,
    shadow: getComputedStyle(element).boxShadow,
  }))
  expect(ocrHover.background).toBe('rgba(0, 0, 0, 0)')
  expect(ocrHover.shadow).toBe('none')
  await page.screenshot({ path: `${screenshotDirectory}/result-1024.png`, fullPage: true })
  const sourceWidthBefore = (await page.locator('.scanner-source-pane').boundingBox())?.width ?? 0
  const divider = await page.locator('.scanner-pane-divider').boundingBox()
  expect(divider).toBeTruthy()
  await page.mouse.move((divider?.x ?? 0) + 3, (divider?.y ?? 0) + 120)
  await page.mouse.down()
  await page.mouse.move((divider?.x ?? 0) + 83, (divider?.y ?? 0) + 120)
  await page.mouse.up()
  const sourceWidthAfter = (await page.locator('.scanner-source-pane').boundingBox())?.width ?? 0
  expect(sourceWidthAfter).toBeGreaterThan(sourceWidthBefore + 50)
  const movedDivider = await page.locator('.scanner-pane-divider').boundingBox()
  await page.mouse.move((movedDivider?.x ?? 0) + 3, (movedDivider?.y ?? 0) + 120)
  await page.mouse.down()
  await page.mouse.move((divider?.x ?? 0) + 3, (divider?.y ?? 0) + 120)
  await page.mouse.up()
  await page.getByRole('button', { name: '收起侧边栏' }).click()
  const expandButtonBox = await page.getByRole('button', { name: '展开侧边栏' }).boundingBox()
  const backButtonBox = await page.getByRole('button', { name: '返回上传页' }).boundingBox()
  expect(
    Math.abs((expandButtonBox?.y ?? 0) - (backButtonBox?.y ?? 0)),
    JSON.stringify({ expandButtonBox, backButtonBox }),
  ).toBeLessThanOrEqual(1)
  await page.getByRole('button', { name: '展开侧边栏' }).click()
  await expectNoScannerOverflow(page)

  await page.getByRole('button', { name: 'No OCR', exact: true }).click()
  const docxImage = page.locator('.scanner-markdown-pane img[alt="image1.png"]')
  await expect(docxImage).toBeVisible()
  await expect.poll(() => docxImage.evaluate((image: HTMLImageElement) => [image.complete, image.naturalWidth, image.naturalHeight])).toEqual([true, 1, 1])
  await expect(page.locator('.scanner-markdown-pane')).not.toContainText('DOCX 图片引用')
  await page.setViewportSize({ width: 768, height: 820 })
  await expectNoScannerOverflow(page)
  await page.screenshot({ path: `${screenshotDirectory}/result-768.png`, fullPage: true })
  await page.setViewportSize({ width: 480, height: 820 })
  await expectNoScannerOverflow(page)
  await page.screenshot({ path: `${screenshotDirectory}/result-480.png`, fullPage: true })

  await page.setViewportSize({ width: 1024, height: 820 })
  await page.getByRole('button', { name: '我的', exact: true }).click()
  await page.getByRole('button', { name: '我的收藏', exact: true }).click()
  await expect(page.locator('.favorites-view')).toBeVisible()
  await page.getByLabel('收藏分类').getByRole('button', { name: '扫描器', exact: true }).click()
  await expect(page.locator('.scanner-favorites-panel .scanner-history-card')).toHaveCount(1)
  await page.screenshot({ path: `${screenshotDirectory}/favorites-1024.png`, fullPage: true })
})

test('scanner running task exposes a responsive immediate stop control', async ({ page }) => {
  test.setTimeout(30_000)
  await mockScannerWorkspace(page, false)
  await page.setViewportSize({ width: 1024, height: 820 })
  await page.goto('/')
  await openScanner(page)

  const chooserPromise = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: '上传解析', exact: true }).click()
  await (await chooserPromise).setFiles({ name: '并发任务.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: Buffer.from('queue-smoke') })
  const stopButton = page.locator('.scanner-stop-button')
  await expect(stopButton).toBeVisible()

  for (const viewport of [{ name: '1024', width: 1024 }, { name: '768', width: 768 }, { name: '480', width: 480 }]) {
    await page.setViewportSize({ width: viewport.width, height: 820 })
    if (!await page.locator('.scanner-history-rail').evaluate((element) => element.classList.contains('open'))) {
      await page.getByRole('button', { name: '展开侧边栏' }).click()
    }
    await page.waitForTimeout(250)
    await expect(stopButton).toBeInViewport()
    await expectNoScannerOverflow(page)
    await page.screenshot({ path: `${screenshotDirectory}/queue-running-${viewport.name}.png`, fullPage: true })
  }

  await page.setViewportSize({ width: 1024, height: 820 })
  await stopButton.click()
  await expect(page.locator('.scanner-history-status')).toHaveText('已终止')
  await expect(stopButton).toHaveCount(0)
})

test('blank-image-docx-upload-reaches-finished-result', async ({ page }) => {
  await mockScannerWorkspace(page)
  await page.setViewportSize({ width: 1024, height: 820 })
  await page.goto('/')
  await openScanner(page)

  const chooserPromise = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: '上传解析', exact: true }).click()
  const chooser = await chooserPromise
  await chooser.setFiles({
    name: '空白图片.docx',
    mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    buffer: Buffer.from('blank-image-docx-smoke'),
  })

  await expect(page.locator('.scanner-running')).toBeVisible()
  await expect(page.locator('.scanner-result')).toBeVisible({ timeout: 8_000 })
  await expect(page.getByRole('button', { name: 'OCR', exact: true })).toBeVisible()
  await page.screenshot({ path: `${screenshotDirectory}/blank-image-result-1024.png`, fullPage: true })
})
