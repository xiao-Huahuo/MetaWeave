/*
 * Model and compiler management component tests.
 *
 * Usage:
 * Verifies backend-owned details, real byte progress, expandable information,
 * and friendly compiler lifecycle actions render without fabricated values.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CompilerManagement from '../CompilerManagement.vue'
import ModelManagement from '../ModelManagement.vue'
import SdkManagement from '../SdkManagement.vue'

const {
  fetchModelManagement,
  checkModelDisk,
  downloadManagedModel,
  deleteManagedModel,
  loadManagedModel,
  fetchLatexManagement,
  installLatexRuntime,
  cancelLatexInstall,
  uninstallLatexRuntime,
  fetchDshSdkManagement,
  installDshSdk,
  cancelDshSdkInstall,
  repairDshSdk,
  uninstallDshSdk,
} = vi.hoisted(() => ({
  fetchModelManagement: vi.fn(),
  checkModelDisk: vi.fn().mockResolvedValue({}),
  downloadManagedModel: vi.fn().mockResolvedValue({ status: 'started', model: 'embedding' }),
  deleteManagedModel: vi.fn().mockResolvedValue({ model: 'embedding', deleted: true, path: 'D:/models/demo' }),
  loadManagedModel: vi.fn().mockResolvedValue({ status: 'triggered', model: 'rerank' }),
  fetchLatexManagement: vi.fn(),
  installLatexRuntime: vi.fn(),
  cancelLatexInstall: vi.fn(),
  uninstallLatexRuntime: vi.fn(),
  fetchDshSdkManagement: vi.fn(),
  installDshSdk: vi.fn(),
  cancelDshSdkInstall: vi.fn(),
  repairDshSdk: vi.fn(),
  uninstallDshSdk: vi.fn(),
}))

vi.mock('@/api/settings', () => ({
  fetchModelManagement,
  checkModelDisk,
  downloadManagedModel,
  deleteManagedModel,
  loadManagedModel,
}))

vi.mock('@/api/latex', () => ({
  fetchLatexManagement,
  installLatexRuntime,
  cancelLatexInstall,
  uninstallLatexRuntime,
}))

vi.mock('@/api/sdk', () => ({
  fetchDshSdkManagement,
  installDshSdk,
  cancelDshSdkInstall,
  repairDshSdk,
  uninstallDshSdk,
}))

const iconStub = { template: '<span class="icon-stub"></span>' }

describe('management panels', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    checkModelDisk.mockResolvedValue({})
  })

  it('shows real model bytes, enabled state and expandable backend details', async () => {
    fetchModelManagement.mockResolvedValue({ models: [{
      key: 'embedding',
      label: 'Embedding 模型',
      role: '知识向量化',
      name: 'BAAI/demo',
      path: 'D:/models/demo',
      base_path: 'D:/models',
      size_bytes: 1024,
      file_count: 4,
      status: 'downloading',
      enabled: true,
      active: false,
      downloaded: false,
      progress: {
        status: 'downloading', stage: 'model_files', downloaded_bytes: 50,
        total_bytes: 200, percent: 25, indeterminate: false, message: '正在下载模型文件',
      },
      details: { provider: 'Hugging Face', repository: 'BAAI/demo' },
    }] })
    const wrapper = mount(ModelManagement, {
      props: { userId: 'u1' },
      global: { stubs: { IcIcon: iconStub } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('已启用')
    expect(wrapper.text()).toMatch(/50 B\s+\/ 200 B · 25%/u)
    expect(wrapper.get('progress').attributes('value')).toBe('25')
    await wrapper.get('.details-toggle').trigger('click')
    expect(wrapper.text()).toContain('D:/models/demo')
    expect(wrapper.text()).toContain('Hugging Face')
  })

  it('shows every backend-owned component of the structured OCR pipeline', async () => {
    fetchModelManagement.mockResolvedValue({ models: [{
      key: 'paddleocr',
      label: 'PaddleOCR 结构化流水线',
      role: '扫描文档版面、文字、表格、公式与阅读顺序解析',
      name: 'PP-StructureV3 高质量流水线',
      path: 'D:/models/paddleocr',
      base_path: 'D:/models/paddleocr',
      size_bytes: 4096,
      file_count: 42,
      status: 'ready',
      enabled: true,
      active: true,
      downloaded: true,
      progress: {
        status: 'idle', stage: 'idle', downloaded_bytes: 0,
        total_bytes: null, percent: null, indeterminate: false, message: '',
      },
      details: {
        provider: 'PaddleOCR / PaddleX',
        layout_model: 'PP-DocLayout-L',
        ocr_models: 'PP-OCRv5_server_det / PP-OCRv5_server_rec',
        table_models: 'SLANeXt_wired / SLANeXt_wireless',
        formula_model: 'PP-FormulaNet_plus-M',
        supporting_models: 'PP-DocBlockLayout / UVDoc / RT-DETR-L_wired_table_cell_det',
        disabled_modules: '图表解析 / 印章识别',
      },
    }] })
    const wrapper = mount(ModelManagement, {
      props: { userId: 'u1' },
      global: { stubs: { IcIcon: iconStub } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('PaddleOCR 结构化流水线')
    expect(wrapper.text()).toContain('PP-StructureV3 高质量流水线')
    await wrapper.get('.details-toggle').trigger('click')
    expect(wrapper.text()).toContain('版面模型')
    expect(wrapper.text()).toContain('PP-DocLayout-L')
    expect(wrapper.text()).toContain('SLANeXt_wired / SLANeXt_wireless')
    expect(wrapper.text()).toContain('PP-FormulaNet_plus-M')
    expect(wrapper.text()).toContain('PP-DocBlockLayout / UVDoc / RT-DETR-L_wired_table_cell_det')
    expect(wrapper.text()).toContain('图表解析 / 印章识别')
  })

  it('polls automatically when an active download is discovered on initial load', async () => {
    vi.useFakeTimers()
    const downloadingModel = (percent: number) => ({
      key: 'local_qwen',
      label: '本地 Qwen 大语言模型',
      role: '本地主 Agent、小模型回退与图片理解',
      name: 'Qwen/Qwen3.5-2B',
      path: 'D:/models/qwen',
      base_path: 'D:/models',
      size_bytes: percent,
      file_count: 4,
      status: 'downloading',
      enabled: true,
      active: false,
      downloaded: false,
      progress: {
        status: 'downloading', stage: 'model_files', downloaded_bytes: percent,
        total_bytes: 100, percent, indeterminate: false, message: '正在下载模型文件',
      },
      details: { provider: 'Hugging Face' },
    })
    fetchModelManagement
      .mockResolvedValueOnce({ models: [downloadingModel(25)] })
      .mockResolvedValueOnce({ models: [downloadingModel(50)] })

    const wrapper = mount(ModelManagement, {
      props: { userId: 'u1' },
      global: { stubs: { IcIcon: iconStub } },
    })
    await flushPromises()
    expect(wrapper.get('progress').attributes('value')).toBe('25')

    await vi.advanceTimersByTimeAsync(750)
    await flushPromises()

    expect(fetchModelManagement).toHaveBeenCalledTimes(2)
    expect(wrapper.get('progress').attributes('value')).toBe('50')
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('shows compiler source, location, size, engines and honest unknown progress', async () => {
    fetchLatexManagement.mockResolvedValue({
      status: 'installing', stage: 'packages', progress: null, message: '正在下载 MiKTeX basic 宏包',
      downloaded_bytes: 4096, total_bytes: null, indeterminate: true,
      source: 'managed', managed: true, distribution: 'MiKTeX', version: 'MiKTeX 25.12',
      compiler_path: 'D:/runtime/miktex/pdflatex.exe', latexmk_path: 'D:/runtime/miktex/latexmk.exe',
      default_engine: 'pdflatex', runtime_path: 'D:/runtime/latex', distribution_path: 'D:/runtime/miktex',
      size_bytes: 8192, file_count: 20,
      engines: [
        { name: 'pdflatex', available: true, path: 'D:/runtime/miktex/pdflatex.exe', default: true },
        { name: 'xelatex', available: true, path: 'D:/runtime/miktex/xelatex.exe', default: false },
      ],
      paths: { repository: 'D:/runtime/repository' },
    })
    const wrapper = mount(CompilerManagement, {
      props: { userId: 'u1' },
      global: { stubs: { IcIcon: iconStub } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('MetaWeave 托管')
    expect(wrapper.text()).toContain('4.0 KB')
    expect(wrapper.get('progress').attributes('value')).toBeUndefined()
    await wrapper.get('.details-toggle').trigger('click')
    expect(wrapper.text()).toContain('D:/runtime/miktex')
    expect(wrapper.text()).toContain('pdflatex')
    expect(wrapper.text()).toContain('xelatex')
  })

  it('shows the backend-owned DSH Runtime version, progress and install path', async () => {
    fetchDshSdkManagement.mockResolvedValue({
      key: 'deepseek_harness', label: 'DeepSeek Harness SDK', role: '代码子 Agent 与只读执行轨迹',
      version: '0.1.0-rc.5+mw.1', platform: 'Windows x64', path: 'D:/runtime/assets/sdks/dsh',
      size_bytes: 0, package_size_bytes: 4096, file_count: 0,
      installed: false, configured: true, in_use: false,
      status: 'extracting', message: '正在解压 Windows Runtime', processed_bytes: 1024,
      total_bytes: 4096, progress: 25,
    })
    const wrapper = mount(SdkManagement, {
      props: { userId: 'u1' },
      global: { stubs: { IcIcon: iconStub } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('DeepSeek Harness SDK')
    expect(wrapper.text()).toContain('0.1.0-rc.5+mw.1')
    expect(wrapper.text()).toMatch(/1.0 KB\s+\/ 4.0 KB/u)
    expect(wrapper.get('progress').attributes('value')).toBe('25')
    expect(wrapper.text()).toContain('正在解压 Windows Runtime')
    await wrapper.findAll('.icon-action')[1]!.trigger('click')
    expect(wrapper.text()).toContain('D:/runtime/assets/sdks/dsh')
    wrapper.unmount()
  })

  it('keeps SDK available while compiler retries its own transient failure', async () => {
    vi.useFakeTimers()
    fetchLatexManagement
      .mockRejectedValueOnce(new Error('compiler timeout'))
      .mockResolvedValueOnce({
        status: 'ready', message: '可用', source: 'system', managed: false,
        distribution: 'MiKTeX', version: '25.12', distribution_path: 'D:/MiKTeX',
        runtime_path: '', size_bytes: 0, file_count: 1, engines: [], paths: {},
      })
    fetchDshSdkManagement.mockResolvedValue({
      key: 'deepseek_harness', label: 'DeepSeek Harness SDK', role: '代码子 Agent',
      version: '0.1.0-rc.5+mw.1', platform: 'Windows x64', path: 'D:/sdk',
      size_bytes: 1, package_size_bytes: 1, file_count: 1, installed: true,
      configured: true, in_use: false, status: 'ready', message: '可用',
      processed_bytes: 0, total_bytes: 0, progress: null,
    })
    const compiler = mount(CompilerManagement, {
      props: { userId: 'u1' }, global: { stubs: { IcIcon: iconStub } },
    })
    const sdk = mount(SdkManagement, {
      props: { userId: 'u1' }, global: { stubs: { IcIcon: iconStub } },
    })
    await flushPromises()

    expect(compiler.text()).toContain('compiler timeout')
    expect(sdk.text()).toContain('DeepSeek Harness SDK')

    await vi.advanceTimersByTimeAsync(750)
    await flushPromises()
    expect(compiler.text()).toContain('MiKTeX')
    expect(compiler.text()).not.toContain('compiler timeout')
    expect(fetchDshSdkManagement).toHaveBeenCalledTimes(1)
    compiler.unmount()
    sdk.unmount()
    vi.useRealTimers()
  })
})
