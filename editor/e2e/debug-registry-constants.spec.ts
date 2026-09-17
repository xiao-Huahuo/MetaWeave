/**
 * Debug 工具注册表与全局常量浏览器冒烟测试。
 *
 * 使用说明:
 * 打开真实 Debug 页面,逐项验证运行时新增工具不会被设置分组过滤,并验证
 * AgentConfig 动态快照能够以只读方式展示介绍和值。
 */
import { expect, test } from '@playwright/test'

test('shows every runtime tool and the read-only AgentConfig snapshot', async ({ page }) => {
  await page.route('**/*', async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname === '/health') {
      await route.fulfill({ status: 200, body: 'ok' })
      return
    }
    if (pathname === '/settings/models/status') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ embedding: 'ready', rerank: 'ready' }),
      })
      return
    }
    if (pathname === '/settings/profile') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user_id: 'debug-e2e-user',
          knowledge_dir: 'D:/Knowledge',
          active_library_id: 'default',
          knowledge_libraries: [],
        }),
      })
      return
    }
    if (pathname === '/sessions') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (pathname === '/agent/tools') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          tool_count: 3,
          tools: [
            {
              name: 'known_tool',
              display_name: '已分组工具',
              description: '设置页已登记的工具。',
              args_schema: { properties: {}, required: [] },
              argument_count: 0,
            },
            {
              name: 'new_runtime_tool',
              display_name: '新增运行时工具',
              description: '只存在于最终运行时注册表的工具。',
              args_schema: { properties: {}, required: [] },
              argument_count: 0,
            },
            {
              name: 'write_long_term_memory',
              display_name: '写入记忆',
              description: '写入长期记忆。',
              args_schema: { properties: {}, required: ['content'] },
              argument_count: 1,
            },
          ],
        }),
      })
      return
    }
    if (pathname === '/settings/tools/available') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          groups: [
            {
              category: 'UTILITY',
              display_name: '通用工具',
              tools: [
                {
                  name: 'known_tool',
                  display_name: '已分组工具',
                  description: '设置页已登记的工具。',
                  enabled: true,
                },
              ],
            },
            {
              category: 'MEMORY',
              display_name: '记忆工具',
              tools: [{
                name: 'write_long_term_memory',
                display_name: '写入记忆',
                description: '写入长期记忆。',
                enabled: true,
              }],
            },
          ],
        }),
      })
      return
    }
    if (pathname === '/settings/tools/disabled') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ disabled_tools: [] }),
      })
      return
    }
    if (pathname === '/debug/global-constants') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          config_count: 1,
          constant_count: 2,
          configs: [
            {
              key: 'server',
              name: 'ServerConfig',
              description: '管理 HTTP 与 gRPC 服务。',
              constants: [
                {
                  name: 'http_port',
                  description: 'FastAPI HTTP 监听端口。',
                  type: 'int',
                  value: 8002,
                },
                {
                  name: 'grpc_host',
                  description: 'gRPC 监听地址。',
                  type: 'str',
                  value: '[::]',
                },
              ],
            },
          ],
        }),
      })
      return
    }
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    await route.continue()
  })

  await page.addInitScript(() => {
    localStorage.setItem('agent_editor_profile', JSON.stringify({
      userId: 'debug-e2e-user',
      knowledgeDir: 'D:/Knowledge',
      activeLibraryId: 'default',
      knowledgeLibraries: [],
    }))
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Debug', exact: true }).click()

  await page.getByRole('button', { name: '工具注册表' }).click()
  await expect(page.getByText('新增运行时工具', { exact: true })).toBeVisible()
  await expect(page.getByText('运行时工具', { exact: true })).toBeVisible()
  const memoryToolRow = page.locator('.tool-list-item').filter({ hasText: '写入记忆' })
  await expect(memoryToolRow.locator('input')).toBeDisabled()
  await expect(memoryToolRow.locator('.tool-toggle-label')).toHaveAttribute('title', '由长期记忆总开关控制')
  const toolRegistryStyles = await page.locator('.tool-registry-panel').evaluate((panel) => {
    /** 采集工具注册表关键组件规格,用于和全局常量页做像素级同源断言。 */
    const read = (selector: string, properties: string[]) => {
      const element = panel.querySelector(selector)
      if (!(element instanceof HTMLElement)) throw new Error(`missing ${selector}`)
      const style = getComputedStyle(element)
      return Object.fromEntries(properties.map(property => [property, style.getPropertyValue(property)]))
    }
    const panelStyle = getComputedStyle(panel)
    return {
      panel: { padding: panelStyle.padding },
      heading: read('.registry-heading', ['grid-template-columns', 'gap']),
      search: read('.registry-search', ['border-radius', 'padding']),
      surface: read('.panel-surface', ['border-radius', 'border-width']),
      grid: read('.registry-grid', ['grid-template-columns', 'gap', 'padding']),
      list: read('.tool-list', ['border-radius', 'border-width']),
      detail: read('.tool-detail', ['padding', 'border-radius']),
      title: read('.detail-display', ['font-size', 'font-weight']),
      description: read('.detail-description', ['font-size', 'line-height', 'margin']),
      table: read('.arg-table', ['border-radius', 'border-width']),
      schema: read('.schema-block', ['font-size', 'line-height', 'padding', 'border-radius']),
    }
  })

  const constantsTab = page.getByRole('button', { name: '全局常量' })
  await expect(constantsTab.locator('svg path')).toHaveCount(1)
  await constantsTab.click()
  const constantsPanel = page.locator('.global-constants-panel')
  await expect(constantsPanel).toBeVisible()
  await expect(constantsPanel.getByText('ServerConfig', { exact: true }).first()).toBeVisible()
  await expect(constantsPanel.locator('.detail-display')).toHaveText('http_port')
  await expect(constantsPanel.getByText('FastAPI HTTP 监听端口。', { exact: true })).toBeVisible()
  await expect(constantsPanel.getByText('8002', { exact: true }).last()).toBeVisible()
  await expect(constantsPanel.locator('textarea')).toHaveCount(0)
  await expect(constantsPanel.locator('input[type="checkbox"]')).toHaveCount(0)
  const constantRegistryStyles = await constantsPanel.evaluate((panel) => {
    /** 使用与工具注册表相同的选择器采集规格,确保两页共享真实组件语言。 */
    const read = (selector: string, properties: string[]) => {
      const element = panel.querySelector(selector)
      if (!(element instanceof HTMLElement)) throw new Error(`missing ${selector}`)
      const style = getComputedStyle(element)
      return Object.fromEntries(properties.map(property => [property, style.getPropertyValue(property)]))
    }
    const panelStyle = getComputedStyle(panel)
    return {
      panel: { padding: panelStyle.padding },
      heading: read('.registry-heading', ['grid-template-columns', 'gap']),
      search: read('.registry-search', ['border-radius', 'padding']),
      surface: read('.panel-surface', ['border-radius', 'border-width']),
      grid: read('.registry-grid', ['grid-template-columns', 'gap', 'padding']),
      list: read('.tool-list', ['border-radius', 'border-width']),
      detail: read('.tool-detail', ['padding', 'border-radius']),
      title: read('.detail-display', ['font-size', 'font-weight']),
      description: read('.detail-description', ['font-size', 'line-height', 'margin']),
      table: read('.arg-table', ['border-radius', 'border-width']),
      schema: read('.schema-block', ['font-size', 'line-height', 'padding', 'border-radius']),
    }
  })
  expect(constantRegistryStyles).toEqual(toolRegistryStyles)
})
