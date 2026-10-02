/*
 * Agent body-stream regression smoke tests.
 *
 * Runs the real Agent page/store/Markdown renderer against a paced SSE fetch
 * fixture. Existing text nodes must survive suffix updates, the thinking scan
 * and controls must keep advancing, and completion/cancellation must keep text.
 * Run with: npx playwright test e2e/agent-text-stream-performance.spec.ts --project=chromium --workers=1
 */
import { expect, test, type Page } from '@playwright/test'
import { writeFile } from 'node:fs/promises'

/** Browser-owned fixture; all timers and stream resources stop on close/abort. */
interface BodyStreamHarness {
  /** The production fetch caller has opened its SSE response. */
  ready: boolean
  /** Exact source passed to the stream before its terminal event. */
  accepted: string
  /** The production AbortSignal has closed the fixture. */
  aborted: boolean
  /** Emits one body delta through the production SSE decoder. */
  append: (content: string) => void
  /** Emits body deltas at 25 ms intervals, retaining the response afterwards. */
  pace: (deltas: string[]) => void
  /** Completes the SSE response and releases its timer/controller. */
  finish: () => void
  /** Whether the fixture still owns a live interval. */
  pacing: boolean
}

/** Measurements only cover steady incremental output, excluding initial parsing. */
interface BodyStreamProbe {
  /** Gaps between browser animation frames during steady body updates. */
  frameGaps: number[]
  /** Main-thread task durations collected by the browser. */
  longTasks: number[]
  /** Computed gradient positions of the user's 正在思考 label. */
  shimmerPositions: string[]
  /** Computed transforms of the reasoning row's scanning light. */
  scanTransforms: string[]
  /** Mutation batches belonging to the actual assistant body. */
  textUpdates: number
  /** Number of observations after the original prefix Text is disconnected. */
  prefixReplacements: number
  /** Milliseconds between clicking the sidebar and its rendered open state. */
  controlDelay: number
  /** Disconnects both observers and cancels the measurement frame. */
  stop: () => void
}

declare global {
  interface Window {
    __bodyStream: BodyStreamHarness
    __bodyStreamProbe: BodyStreamProbe
  }
}

test.use({ headless: true, viewport: { width: 1440, height: 960 } })

/** Reuses the Agent responsiveness fixture endpoints without bypassing its UI. */
async function openAgent(page: Page) {
  let sessionCreated = false
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/settings/profile') {
      await route.fulfill({ json: { user_id: 'e2e-user', knowledge_dir: 'D:/Knowledge', active_library_id: 'default', knowledge_libraries: [] } })
      return
    }
    const session = { session_id: 'body-stream-session', user_id: 'e2e-user', session_name: 'body stream', created_at: '', updated_at: '' }
    if (url.pathname === '/sessions' && request.method() === 'POST') {
      sessionCreated = true
      await route.fulfill({ json: session })
      return
    }
    if (url.pathname === '/sessions' && request.method() === 'GET') {
      await route.fulfill({ json: sessionCreated ? [session] : [] })
      return
    }
    const mockBodies: Record<string, unknown> = {
      '/settings/models/status': { embedding: 'ready', rerank: 'ready', paddleocr: 'ready' },
      '/settings/models/management': { models: [] },
      '/privacy': { privacy: [] },
      '/favorites': { favorites: [] },
      '/skills': { skills: [], count: 0 },
      '/agent/children': { session_id: 'body-stream-session', children: [] },
      '/knowledge/files': { tree: [] },
      '/todo/list': [],
      '/automation/list': [],
      '/settings/llm/config': { model_name: '', context_window_tokens: 128000 },
      '/settings/web-search/config': { enabled: false },
      '/git/status': { initialized: false, branches: [], remote_branches: [], remotes: [], changes: [], untracked: [], ignored: [], has_changes: false },
      '/git/history': { history: [], unpushed_commits: [], unpushed_files: [], upstream: '' },
    }
    if (url.pathname in mockBodies) {
      await route.fulfill({ json: mockBodies[url.pathname] })
      return
    }
    if (url.pathname.endsWith('/messages') || url.pathname.endsWith('/changes') || url.pathname.endsWith('/task-list') || url.pathname.endsWith('/state') || url.pathname.includes('task-suggestions')) {
      const body = url.pathname.endsWith('/messages') ? [] : url.pathname.endsWith('/changes') ? { change_snapshot: null } : url.pathname.endsWith('/task-list') ? { task_list: null } : url.pathname.endsWith('/state') ? { session_state: null } : { suggestions: [] }
      await route.fulfill({ json: body })
      return
    }
    if (request.resourceType() === 'fetch' || request.resourceType() === 'xhr') {
      await route.fulfill({ json: {} })
      return
    }
    await route.continue()
  })
  await page.addInitScript(() => {
    localStorage.setItem('agent_editor_profile', JSON.stringify({ userId: 'e2e-user', knowledgeDir: 'D:/Knowledge', activeLibraryId: 'default', knowledgeLibraries: [] }))
    const nativeFetch = window.fetch.bind(window)
    const encoder = new TextEncoder()
    let controller: ReadableStreamDefaultController<Uint8Array> | undefined
    let timer = 0
    let closed = false
    let firstBodyDelta = true
    /** Encodes exactly the SSE delta event used by the production stream client. */
    const emit = (type: string, content: string) => {
      const metadata = type === 'delta' && firstBodyDelta ? { latency: { first_agent_delta_ms: 37 } } : {}
      if (type === 'delta') firstBodyDelta = false
      controller?.enqueue(encoder.encode(`data: ${JSON.stringify({ type, node: 'agent', content, metadata, tool_calls: [], trace: [] })}\n\n`))
    }
    window.__bodyStream = {
      ready: false,
      accepted: '',
      aborted: false,
      pacing: false,
      append(content) {
        if (closed) return
        this.accepted += content
        emit('delta', content)
      },
      pace(deltas) {
        let index = 0
        this.pacing = true
        timer = window.setInterval(() => {
          const delta = deltas[index++]
          if (delta !== undefined) this.append(delta)
          if (index >= deltas.length) {
            window.clearInterval(timer)
            timer = 0
            this.pacing = false
          }
        }, 25)
      },
      finish() {
        if (closed) return
        window.clearInterval(timer)
        timer = 0
        this.pacing = false
        closed = true
        controller?.enqueue(encoder.encode('data: [DONE]\n\n'))
        controller?.close()
      },
    }
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href)
      if (url.pathname !== '/agent/stream') return nativeFetch(input, init)
      const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined)
      /** Aborting the real composer closes this fixture exactly once. */
      const abort = () => {
        if (closed) return
        closed = true
        window.clearInterval(timer)
        timer = 0
        window.__bodyStream.pacing = false
        window.__bodyStream.aborted = true
        controller?.error(new DOMException('Aborted', 'AbortError'))
      }
      const body = new ReadableStream<Uint8Array>({
        start(value) {
          controller = value
          window.__bodyStream.ready = true
          // Real runs retain earlier model requests. Exercise the installed
          // devtools subscriber with substantial immutable request payloads.
          const messages = Array.from({ length: 32 }, () => ({ role: 'user', content: '模型请求的历史上下文。'.repeat(200) }))
          const snapshots = Array.from({ length: 6 }, (_, index) => ({
            call_index: index + 1, node: 'agent', model_tier: 'large', model: 'performance-fixture',
            temperature: 0, timeout_seconds: 120, model_kwargs: {}, messages, tools: [],
          }))
          controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'context_mirror', node: 'agent', context_messages: messages, context_snapshots: snapshots })}\n\n`))
          emit('thinking', '正在检查正文流的连续更新。')
          if (signal?.aborted) abort()
          else signal?.addEventListener('abort', abort, { once: true })
        },
        cancel() { abort() },
      })
      return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    }
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await page.locator('textarea[placeholder="输入消息..."]').fill('验证长正文输出')
  await page.getByTitle('发送').click()
  await expect.poll(() => page.evaluate(() => window.__bodyStream.ready)).toBe(true)
  await expect(page.getByTitle('中断输出')).toBeVisible()
  await expect(page.locator('.thinking-flow span')).toHaveText('正在思考')
}

/** Captures a prefix Text identity, real RAF cadence, and both thinking scans. */
async function startProbe(page: Page) {
  await page.evaluate(() => {
    const root = [...document.querySelectorAll('.markdown-body')].at(-1)!
    const firstText = document.createTreeWalker(root, NodeFilter.SHOW_TEXT).nextNode()!
    const shimmer = document.querySelector('.thinking-flow span')!
    const scan = document.querySelector('.think-row__trigger')!
    let previousFrame = performance.now()
    let frame = 0
    let frameId = 0
    let lastShimmerSample = 0
    let controlClickedAt = 0
    const probe: BodyStreamProbe = {
      frameGaps: [], longTasks: [], shimmerPositions: [], scanTransforms: [],
      textUpdates: 0, prefixReplacements: 0, controlDelay: -1,
      stop() {
        cancelAnimationFrame(frameId)
        mutations.disconnect()
        longTasks.disconnect()
      },
    }
    /** A disconnected prefix proves previously emitted content was rebuilt. */
    const mutations = new MutationObserver((records) => {
      if (!firstText.isConnected) probe.prefixReplacements += 1
      probe.textUpdates += records.filter((record) => root.contains(record.target) && (record.type === 'characterData' || record.addedNodes.length > 0)).length
      if (controlClickedAt > 0 && document.querySelector('.session-drawer.open')) {
        probe.controlDelay = performance.now() - controlClickedAt
        controlClickedAt = 0
      }
    })
    mutations.observe(document.body, { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ['class'] })
    const longTasks = new PerformanceObserver((entries) => {
      probe.longTasks.push(...entries.getEntries().map((entry) => entry.duration))
    })
    longTasks.observe({ type: 'longtask', buffered: false })
    document.querySelector('[title="Toggle sidebar"]')!.addEventListener('click', () => { controlClickedAt = performance.now() }, { once: true })
    /** Sample computed animation state sparingly so the probe adds little work. */
    const tick = (now: number) => {
      if (frame++ > 0) probe.frameGaps.push(now - previousFrame)
      previousFrame = now
      if (now - lastShimmerSample >= 80) {
        probe.shimmerPositions.push(getComputedStyle(shimmer).backgroundPosition)
        probe.scanTransforms.push(getComputedStyle(scan, '::after').transform)
        lastShimmerSample = now
      }
      frameId = requestAnimationFrame(tick)
    }
    frameId = requestAnimationFrame(tick)
    window.__bodyStreamProbe = probe
  })
}

/** Stops the observer before final Markdown reparse and returns serializable data. */
async function stopProbe(page: Page) {
  return page.evaluate(() => {
    const probe = window.__bodyStreamProbe
    probe.stop()
    return {
      frameGaps: probe.frameGaps, longTasks: probe.longTasks,
      shimmerPositions: probe.shimmerPositions, scanTransforms: probe.scanTransforms,
      textUpdates: probe.textUpdates, prefixReplacements: probe.prefixReplacements,
      controlDelay: probe.controlDelay,
    }
  })
}

/** Cases keep a single open Markdown block while many small suffixes arrive. */
const prose = '长正文必须连续输出，中文和 emoji😀 都应完整保留。'.repeat(2000)
const codeRows = Array.from({ length: 280 }, (_, index) => `result_${index} = calculate(${index}, "正文与代码😀")\n`)
const listRows = Array.from({ length: 330 }, (_, index) => `- item_${index}: 正文更新应保留之前的列表条目\n`)
const tableRows = Array.from({ length: 330 }, (_, index) => `| row_${index} | 正文更新应保留之前的表格单元格 |\n`)
const cases = [
  { name: 'long uninterrupted prose', initial: prose, deltas: Array.from({ length: 30 }, (_, index) => `增量${index}继续输出。`), ending: '', selector: 'p', expected: [prose + Array.from({ length: 30 }, (_, index) => `增量${index}继续输出。`).join('')] },
  { name: 'long fenced Python code', initial: '```python\n' + codeRows.slice(0, 250).join(''), deltas: codeRows.slice(250), ending: '```', selector: 'pre code', expected: [codeRows.join('')] },
  { name: 'long uninterrupted list', initial: listRows.slice(0, 300).join(''), deltas: listRows.slice(300), ending: '', selector: 'li', expected: listRows.map((row) => row.slice(2).trimEnd()) },
  { name: 'long uninterrupted table', initial: '| key | value |\n| --- | --- |\n' + tableRows.slice(0, 300).join(''), deltas: tableRows.slice(300), ending: '', selector: 'tbody td', expected: tableRows.flatMap((_, index) => [`row_${index}`, '正文更新应保留之前的表格单元格']) },
]

for (const fixture of cases) {
  test(`keeps body text and thinking scans responsive during ${fixture.name}`, async ({ page }, testInfo) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await openAgent(page)
    await page.evaluate((initial) => window.__bodyStream.append(initial), fixture.initial)
    const reply = page.locator('.markdown-body').last()
    await expect.poll(() => reply.textContent()).toContain(fixture.name.includes('code') ? 'result_249' : fixture.name.includes('list') ? 'item_299' : fixture.name.includes('table') ? 'row_299' : prose.slice(-80))
    await startProbe(page)
    await page.evaluate((deltas) => window.__bodyStream.pace(deltas), fixture.deltas)
    await page.getByTitle('Toggle sidebar').click()
    await expect(page.locator('.session-drawer')).toHaveClass(/open/)
    await page.locator('textarea[placeholder="输入消息..."]').fill('输出时输入仍然响应')
    await expect(page.locator('textarea[placeholder="输入消息..."]')).toHaveValue('输出时输入仍然响应')
    await expect.poll(() => page.evaluate(() => window.__bodyStream.pacing)).toBe(false)
    await expect.poll(() => reply.textContent()).toContain(fixture.deltas.at(-1)!.trim().replace(/^- /, '').replace(/^\| /, '').split(' | ')[0]!)
    const measured = await stopProbe(page)
    const metricPath = testInfo.outputPath('body-stream-metrics.json')
    await writeFile(metricPath, JSON.stringify(measured), 'utf8')
    await testInfo.attach('body-stream-metrics', { contentType: 'application/json', path: metricPath })
    const orderedGaps = [...measured.frameGaps].sort((a, b) => a - b)
    console.log(JSON.stringify({ case: fixture.name, maxFrameMs: Math.max(...orderedGaps), p95FrameMs: orderedGaps[Math.floor(orderedGaps.length * 0.95)], maxLongTaskMs: Math.max(0, ...measured.longTasks), controlMs: measured.controlDelay, updates: measured.textUpdates }))
    expect(measured.prefixReplacements, 'already displayed prefix DOM must survive each suffix').toBe(0)
    expect(measured.textUpdates).toBeGreaterThan(10)
    expect(measured.frameGaps.length).toBeGreaterThan(15)
    expect(Math.max(...measured.frameGaps), 'body updates must not block multiple visible frames').toBeLessThan(80)
    expect(orderedGaps[Math.floor(orderedGaps.length * 0.95)]).toBeLessThan(40)
    expect(Math.max(0, ...measured.longTasks)).toBeLessThan(80)
    expect(new Set(measured.shimmerPositions).size).toBeGreaterThan(4)
    expect(new Set(measured.scanTransforms.filter((value) => value !== 'none')).size).toBeGreaterThan(4)
    expect(measured.controlDelay).toBeGreaterThanOrEqual(0)
    expect(measured.controlDelay).toBeLessThan(200)
    if (fixture.selector === 'pre code') {
      await page.screenshot({ path: testInfo.outputPath('agent-code-stream.png') })
    }
    await page.evaluate((ending) => {
      if (ending) window.__bodyStream.append(ending)
      window.__bodyStream.finish()
    }, fixture.ending)
    await expect(page.getByTitle('中断输出')).toHaveCount(0)
    await expect(reply.locator(fixture.selector)).toHaveText(fixture.expected)
    if (fixture.selector === 'pre code') await expect(reply.locator('pre code .hljs-keyword, pre code .hljs-string').first()).toBeAttached()
    expect(errors).toEqual([])
  })
}

test('keeps all accepted body text when interrupted during paced output', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await openAgent(page)
  await page.evaluate((initial) => window.__bodyStream.append(initial), prose)
  const reply = page.locator('.markdown-body').last()
  await expect.poll(() => reply.textContent()).toContain(prose.slice(-80))
  await page.evaluate(() => window.__bodyStream.pace(Array.from({ length: 80 }, (_, index) => `中断前增量${index}。`)))
  await expect.poll(() => page.evaluate(() => window.__bodyStream.accepted.length)).toBeGreaterThan(prose.length + 80)
  await page.getByTitle('中断输出').click()
  await expect.poll(() => page.evaluate(() => window.__bodyStream.aborted)).toBe(true)
  await expect(page.getByTitle('中断输出')).toHaveCount(0)
  const accepted = await page.evaluate(() => window.__bodyStream.accepted)
  await expect(reply).toHaveText(accepted)
  expect(await page.evaluate(() => window.__bodyStream.pacing)).toBe(false)
  expect(errors).toEqual([])
})
