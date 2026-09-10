/**
 * Shared tag-color palette browser smoke test.
 *
 * Usage:
 * Saves one color through the real Appearance UI, then verifies Library and
 * Smart Forms render their real tag components from the same root variable.
 */
import { expect, test } from '@playwright/test'

test('saves, resets, and shares tag colors across Library and Smart Forms', async ({ page }, testInfo) => {
  test.setTimeout(60_000)
  const userId = 'tag-color-smoke'
  const defaults = ['#7c5cfc', '#eb2463', '#26a269', '#2f88d5', '#e2a72e', '#0ea5b6']
  let persistedColors = [...defaults]
  let persistedTranslucency = true
  const form = {
    version: 1,
    title: '标签色验收',
    updatedAt: new Date().toISOString(),
    columns: [
      { id: 'row_index', title: '序号', type: 'index', removable: false, editable: false, width: 64 },
      { id: 'tags', title: '标签', type: 'tag', removable: true, editable: true, width: 200 },
    ],
    rows: [{ id: 'row-1', cells: { row_index: { value: '1' }, tags: { value: 'f' } } }],
  }
  const libraryItem = {
    item_id: 'tag-book', user_id: userId, library_id: 'default', parent_id: '', item_type: 'book',
    content_type: 'knowledge_file', title: '标签色图书', display_title: '标签色图书', description: '',
    storage_path: '.mw/library/tag.md', source_path: '.mw/library/tag.md', source_url: '',
    source_name: 'tag.md', source_mime: 'text/markdown', source_size: 12, source_mtime: '2026-09-10T00:00:00Z', source_exists: true,
    cover_mode: 'title', cover_asset_id: '', cover_asset: null, sort_order: 0, index_status: '', graph_status: '',
    tags: ['f'], child_count: 0, created_at: '2026-09-10T00:00:00Z', updated_at: '2026-09-10T00:00:00Z',
  }

  await page.addInitScript(({ profile }) => {
    localStorage.setItem('agent_editor_profile', JSON.stringify(profile))
    localStorage.setItem('agent_editor_settings_active_tab', 'appearance')
  }, {
    profile: {
      userId, knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default', knowledgeWatchEnabled: true,
      knowledgeLibraries: [{ libraryId: 'default', name: '标签色验收库', knowledgeDir: 'D:/Knowledge', libraryStorageDir: '.mw/library', isActive: true }],
      tagColors: defaults,
      tagColorsTranslucent: true,
    },
  })

  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.pathname === '/health') return route.fulfill({ status: 200, body: 'ok' })
    if (url.pathname === '/settings/models/status') return json({ embedding: 'ready', rerank: 'ready' })
    if (url.pathname === '/settings/models/management') return json({ models: [] })
    if (url.pathname === '/settings/profile') return json({
      user_id: userId, knowledge_dir: 'D:/Knowledge', active_library_id: 'default',
      knowledge_libraries: [{ library_id: 'default', name: '标签色验收库', knowledge_dir: 'D:/Knowledge', library_storage_dir: '.mw/library', is_active: true }],
      theme_primary_color: '', theme_soft_color: '', tag_colors: persistedColors,
      tag_colors_translucent: persistedTranslucency,
      background_cover_url: '', show_backlinks: false, created_at: '', updated_at: '',
    })
    if (url.pathname === '/settings/appearance/config') {
      const body = request.postDataJSON() as { tag_colors?: string[]; tag_colors_translucent?: boolean | null }
      if (body.tag_colors) persistedColors = body.tag_colors.length ? [...body.tag_colors] : [...defaults]
      if ('tag_colors_translucent' in body) persistedTranslucency = body.tag_colors_translucent ?? true
      return json({
        user_id: userId, theme_primary_color: '', theme_soft_color: '', tag_colors: persistedColors,
        tag_colors_translucent: persistedTranslucency,
        background_cover_url: '', show_backlinks: false, updated_at: '',
      })
    }
    if (url.pathname === '/library/items') return json({ items: [libraryItem], parent: null, breadcrumbs: [] })
    if (url.pathname === '/library/tags') return json({ tags: ['f'] })
    if (url.pathname === '/smart-forms/list') return json([{ form_id: 'tag-form', title: form.title, asset_dir: '.mw/forms/tag', updated_at: form.updatedAt }])
    if (url.pathname === '/smart-forms/tag-form') return json({ form_id: 'tag-form', user_id: userId, asset_dir: '.mw/forms/tag', form, updated_at: form.updatedAt })
    if (url.pathname === '/favorites') return json({ favorites: [] })
    if (url.pathname === '/privacy') return json({ privacy: [] })
    if (url.pathname === '/sessions' || url.pathname === '/todo/list') return json([])
    if (url.pathname === '/knowledge/files') return json({ tree: [] })
    if (url.pathname === '/knowledge/files/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': smoke\n\n' })
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') return json({})
    return route.continue()
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Settings' }).click()
  const tagColorOne = page.getByLabel('标签色 1 十六进制值')
  const translucencyToggle = page.getByLabel('半透明效果')
  await expect(tagColorOne).toBeVisible()
  await expect(translucencyToggle).toBeChecked()
  await tagColorOne.fill('#123456')
  await tagColorOne.blur()
  await translucencyToggle.uncheck()
  await page.getByRole('button', { name: '保存标签色' }).click()
  await expect.poll(() => persistedColors[0]).toBe('#123456')
  await expect.poll(() => persistedTranslucency).toBe(false)
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-tag-1').trim())).toBe('#123456')
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--tag-color-library-strength').trim())).toBe('100%')
  await page.screenshot({ path: testInfo.outputPath('appearance-tag-colors.png'), fullPage: true })

  await page.getByRole('navigation', { name: 'Editor activity bar' }).getByLabel('主页').click()
  await page.getByRole('button', { name: /进入图书馆/u }).first().click()
  const libraryTag = page.locator('.library-card .tag-pill').first()
  await expect(libraryTag).toBeVisible()
  await expect.poll(() => libraryTag.evaluate((element) => {
    const probe = document.createElement('span')
    probe.style.background = 'color-mix(in srgb, var(--color-tag-1) var(--tag-color-library-strength), transparent)'
    document.body.append(probe)
    const expected = getComputedStyle(probe).backgroundColor
    probe.remove()
    return getComputedStyle(element).backgroundColor === expected
  })).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('library-shared-tag-color.png'), fullPage: true })

  await page.getByRole('button', { name: '库', exact: true }).click()
  await page.locator('.knowledge-submenu:visible .activity-button').nth(4).dispatchEvent('click')
  const smartTag = page.locator('.smart-table .tag-pill').first()
  await expect(smartTag).toBeVisible()
  await expect(smartTag).toHaveAttribute('style', /var\(--color-tag-1\)/u)
  await page.screenshot({ path: testInfo.outputPath('smart-forms-shared-tag-color.png'), fullPage: true })

  await page.getByRole('button', { name: 'Settings' }).click()
  await page.getByRole('button', { name: '重置标签色' }).click()
  await expect.poll(() => persistedColors).toEqual(defaults)
  await expect(page.getByLabel('半透明效果')).toBeChecked()
  await expect.poll(() => persistedTranslucency).toBe(true)
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-tag-1').trim())).toBe(defaults[0])
})
