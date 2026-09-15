/**
 * Top command bar browser regression checks.
 *
 * Usage:
 * Verifies that the collapsed toolbar search only reserves its visible icon
 * width, leaving the former expansion area on the draggable top bar.
 */
import { expect, test } from '@playwright/test'

test('moves the persisted theme toggle from the top bar to the activity rail', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem('agent_editor_theme_mode', 'dark')
  })
  await page.goto('/')
  const userIdInput = page.getByRole('textbox', { name: '用户 ID' })
  if (await userIdInput.isVisible()) {
    await userIdInput.fill('theme-toggle-smoke')
    await page.getByRole('button', { name: '进入', exact: true }).click()
  }

  await expect(page.locator('.topbar .theme-toggle-button')).toHaveCount(0)
  const activityToggle = page.locator('.activity-bar > .theme-toggle-button')
  const homeButton = page.getByRole('button', { name: '主页' })
  await expect(activityToggle).toBeVisible()
  await expect.poll(async () => {
    const [toggleBox, homeBox] = await Promise.all([activityToggle.boundingBox(), homeButton.boundingBox()])
    return Boolean(
      toggleBox
      && homeBox
      && toggleBox.y < homeBox.y
      && Math.abs(toggleBox.width - homeBox.width) <= 1
      && Math.abs(toggleBox.height - homeBox.height) <= 1,
    )
  }).toBe(true)

  await activityToggle.click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await expect.poll(() => page.evaluate(() => localStorage.getItem('agent_editor_theme_mode'))).toBe('light')
  await page.screenshot({ path: testInfo.outputPath('theme-toggle-activity-light.png'), fullPage: true })

  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByRole('button', { name: '外观' }).click()
  await expect(page.locator('.settings-body .theme-toggle-button')).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('theme-toggle-removed-from-settings.png'), fullPage: true })
})

test('collapsed toolbar search releases its expansion area for window dragging', async ({ page }) => {
  await page.goto('/')
  const userIdInput = page.getByRole('textbox', { name: '用户 ID' })
  if (await userIdInput.isVisible()) {
    await userIdInput.fill('topbar-smoke')
    await page.getByRole('button', { name: '进入', exact: true }).click()
  }

  const searchCenter = page.locator('.search-center')
  await expect(searchCenter).toBeVisible()
  await expect.poll(async () => (await searchCenter.boundingBox())?.width ?? 0).toBeLessThanOrEqual(27)

  const collapsedBox = await searchCenter.boundingBox()
  const releasedPoint = await page.evaluate(({ x, y }) => {
    const target = document.elementFromPoint(x, y)
    return {
      topbar: Boolean(target?.closest('.topbar')),
      actions: Boolean(target?.closest('.actions')),
    }
  }, {
    x: Math.max(1, (collapsedBox?.x ?? 40) - 24),
    y: (collapsedBox?.y ?? 0) + (collapsedBox?.height ?? 26) / 2,
  })
  expect(releasedPoint).toEqual({ topbar: true, actions: false })

  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await expect.poll(async () => (await searchCenter.boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(249)
})

test('wraps the Agent sidebar in the workspace card shell', async ({ page }) => {
  await page.goto('/')
  const userIdInput = page.getByRole('textbox', { name: '用户 ID' })
  if (await userIdInput.isVisible()) {
    await userIdInput.fill('agent-card-smoke')
    await page.getByRole('button', { name: '进入', exact: true }).click()
  }

  await page.getByTitle('切换 Agent 面板').click()
  const agentCard = page.locator('.agent-col')
  const agentPanel = agentCard.locator('.agent-panel')
  const workspaceCard = page.locator('.main-shell.ide-panel')
  await expect(agentCard).toBeVisible()
  await expect.poll(async () => {
    const [agentRadius, workspaceRadius] = await Promise.all([
      agentCard.evaluate((element) => getComputedStyle(element).borderRadius),
      workspaceCard.evaluate((element) => getComputedStyle(element).borderRadius),
    ])
    return agentRadius === workspaceRadius
  }).toBe(true)
  await expect(agentCard).toHaveCSS('overflow', 'hidden')
  await expect(agentCard).toHaveCSS('border-top-width', '0px')
  await expect(workspaceCard).toHaveCSS('border-top-width', '0px')
  await expect(agentCard).toHaveCSS('box-shadow', /4px/)
  await expect(workspaceCard).toHaveCSS('box-shadow', /4px/)
  await expect(agentCard).toHaveCSS('margin-left', '12px')
  await expect(agentCard).toHaveCSS('margin-right', '12px')
  await expect(agentCard).toHaveCSS('margin-top', '12px')
  await expect(agentCard).toHaveCSS('margin-bottom', '12px')
  await expect(workspaceCard).toHaveCSS('margin-left', '12px')
  await expect(workspaceCard).toHaveCSS('margin-right', '12px')
  await expect(workspaceCard).toHaveCSS('margin-top', '12px')
  await expect(workspaceCard).toHaveCSS('margin-bottom', '12px')
  await expect.poll(async () => {
    const [agentBackground, workspaceBackground] = await Promise.all([
      agentPanel.evaluate((element) => getComputedStyle(element).backgroundColor),
      workspaceCard.evaluate((element) => getComputedStyle(element).backgroundColor),
    ])
    return agentBackground === workspaceBackground
  }).toBe(true)
})

test('resizes the sidebar browser from its left edge', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await page.goto('/')
  const userIdInput = page.getByRole('textbox', { name: '用户 ID' })
  if (await userIdInput.isVisible()) {
    await userIdInput.fill('browser-resize-smoke')
    await page.getByRole('button', { name: '进入', exact: true }).click()
  }

  await page.getByRole('button', { name: '打开或收起右侧浏览器' }).click()
  const browserSidebar = page.locator('.browser-sidebar-content')
  await expect(browserSidebar).toBeVisible()
  const browserWidthBefore = (await browserSidebar.boundingBox())?.width ?? 0
  const browserResizer = page.getByRole('separator', { name: 'Resize browser sidebar' })
  await expect(browserResizer).toBeVisible()
  const browserHandleBox = await browserResizer.boundingBox()
  await page.mouse.move(
    (browserHandleBox?.x ?? 0) + (browserHandleBox?.width ?? 4) / 2,
    (browserHandleBox?.y ?? 0) + (browserHandleBox?.height ?? 400) / 2,
  )
  await page.mouse.down()
  await page.mouse.move((browserHandleBox?.x ?? 0) - 80, (browserHandleBox?.y ?? 0) + (browserHandleBox?.height ?? 400) / 2)
  await page.mouse.up()

  await expect.poll(async () => (await browserSidebar.boundingBox())?.width ?? 0).toBeGreaterThan(browserWidthBefore + 60)
  await page.screenshot({ path: testInfo.outputPath('browser-sidebar-resized.png'), fullPage: true })
})

test('opens the GitHub repository in the existing browser sidebar', async ({ page, context }, testInfo) => {
  await page.setViewportSize({ width: 1400, height: 900 })
  await page.goto('/')
  const userIdInput = page.getByRole('textbox', { name: '用户 ID' })
  if (await userIdInput.isVisible()) {
    await userIdInput.fill('github-sidebar-smoke')
    await page.getByRole('button', { name: '进入', exact: true }).click()
  }

  const pageCount = context.pages().length
  await page.getByTitle('GitHub').click()

  await expect(page.locator('.browser-sidebar-content')).toBeVisible()
  expect(context.pages()).toHaveLength(pageCount)
  await page.screenshot({ path: testInfo.outputPath('github-browser-sidebar.png'), fullPage: true })
})

test('mobile sidebars float and the latest one replaces the previous overlay', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 600, height: 820 })
  await page.route('**/health', (route) => route.fulfill({ status: 200, body: '{"status":"ok"}' }))
  await page.route((url) => url.pathname === '/settings/profile', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      user_id: 'mobile-sidebar-smoke', knowledge_dir: 'D:/Knowledge', active_library_id: 'mobile-library',
      active_knowledge_library: { library_id: 'mobile-library', user_id: 'mobile-sidebar-smoke', name: 'knowledge', knowledge_dir: 'D:/Knowledge', is_active: true, created_at: '', updated_at: '' },
      knowledge_libraries: [], created_at: '', updated_at: '',
    }),
  }))
  await page.route((url) => url.pathname === '/knowledge/files', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      tree: [{ name: 'report.pdf', path: 'docs/report.pdf', isDir: false }],
    }),
  }))
  await page.route((url) => url.pathname === '/search', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      query: 'report',
      selected_sources: ['files', 'library', 'components', 'literature'],
      fulltext: true,
      semantic: false,
      results: [{
        id: 'docs/report.pdf',
        source: 'files',
        title: 'report.pdf',
        snippet: '',
        locator: 'docs/report.pdf',
        updated_at: '',
        score: 0.92,
        matched_modes: ['title'],
        item: { name: 'report.pdf', path: 'docs/report.pdf', isDir: false },
      }],
      groups: {
        files: [{
          id: 'docs/report.pdf', source: 'files', title: 'report.pdf', snippet: '', locator: 'docs/report.pdf',
          updated_at: '', score: 0.92, matched_modes: ['title'], item: { name: 'report.pdf', path: 'docs/report.pdf', isDir: false },
        }],
        library: [], components: [], literature: [],
      },
      counts: { files: 1, library: 0, components: 0, literature: 0 },
      total: 1,
    }),
  }))
  await page.route((url) => url.pathname === '/knowledge/files/preview', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      path: 'docs/report.pdf',
      kind: 'pdf',
      raw_url: '/knowledge/raw/report.pdf',
      content: 'Extracted PDF text.',
      mtime: '2026-08-29T00:00:00',
      size: 128,
      extension: '.pdf',
      readonly: true,
    }),
  }))
  await page.goto('/')
  const userIdInput = page.getByRole('textbox', { name: '用户 ID' })
  await expect(userIdInput.or(page.locator('.topbar'))).toBeVisible()
  if (await userIdInput.isVisible()) {
    await userIdInput.fill('mobile-sidebar-smoke')
    await page.getByRole('button', { name: '进入', exact: true }).click()
  }
  await expect(page.locator('.topbar')).toBeVisible()
  await page.evaluate(() => {
    const grid = document.querySelector('.workspace-grid')
    let mobile = grid?.classList.contains('mobile-main-layout') ?? false
    ;(window as typeof window & { __mobileLayoutFlipCount?: number }).__mobileLayoutFlipCount = 0
    new MutationObserver(() => {
      const nextMobile = grid?.classList.contains('mobile-main-layout') ?? false
      if (nextMobile !== mobile) {
        mobile = nextMobile
        const target = window as typeof window & { __mobileLayoutFlipCount?: number }
        target.__mobileLayoutFlipCount = (target.__mobileLayoutFlipCount ?? 0) + 1
      }
    }).observe(grid!, { attributes: true, attributeFilter: ['class'] })
  })

  const browserButton = page.getByRole('button', { name: '打开或收起右侧浏览器' })
  await expect(browserButton).toBeVisible()
  await browserButton.click()

  const browserSidebar = page.locator('.browser-sidebar-content')
  await expect(browserSidebar).toBeVisible()
  await expect(browserSidebar).toHaveCSS('position', 'absolute')

  await page.getByTitle('切换 Agent 面板').click()
  const agentSidebar = page.locator('.agent-col')
  await expect(agentSidebar).toBeVisible()
  await expect(agentSidebar).toHaveCSS('position', 'absolute')
  await expect(browserButton).not.toHaveClass(/active/)
  await expect(browserSidebar).toHaveCSS('opacity', '0')

  await page.getByRole('button', { name: 'Files' }).click()
  const fileSidebar = page.locator('.file-col')
  await expect(fileSidebar).toBeVisible()
  await expect(agentSidebar).toHaveCSS('opacity', '0')
  await page.screenshot({ path: testInfo.outputPath('mobile-latest-sidebar.png'), fullPage: true })

  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await page.locator('.page-variant .search-input').fill('report')
  await page.locator('.search-box-submit').click()
  const searchResult = page.locator('.unified-result-row')
  await expect(searchResult).toBeVisible()
  await page.waitForTimeout(300)
  await searchResult.click()
  const searchPreview = page.locator('.editor-sidebar-content')
  await expect(searchPreview).toHaveCSS('position', 'fixed')
  await expect(searchPreview).toHaveCSS('opacity', '1')
  await expect(searchPreview.locator('.pdf-viewer')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('mobile-search-preview.png'), fullPage: true })

  await page.getByTitle('切换 Agent 面板').click()
  await expect(searchPreview).toHaveCSS('opacity', '0')
  await page.waitForTimeout(500)
  await expect.poll(() => page.evaluate(
    () => (window as typeof window & { __mobileLayoutFlipCount?: number }).__mobileLayoutFlipCount ?? 0,
  )).toBe(0)
})

test('keeps the library name visible beside ingestion progress', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('agent_editor_profile', JSON.stringify({
      userId: '1',
      knowledgeDir: 'D:/Knowledge',
      activeLibraryId: 'knowledge-library',
      knowledgeLibraries: [{
        libraryId: 'knowledge-library',
        name: 'knowledge',
        knowledgeDir: 'D:/Knowledge',
        libraryStorageDir: '.metaweave/library',
        isActive: true,
      }],
    }))
  })
  await page.goto('/')

  const libraryName = page.locator('.library-name-input')
  await expect(libraryName).toBeVisible()
  await libraryName.evaluate((element) => {
    const input = element as HTMLInputElement
    input.value = 'knowledge'
    input.dispatchEvent(new Event('input', { bubbles: true }))

    const brand = input.closest<HTMLElement>('.brand')
    if (brand) {
      brand.style.width = '230px'
      brand.style.maxWidth = '230px'
      brand.style.flexBasis = '230px'
    }
    const progress = document.createElement('div')
    progress.className = 'ingestion-progress'
    progress.style.flex = '0 0 140px'
    progress.style.width = '140px'
    progress.innerHTML = '<span class="ingestion-progress-track"></span><span class="ingestion-progress-percent">33%</span>'
    brand?.append(progress)
  })

  await expect.poll(async () => libraryName.evaluate((element) => {
    const input = element as HTMLInputElement
    return input.clientWidth >= input.scrollWidth
  })).toBe(true)
})
