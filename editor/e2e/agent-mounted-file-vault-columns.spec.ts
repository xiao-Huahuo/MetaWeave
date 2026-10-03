/*
 * Agent mounted-file and vault dynamic-column browser smoke tests.
 *
 * Usage:
 * Verifies the real workspace surfaces with mocked network data, including
 * encoded knowledge links, editor-sidebar navigation, and per-type vault columns.
 */
import { expect, test, type Page } from '@playwright/test'

const profile = {
  user_id: 'e2e-user',
  knowledge_dir: 'D:/Knowledge',
  active_library_id: 'default',
  knowledge_libraries: [{ library_id: 'default', name: 'Default', knowledge_dir: 'D:/Knowledge', is_active: true }],
}

const mountedFileName = '原神阴间地图汇总报告.md'
const mountedFilePath = `文档/${mountedFileName}`
const sourceFilePath = '资料/冬冬国.md'

const mountedSearchResults = {
  K1: {
    source_uri: sourceFilePath,
    content: '测试来源',
    search_result: {
      id: sourceFilePath, source: 'files', title: '冬冬国.md', snippet: '测试来源', locator: sourceFilePath,
      updated_at: '', score: 1, matched_modes: ['title'],
      item: { name: '冬冬国.md', path: sourceFilePath, isDir: false, size: 1024 },
    },
  },
  K2: {
    source_uri: 'https://example.com/knowledge-book', content: '图书馆来源',
    search_result: {
      id: 'book-1', source: 'library', title: '知识手册', snippet: '图书馆来源', locator: 'https://example.com/knowledge-book',
      updated_at: '', score: 0.9, matched_modes: ['title'],
      item: {
        item_id: 'book-1', user_id: 'e2e-user', library_id: 'default', parent_id: '', item_type: 'book',
        content_type: 'knowledge_file', title: '知识手册', display_title: '知识手册', description: '',
        source_path: '资料/知识手册.pdf', source_url: '', source_name: '知识手册.pdf', source_mime: 'application/pdf',
        source_size: 2048, source_mtime: '', source_exists: true, cover_mode: 'title', cover_asset_id: '',
        cover_asset: null, tags: [], child_count: 0, index_status: 'indexed', graph_status: 'graphed', created_at: '', updated_at: '',
      },
    },
  },
  K3: {
    source_uri: 'component://SearchPanel', content: '组件来源',
    search_result: {
      id: 'SearchPanel.vue', source: 'components', title: 'SearchPanel', snippet: '组件来源', locator: 'SearchPanel.vue',
      updated_at: '', score: 0.8, matched_modes: ['title'],
      item: {
        component_id: 'SearchPanel.vue', user_id: 'e2e-user', title: 'SearchPanel', tag: 'cards', source_format: 'vue',
        source: '<template><section>Search Panel</section></template>', builtin: false, created_at: null, updated_at: null,
      },
    },
  },
  K4: {
    source_uri: 'literature://paper-1', content: '文献来源',
    search_result: {
      id: 'form-1:row-1', source: 'literature', title: '检索研究', snippet: '文献来源', locator: '.mw/forms/paper.pdf',
      updated_at: '', score: 0.7, matched_modes: ['title'],
      item: {
        form_id: 'form-1', form_title: '研究文献', row_id: 'row-1', title: '检索研究', file_name: 'paper.pdf',
        asset_path: '.mw/forms/paper.pdf', content_excerpt: '文献来源', file_size: 4096,
        entered_at: '', updated_at: '', last_viewed_at: '', tags: [], rating: 5,
      },
    },
  },
}

async function mockWorkspace(page: Page, mountKnowledge = false): Promise<void> {
  let streamCompleted = false
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/agent/stream') {
      streamCompleted = true
      const event = {
        node: 'agent',
        content: `四库来源：[K1] [K2] [K3] [K4]\n\n📄 [打开《${mountedFileName}》](/knowledge/files/raw?user_id=e2e-user&path=${encodeURIComponent(mountedFilePath)})`
          + (mountKnowledge ? Object.values(mountedSearchResults).filter(({ search_result }) => search_result.source !== 'files').map(({ search_result }) => (
            `\n\n[${search_result.title}](/knowledge/resolve?source=${search_result.source}&id=${encodeURIComponent(search_result.id)}&user_id=e2e-user&library_id=default)`
          )).join('') : ''),
        tool_calls: [],
        trace: [],
        metadata: {
          citation_map: {
            ...mountedSearchResults,
          },
          used_citations: ['K1', 'K2', 'K3', 'K4'],
          change_snapshot: {
            snapshot_id: 'snap-e2e', session_id: 'e2e-session', run_id: 'run-e2e', created_at: '',
            additions: 10, deletions: 2, is_undone: false, edits: [],
            files: ['a.md', 'b.md', 'c.md', 'd.md'].map((path) => ({ path, additions: 2, deletions: 0, edits: [] })),
          },
        },
      }
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: `data: ${JSON.stringify(event)}\n\ndata: [DONE]\n\n` })
      return
    }
    if (url.pathname === '/agent/task-suggestions') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          suggestions: streamCompleted ? ['检查这次修改', '继续优化侧边栏', '解释本次改动'] : [],
        }),
      })
      return
    }
    if (url.pathname === '/knowledge/resolve') {
      const result = Object.values(mountedSearchResults).find(({ search_result }) => (
        search_result.source === url.searchParams.get('source') && search_result.id === url.searchParams.get('id')
      ))?.search_result
      await route.fulfill({ status: result ? 200 : 404, contentType: 'application/json', body: JSON.stringify(result ?? { detail: 'missing' }) })
      return
    }
    if (url.pathname === '/health') {
      await route.fulfill({ status: 200, body: 'ok' })
      return
    }
    if (url.pathname === '/settings/profile') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profile) })
      return
    }
    if (url.pathname === '/settings/models/status') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ embedding: 'ready', rerank: 'ready' }) })
      return
    }
    if (url.pathname === '/settings/models/management' || url.pathname === '/agent/children' || url.pathname === '/library/tags') {
      const body = url.pathname === '/agent/children' ? { children: [] } : url.pathname === '/library/tags' ? { tags: [] } : { models: [] }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
      return
    }
    if (url.pathname === '/knowledge/files/content' || url.pathname === '/knowledge/files/preview') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        path: url.searchParams.get('path'), content: '# 文件正文', text: '# 文件正文', kind: 'text', mtime: '', size: 16, extension: 'md', readonly: false,
      }) })
      return
    }
    if (url.pathname === '/knowledge/files') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tree: [
          {
            name: mountedFileName, path: mountedFilePath, isDir: false,
            size: 24576, createdAt: '2026-08-21 09:30', mtime: '2026-08-21 10:00',
            indexStatus: 'indexed', graphStatus: 'graphed',
          },
          {
            name: '冬冬国.md', path: sourceFilePath, isDir: false,
            size: 1024, createdAt: '', mtime: '', indexStatus: 'indexed', graphStatus: 'graphed',
          },
        ] }),
      })
      return
    }
    if (url.pathname === '/vault/status') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user_id: 'e2e-user', configured: true, item_count: 2 }) })
      return
    }
    if (url.pathname === '/vault/items') {
      const items = [
        {
          item_id: 'login-1', user_id: 'e2e-user', item_type: 'login', name: '工作账号',
          fields: { name: '工作账号', username: 'alice' }, safe_fields: { name: '工作账号', username: 'alice' },
          field_keys: ['name', 'username', 'password'], tags: [], deleted_at: '', created_at: '2026-08-21T09:00:00Z', updated_at: '2026-08-21T09:00:00Z',
        },
        {
          item_id: 'login-2', user_id: 'e2e-user', item_type: 'login', name: '私人账号',
          fields: { name: '私人账号', uri: 'https://example.com' }, safe_fields: { name: '私人账号', uri: 'https://example.com' },
          field_keys: ['name', 'password', 'uri'], tags: [], deleted_at: '', created_at: '2026-08-20T09:00:00Z', updated_at: '2026-08-20T09:00:00Z',
        },
      ]
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items, total: 2, type_counts: { login: 2, card: 0, identity: 0, secure_note: 0 } }) })
      return
    }
    if (url.pathname === '/vault/tags') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ tags: [] }) })
      return
    }
    if (url.pathname === '/sessions' && request.method() === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'e2e-session', user_id: 'e2e-user', session_name: 'test', created_at: '', updated_at: '' }) })
      return
    }
    if (url.pathname === '/sessions') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (url.pathname.endsWith('/messages')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (url.pathname === '/favorites') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ favorites: [] }) })
      return
    }
    if (url.pathname === '/privacy') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ privacy: [] }) })
      return
    }
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    await route.continue()
  })

  await page.addInitScript(() => {
    if (window.top !== window) return
    localStorage.setItem('agent_editor_profile', JSON.stringify({
      userId: 'e2e-user', knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default',
      knowledgeLibraries: [{ libraryId: 'default', name: 'Default', knowledgeDir: 'D:/Knowledge', isActive: true }],
    }))
    sessionStorage.setItem('metaweave_vault_token_e2e-user', JSON.stringify({ token: 'vault-token', expires_at: '2099-01-01T00:00:00Z' }))
  })
}

test('renders and opens an encoded Agent file block', async ({ page }, testInfo) => {
  await mockWorkspace(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'))
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.locator('textarea[placeholder="输入消息..."]').fill('挂载这个文件')
  await page.getByRole('button', { name: '发送' }).click()

  const block = page.locator('.agent-mounted-file')
  await expect(block).toBeVisible()
  await expect(block.locator('.agent-mounted-file__status')).toHaveCount(4)
  await expect(block).toContainText(`D:/Knowledge/${mountedFilePath}`)

  // K references remain source citations; only explicit knowledge URLs mount cards.
  await expect(page.locator('.agent-search-result-section')).toHaveCount(0)
  await expect(page.locator('.agent-knowledge-block')).toHaveCount(0)

  const summary = page.locator('.agent-page-mode .final-turn-summary')
  await summary.getByRole('button', { name: '来源' }).click()
  await summary.getByRole('button', { name: /冬冬国\.md/ }).click()
  const sourceSidebar = page.locator('.editor-sidebar-content')
  await expect(sourceSidebar).toHaveAttribute('aria-hidden', 'false')
  await expect(page.locator('.agent-page-mode')).toBeVisible()
  await page.getByRole('button', { name: '关闭编辑区侧边栏' }).click()
  await page.screenshot({ path: testInfo.outputPath('agent-file-dark.png'), fullPage: true })

  await block.click()
  const editorSidebar = page.locator('.editor-sidebar-content')
  await expect(editorSidebar).toHaveAttribute('aria-hidden', 'false')
  await expect(editorSidebar).toBeVisible()
  await expect(editorSidebar.locator('.sidebar-editor-panel')).toBeVisible()
  await expect.poll(async () => (await editorSidebar.boundingBox())?.width ?? 0).toBeGreaterThan(300)
  const editorWidthBefore = (await editorSidebar.boundingBox())?.width ?? 0
  const editorResizer = page.getByRole('separator', { name: 'Resize editor sidebar' })
  await expect(editorResizer).toBeVisible()
  const editorHandleBox = await editorResizer.boundingBox()
  await page.mouse.move(
    (editorHandleBox?.x ?? 0) + (editorHandleBox?.width ?? 4) / 2,
    (editorHandleBox?.y ?? 0) + (editorHandleBox?.height ?? 400) / 2,
  )
  await page.mouse.down()
  await page.mouse.move((editorHandleBox?.x ?? 0) + 80, (editorHandleBox?.y ?? 0) + (editorHandleBox?.height ?? 400) / 2)
  await page.mouse.up()
  await expect.poll(async () => (await editorSidebar.boundingBox())?.width ?? 0).toBeLessThan(editorWidthBefore - 60)
  await page.screenshot({ path: testInfo.outputPath('agent-file-sidebar-open.png'), fullPage: true })
})

test('opens four-library inline K citations in their native right sidebars', async ({ page }, testInfo) => {
  await mockWorkspace(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.locator('textarea[placeholder="输入消息..."]').fill('展示四库引用')
  await page.getByRole('button', { name: '发送' }).click()

  const sidebar = page.locator('.editor-sidebar-content')
  const sources = ['files', 'library', 'components', 'literature'] as const
  for (const [index, source] of sources.entries()) {
    await page.locator(`.citation-anchor[data-citation-idx="K${index + 1}"]`).click()
    await expect(sidebar).toHaveAttribute('aria-hidden', 'false')
    if (source === 'files') {
      await expect(sidebar.locator('.sidebar-editor-panel')).toBeVisible()
    } else {
      await expect(sidebar.locator(`.search-result-sidebar[data-source="${source}"]`)).toBeVisible()
    }
    await expect(page.locator('.agent-page-mode')).toBeVisible()
    if (source === 'literature') {
      await page.screenshot({ path: testInfo.outputPath('four-library-k-citation-sidebar.png'), fullPage: true })
    }
    await page.getByRole('button', { name: '关闭编辑区侧边栏' }).click()
  }
})

test('mounts only explicitly linked native knowledge blocks at responsive widths', async ({ page }, testInfo) => {
  await mockWorkspace(page, true)
  await page.setViewportSize({ width: 1440, height: 1100 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.getByPlaceholder('输入消息...').fill('单独展示选择的知识块')
  await page.getByRole('button', { name: '发送' }).click()
  const blocks = page.locator('.agent-knowledge-block')
  await expect(blocks).toHaveCount(3)
  await expect(page.locator('.agent-mounted-file')).toHaveCount(1)
  await expect(page.locator('.agent-search-result-section, .file-medium-grid')).toHaveCount(0)
  await expect(blocks.locator('.library-card')).toHaveCount(1)
  await expect(blocks.locator('.component-card')).toHaveCount(1)
  await expect(blocks.locator('.literature-card')).toHaveCount(1)

  for (const width of [1024, 768, 480, 320]) {
    await page.setViewportSize({ width, height: 1100 })
    for (const block of await blocks.all()) {
      await block.scrollIntoViewIfNeeded()
      await expect(block).toBeVisible()
      const geometry = await block.evaluate((element) => {
        const bounds = element.getBoundingClientRect()
        const parent = element.parentElement!.getBoundingClientRect()
        return { left: bounds.left, right: bounds.right, parentRight: parent.right, client: element.clientWidth, scroll: element.scrollWidth }
      })
      expect(geometry.left).toBeGreaterThanOrEqual(0)
      expect(geometry.right).toBeLessThanOrEqual(width + 1)
      expect(geometry.right).toBeLessThanOrEqual(geometry.parentRight + 1)
      expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 1)
    }
    await page.screenshot({ path: testInfo.outputPath(`knowledge-blocks-${width}.png`), fullPage: true })
  }
  await page.setViewportSize({ width: 1440, height: 1100 })
  await blocks.locator('.component-card .detail-button').click()
  await expect(page.locator('.editor-sidebar-content .search-result-sidebar[data-source="components"]')).toBeVisible()
  await expect(page.locator('.agent-page-mode')).toBeVisible()
  await page.getByRole('button', { name: '关闭编辑区侧边栏' }).click()
  await blocks.locator('.literature-card').click()
  await expect(page.locator('.editor-sidebar-content .search-result-sidebar[data-source="literature"]')).toBeVisible()
})

test('keeps mounted files, changes, and input controls compact in Agent sidebar mode', async ({ page }, testInfo) => {
  await mockWorkspace(page)
  await page.setViewportSize({ width: 1180, height: 800 })
  await page.goto('/')
  await page.getByTitle('切换 Agent 面板').click()

  const agentColumn = page.locator('.agent-col')
  await expect(agentColumn).toHaveAttribute('aria-hidden', 'false')
  await agentColumn.locator('textarea[placeholder="输入消息..."]').fill('挂载这个文件')
  await agentColumn.getByRole('button', { name: '发送' }).click()

  const block = agentColumn.locator('.agent-mounted-file')
  await expect(block).toBeVisible()
  const mountedFileTitle = block.locator('.agent-mounted-file__name')
  await expect(mountedFileTitle).toHaveText(mountedFileName)
  const titleOverflow = await mountedFileTitle.evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      display: style.display,
      overflow: style.overflow,
      textOverflow: style.textOverflow,
      whiteSpace: style.whiteSpace,
      isTruncated: element.scrollWidth > element.clientWidth,
    }
  })
  expect(titleOverflow).toEqual({
    display: 'block',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    isTruncated: true,
  })
  await expect(block.locator('.agent-mounted-file__path')).toBeHidden()
  await expect(block.locator('.agent-mounted-file__created')).toBeHidden()
  await expect(block.locator('.agent-mounted-file__statuses')).toBeHidden()
  const blockGeometry = await block.evaluate((element) => {
    const bounds = element.getBoundingClientRect()
    const parent = element.parentElement?.getBoundingClientRect()
    return { width: bounds.width, parentWidth: parent?.width ?? 0, height: bounds.height }
  })
  expect(blockGeometry.width).toBeLessThanOrEqual(blockGeometry.parentWidth)
  expect(blockGeometry.height).toBeGreaterThanOrEqual(52)
  expect(blockGeometry.height).toBeLessThanOrEqual(58)

  const changeSummary = agentColumn.locator('.final-turn-summary.compact')
  await expect(changeSummary).toBeVisible()
  const panelSwitch = changeSummary.locator('.panel-switch')
  await expect(panelSwitch).toBeVisible()
  const switchAlignment = await changeSummary.evaluate((summary) => {
    const summaryBounds = summary.getBoundingClientRect()
    const switchBounds = (summary.querySelector('.panel-switch') as HTMLElement).getBoundingClientRect()
    return {
      rightGap: summaryBounds.right - switchBounds.right,
      switchCenter: (switchBounds.left + switchBounds.right) / 2,
      summaryCenter: (summaryBounds.left + summaryBounds.right) / 2,
    }
  })
  expect(switchAlignment.rightGap).toBeLessThanOrEqual(12)
  expect(switchAlignment.switchCenter).toBeGreaterThan(switchAlignment.summaryCenter)
  await expect(changeSummary.locator('.change-file-row')).toHaveCount(1)
  await expect(changeSummary).toContainText('再显示 3 个文件')

  const toolbar = agentColumn.locator('.input-toolbar')
  await expect(toolbar.getByRole('button', { name: '上传文件' })).toBeVisible()
  await expect(toolbar.getByRole('button', { name: '联网搜索' })).toBeVisible()
  await expect(toolbar.getByLabel('Agent 权限')).toBeVisible()
  await expect(toolbar.getByRole('button', { name: '配置模型' })).toBeVisible()
  await expect(toolbar.getByRole('button', { name: '发送' })).toBeVisible()
  const toolbarLayout = await toolbar.evaluate((element) => {
    const visibleControls = Array.from(element.querySelectorAll<HTMLElement>('button, summary, .context-progress'))
      .filter((item) => getComputedStyle(item).display !== 'none')
      .map((item) => {
        const rect = item.getBoundingClientRect()
        return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
      })
    const overlaps = visibleControls.some((current, index) => visibleControls.slice(index + 1).some((next) => (
      current.left < next.right && current.right > next.left && current.top < next.bottom && current.bottom > next.top
    )))
    return { overlaps, scrollWidth: element.scrollWidth, clientWidth: element.clientWidth }
  })
  expect(toolbarLayout.overlaps).toBe(false)
  expect(toolbarLayout.scrollWidth).toBeLessThanOrEqual(toolbarLayout.clientWidth)

  const suggestions = agentColumn.locator('.task-suggestions')
  await expect(suggestions.locator('.suggestion-button')).toHaveCount(3)
  await expect(agentColumn.locator('.chat-input-wrap .suggestion-button')).toHaveCount(0)
  const contentOrder = await agentColumn.locator('.bubble-row.assistant, .final-turn-summary, .task-suggestions').evaluateAll((elements) => (
    elements.map((element) => element.className)
  ))
  expect(contentOrder.at(-1)).toContain('task-suggestions')

  const stacking = await agentColumn.evaluate((element) => {
    const messages = element.querySelector('.message-list') as HTMLElement
    const welcome = element.querySelector('.welcome-center') as HTMLElement | null
    return {
      messages: Number(getComputedStyle(messages).zIndex),
      welcome: welcome ? Number(getComputedStyle(welcome).zIndex) : 0,
    }
  })
  expect(stacking.messages).toBeGreaterThan(stacking.welcome)

  await page.screenshot({ path: testInfo.outputPath('agent-sidebar-compact.png'), fullPage: true })

  await block.click()
  await expect(page.locator('.editor-sidebar-content')).toHaveAttribute('aria-hidden', 'true')
  await expect(page.locator('.main-shell .editor-panel .editor-pane-tab-title')).toHaveText(mountedFileName)
})

test('reveals all asynchronous follow-up suggestions below the Agent output', async ({ page }, testInfo) => {
  await mockWorkspace(page)
  await page.setViewportSize({ width: 1100, height: 420 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.locator('textarea[placeholder="输入消息..."]').fill('挂载这个文件')
  await page.getByRole('button', { name: '发送' }).click()

  const messageList = page.locator('.agent-page-mode .message-list')
  const suggestions = messageList.locator('.task-suggestions')
  await expect(suggestions.locator('.suggestion-button')).toHaveCount(3)
  const visibility = await messageList.evaluate((list) => {
    const listBounds = list.getBoundingClientRect()
    const suggestionElement = list.querySelector('.task-suggestions') as HTMLElement
    const suggestionBounds = suggestionElement.getBoundingClientRect()
    return {
      height: suggestionBounds.height,
      borderTopWidth: getComputedStyle(suggestionElement).borderTopWidth,
      topVisible: suggestionBounds.top >= listBounds.top,
      bottomVisible: suggestionBounds.bottom <= listBounds.bottom + 1,
    }
  })
  expect(visibility.height).toBeGreaterThanOrEqual(26)
  expect(visibility.borderTopWidth).toBe('0px')
  expect(visibility.topVisible).toBe(true)
  expect(visibility.bottomVisible).toBe(true)

  await page.screenshot({ path: testInfo.outputPath('agent-follow-up-suggestions-visible.png'), fullPage: true })
})

test('shows the selected vault type non-empty field union', async ({ page }, testInfo) => {
  await mockWorkspace(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: '库', exact: true }).click()
  const vaultButton = page.locator('button[aria-label="密码库"]')
  await expect(vaultButton).toBeVisible()
  await vaultButton.click({ force: true })
  await page.getByRole('button', { name: /登录/ }).click()

  await expect(page.locator('.vault-table th')).toHaveText(['', '项目名称', '用户名', '密码', '网站 URI', '创建时间', '拥有者'])
  await expect(page.locator('.vault-table')).not.toContainText('secret')
  await page.screenshot({ path: testInfo.outputPath('vault-login-columns.png'), fullPage: true })
})

test('closes the library submenu after clicking outside it', async ({ page }) => {
  await mockWorkspace(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')

  await page.getByRole('button', { name: '库', exact: true }).click()
  await expect(page.locator('[aria-label="知识库菜单"]')).toBeVisible()
  await page.locator('.topbar').click({ position: { x: 8, y: 8 } })

  await expect(page.locator('[aria-label="知识库菜单"]')).toBeHidden()
})
