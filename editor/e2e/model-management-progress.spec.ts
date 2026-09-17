/**
 * Model-management polling browser regression.
 *
 * Usage:
 * Opens the real storage-management page with a download already in progress
 * and verifies that the rendered byte count advances without a manual refresh.
 */
import { expect, test } from '@playwright/test'

test('updates an existing model download without manual refresh', async ({ page }) => {
  const userId = 'model-progress-smoke'
  let managementRequests = 0

  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/health') {
      await route.fulfill({ json: { ok: true } })
      return
    }
    if (url.pathname === '/settings/profile') {
      await route.fulfill({ json: {
        user_id: userId,
        knowledge_dir: 'D:/Knowledge',
        active_library_id: 'default',
        knowledge_libraries: [],
        created_at: '2026-08-26T00:00:00Z',
        updated_at: '2026-08-26T00:00:00Z',
      } })
      return
    }
    if (url.pathname === '/settings/storage/config') {
      await route.fulfill({ json: {
        paths: [],
        knowledge_dir_total_bytes: 0,
        runtime_total_bytes: 0,
        managed_resource_distribution: [],
      } })
      return
    }
    if (url.pathname === '/settings/models/check') {
      await route.fulfill({ json: { embedding: 'downloading', rerank: 'ready', paddleocr: 'ready' } })
      return
    }
    if (url.pathname === '/settings/models/management') {
      managementRequests += 1
      const downloadedBytes = managementRequests === 1 ? 10 : 35
      await route.fulfill({ json: { models: [{
        key: 'embedding',
        label: 'Embedding 模型',
        role: '知识向量化与语义检索',
        name: 'BAAI/bge-m3',
        path: 'D:/models/embedding',
        base_path: 'D:/models',
        size_bytes: downloadedBytes,
        file_count: 4,
        status: 'downloading',
        enabled: true,
        active: false,
        downloaded: false,
        progress: {
          status: 'downloading',
          stage: 'model_files',
          downloaded_bytes: downloadedBytes,
          total_bytes: 100,
          percent: downloadedBytes,
          indeterminate: false,
          message: '正在下载模型文件',
        },
        details: { provider: 'Hugging Face' },
      }] } })
      return
    }
    if (url.pathname === '/settings/latex/management') {
      await route.fulfill({ json: {
        status: 'not_installed',
        progress: null,
        downloaded_bytes: 0,
        total_bytes: null,
        engines: [],
        paths: {},
      } })
      return
    }
    if (url.pathname === '/settings/models/status') {
      await route.fulfill({ json: {
        embedding: 'ready',
        rerank: 'ready',
        paddleocr: 'ready',
      } })
      return
    }
    if (url.pathname === '/privacy') {
      await route.fulfill({ json: { privacy: [] } })
      return
    }
    if (url.pathname === '/sessions' || url.pathname === '/todo/list' || url.pathname === '/automation/list') {
      await route.fulfill({ json: [] })
      return
    }
    if (url.pathname === '/favorites') {
      await route.fulfill({ json: { favorites: [] } })
      return
    }
    if (url.pathname === '/knowledge/files') {
      await route.fulfill({ json: { tree: [] } })
      return
    }
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      await route.fulfill({ json: {} })
      return
    }
    await route.continue()
  })

  await page.addInitScript(({ profile }) => {
    localStorage.setItem('agent_editor_profile', JSON.stringify(profile))
    localStorage.setItem('agent_editor_settings_active_tab', 'storage')
  }, {
    profile: { userId, knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default', knowledgeLibraries: [] },
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Settings' }).click()

  const progress = page.locator('[data-model="embedding"] .real-progress')
  await expect(progress).toContainText('35 B / 100 B · 35%', { timeout: 3000 })
  expect(managementRequests).toBeGreaterThanOrEqual(2)
})
