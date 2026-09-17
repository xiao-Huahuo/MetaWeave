/**
 * LLM settings effective-model summary tests.
 *
 * Usage:
 * Verifies that users can distinguish unconfigured, inherited, and explicit
 * large/small/vision model routing from the real saved state.
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import LlmSettingsSection from '../LlmSettingsSection.vue'

function mountSection(overrides: Record<string, unknown> = {}) {
  return mount(LlmSettingsSection, {
    props: {
      largeModelName: '',
      largeBaseUrl: '',
      largeApiKey: '',
      largeContextWindowTokens: 1_000_000,
      largeMaxOutputTokens: 0,
      smallModelName: '',
      smallBaseUrl: '',
      smallApiKey: '',
      smallContextWindowTokens: 1_000_000,
      smallMaxOutputTokens: 0,
      visionModelName: '',
      visionBaseUrl: '',
      visionApiKey: '',
      showLargeKey: false,
      showSmallKey: false,
      showVisionKey: false,
      modelEditing: false,
      modelConfigSaved: false,
      modelSaving: false,
      modelMsg: '',
      savedConfigs: [],
      modelConfigLoaded: true,
      effectiveLargeModelName: '',
      effectiveLargeModelSource: 'unconfigured',
      effectiveSmallModelName: '',
      effectiveSmallModelSource: 'unconfigured',
      effectiveVisionModelName: '',
      effectiveVisionModelSource: 'unconfigured',
      savedSmallModelConfigured: false,
      ...overrides,
    },
  })
}

describe('LLM effective model summary', () => {
  it('shows every role as unconfigured without presenting a local fallback', () => {
    const wrapper = mountSection()

    expect(wrapper.get('[data-effective-model="large"]').text()).toContain('未配置')
    expect(wrapper.get('[data-effective-model="small"]').text()).toContain('未配置')
    expect(wrapper.get('[data-effective-model="vision"]').text()).toContain('未配置')
    expect(wrapper.text()).not.toContain('本地回退')
  })

  it('shows that the small and visual roles inherit the configured large model', () => {
    const wrapper = mountSection({
      effectiveLargeModelName: 'remote-large',
      effectiveLargeModelSource: 'remote',
      effectiveSmallModelName: 'remote-large',
      effectiveSmallModelSource: 'remote',
      effectiveVisionModelName: 'remote-large',
      effectiveVisionModelSource: 'large',
    })

    expect(wrapper.get('[data-effective-model="large"]').text()).toContain('远程配置')
    expect(wrapper.get('[data-effective-model="small"]').text()).toContain('复用大模型')
    expect(wrapper.get('[data-effective-model="vision"]').text()).toContain('继承大模型')
  })

  it('shows separately configured large, small, and visual models', () => {
    const wrapper = mountSection({
      effectiveLargeModelName: 'remote-large',
      effectiveLargeModelSource: 'remote',
      effectiveSmallModelName: 'remote-small',
      effectiveSmallModelSource: 'remote',
      effectiveVisionModelName: 'deepseek-flash',
      effectiveVisionModelSource: 'explicit',
      savedSmallModelConfigured: true,
    })

    expect(wrapper.get('[data-effective-model="large"]').text()).toContain('remote-large')
    expect(wrapper.get('[data-effective-model="small"]').text()).toContain('remote-small')
    expect(wrapper.get('[data-effective-model="small"]').text()).toContain('独立配置')
    expect(wrapper.get('[data-effective-model="vision"]').text()).toContain('deepseek-flash')
    expect(wrapper.get('[data-effective-model="vision"]').text()).toContain('独立配置')
  })

  it('resets cleared model capacity and all visual overrides', async () => {
    const wrapper = mountSection({
      modelEditing: true,
      largeContextWindowTokens: 500_000,
      smallContextWindowTokens: 200_000,
      visionModelName: 'deepseek-flash',
      visionBaseUrl: 'https://api.deepseek.com/v1',
      visionApiKey: 'secret',
    })

    await wrapper.get('button[aria-label="清空大模型配置"]').trigger('click')
    await wrapper.get('button[aria-label="清空小模型配置"]').trigger('click')
    await wrapper.get('button[aria-label="清空视觉模型配置"]').trigger('click')

    const largeCapacityEvents = wrapper.emitted('update:largeContextWindowTokens') ?? []
    const smallCapacityEvents = wrapper.emitted('update:smallContextWindowTokens') ?? []
    const visionNameEvents = wrapper.emitted('update:visionModelName') ?? []
    const visionUrlEvents = wrapper.emitted('update:visionBaseUrl') ?? []
    const visionKeyEvents = wrapper.emitted('update:visionApiKey') ?? []
    expect(largeCapacityEvents[largeCapacityEvents.length - 1]).toEqual([1_000_000])
    expect(smallCapacityEvents[smallCapacityEvents.length - 1]).toEqual([1_000_000])
    expect(visionNameEvents[visionNameEvents.length - 1]).toEqual([''])
    expect(visionUrlEvents[visionUrlEvents.length - 1]).toEqual([''])
    expect(visionKeyEvents[visionKeyEvents.length - 1]).toEqual([''])
  })

  it('offers every saved preset to the visual-model draft', async () => {
    const config = {
      config_id: 'vision-preset', user_id: 'u1', label: 'DeepSeek Vision',
      api_key: 'secret', base_url: 'https://api.deepseek.com/v1', model_name: 'deepseek-flash',
      created_at: '', updated_at: '',
    }
    const wrapper = mountSection({ savedConfigs: [config] })

    await wrapper.get('button[aria-label="导入 DeepSeek Vision 到视觉模型"]').trigger('click')

    expect(wrapper.emitted('importSavedConfig')).toEqual([[config, 'vision']])
  })
})
