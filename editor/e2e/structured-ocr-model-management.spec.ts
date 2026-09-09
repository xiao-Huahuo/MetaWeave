/**
 * Structured OCR model-management responsive browser smoke.
 *
 * Usage:
 * Opens the real storage-management UI with a backend-shaped PP-StructureV3
 * model response and verifies the expanded component list at desktop, tablet,
 * and mobile widths without changing product state.
 */
import { expect, test } from '@playwright/test'

test('shows the complete structured OCR pipeline without horizontal clipping', async ({ page }) => {
  const userId = 'structured-ocr-smoke'
  await page.addInitScript(({ profile }) => {
    localStorage.setItem('agent_editor_profile', JSON.stringify(profile))
    localStorage.setItem('agent_editor_settings_active_tab', 'storage')
  }, {
    profile: { userId, knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default', knowledgeLibraries: [] },
  })
  await page.route('**/*', async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname === '/knowledge/files/events') {
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
    }
    if (!['fetch', 'xhr'].includes(request.resourceType())) return route.continue()
    if (pathname === '/health') return route.fulfill({ json: { ok: true } })
    if (pathname === '/settings/profile') return route.fulfill({ json: {
      user_id: userId, knowledge_dir: 'D:/Knowledge', knowledge_libraries: [],
      created_at: '2026-09-09T00:00:00Z', updated_at: '2026-09-09T00:00:00Z',
    } })
    if (pathname === '/settings/storage/config') return route.fulfill({ json: {
      paths: [], knowledge_dir_total_bytes: 0, runtime_total_bytes: 1_934_281_728,
      managed_resource_distribution: [{ name: 'models', size_bytes: 1_934_281_728 }],
    } })
    if (pathname === '/settings/models/check') return route.fulfill({ json: { paddleocr: 'ready' } })
    if (pathname === '/settings/models/management') return route.fulfill({ json: { models: [{
      key: 'paddleocr', label: 'PaddleOCR 结构化流水线',
      role: '扫描文档版面、文字、表格、公式与阅读顺序解析', name: 'PP-StructureV3 高质量流水线',
      path: 'D:/MetaWeave/runtime/models/paddleocr', base_path: 'D:/MetaWeave/runtime/models/paddleocr',
      size_bytes: 1_934_281_728, file_count: 186, status: 'ready', enabled: true, active: true, downloaded: true,
      progress: { status: 'idle', stage: 'idle', downloaded_bytes: 0, total_bytes: null, percent: null, indeterminate: false, message: '' },
      details: {
        provider: 'PaddleOCR / PaddleX', language: 'ch', device: 'cpu', layout_model: 'PP-DocLayout-L',
        ocr_models: 'PP-OCRv5_server_det / PP-OCRv5_server_rec',
        table_models: 'SLANeXt_wired / SLANeXt_wireless', formula_model: 'PP-FormulaNet_plus-M',
        supporting_models: 'PP-DocBlockLayout / UVDoc / RT-DETR-L_wired_table_cell_det / RT-DETR-L_wireless_table_cell_det',
        preprocessing: '方向分类 / 透视与弯曲校正 / 文本行方向', disabled_modules: '图表解析 / 印章识别',
      },
    }] } })
    if (pathname === '/settings/latex/management') return route.fulfill({ json: {
      status: 'missing', progress: null, downloaded_bytes: 0, total_bytes: null, engines: [], paths: {},
    } })
    if (pathname === '/settings/sdks/dsh/management') return route.fulfill({ json: {
      key: 'deepseek_harness', label: 'DeepSeek Harness SDK', role: '代码子 Agent', version: 'test',
      platform: 'Windows x64', path: 'D:/sdk', size_bytes: 0, package_size_bytes: 0, file_count: 0,
      installed: false, configured: true, in_use: false, status: 'missing', message: '未安装',
      processed_bytes: 0, total_bytes: 0, progress: null,
    } })
    if (pathname === '/sessions' || pathname === '/todo/list' || pathname === '/automation/list') {
      return route.fulfill({ json: [] })
    }
    if (pathname === '/favorites') return route.fulfill({ json: { favorites: [] } })
    if (pathname === '/privacy') return route.fulfill({ json: { privacy: [] } })
    if (pathname === '/knowledge/files') return route.fulfill({ json: { tree: [] } })
    if (pathname === '/settings/models/status') return route.fulfill({ json: { paddleocr: 'ready' } })
    return route.fulfill({ json: {} })
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Settings' }).click()
  const model = page.locator('[data-model="paddleocr"]')
  await expect(model.getByText('PaddleOCR 结构化流水线', { exact: true })).toBeVisible()
  await model.getByRole('button', { name: '展开 PaddleOCR 结构化流水线详情' }).click()
  await expect(model.getByText('PP-DocLayout-L', { exact: true })).toBeVisible()
  await expect(model.getByText('SLANeXt_wired / SLANeXt_wireless', { exact: true })).toBeVisible()
  await expect(model.getByText('PP-FormulaNet_plus-M', { exact: true })).toBeVisible()

  for (const width of [1024, 768, 480]) {
    await page.setViewportSize({ width, height: 820 })
    await expect.poll(() => page.locator('.settings-body').evaluate(element => (
      element.scrollWidth - element.clientWidth
    ))).toBeLessThanOrEqual(1)
    await page.screenshot({ path: `test-results/structured-ocr-model-${width}.png`, fullPage: true })
  }
})
