/** Global entry framework: navigation preserves drafts and never grants fake authentication. */
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AuthView from '@/views/AuthView.vue'
import AuthFormShell from '@/components/auth_view/AuthFormShell.vue'
import KnowledgeLibraryStep from '@/components/auth_view/KnowledgeLibraryStep.vue'
import AuthField from '@/components/auth_view/AuthField.vue'
import ModelConfigStep from '@/components/auth_view/ModelConfigStep.vue'
import PreferencesStep from '@/components/auth_view/PreferencesStep.vue'
import { useSettingsStore } from '@/stores/settings'

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ knowledge_dir: 'D:/Knowledge' }), { status: 200, headers: { 'content-type': 'application/json' } })))
  localStorage.clear()
  vi.stubGlobal('matchMedia', () => ({ matches: false }))
})
afterEach(() => {
  vi.unstubAllGlobals()
})

function mountEntry() {
  return mount(AuthView, { global: { plugins: [createPinia()], stubs: { IcIcon: true, LineWaves: true } } })
}

describe('AuthView framework', () => {
  it('uses the backend absolute default and reuses the desktop directory picker', async () => {
    const picker = vi.fn().mockResolvedValue('D:/SelectedKnowledge')
    vi.stubGlobal('agentEditorDesktop', { selectDirectory: picker })
    const wrapper = mountEntry()
    await flushPromises()
    wrapper.getComponent(AuthFormShell).vm.$emit('navigate', 1)
    await wrapper.vm.$nextTick()
    const step = wrapper.getComponent(KnowledgeLibraryStep)
    expect((step.findAll('input')[1]!.element as HTMLInputElement).value).toBe('D:/Knowledge')
    await step.get('button[aria-label="选择知识目录"]').trigger('click')
    await flushPromises()
    expect(picker).toHaveBeenCalledOnce()
    expect((step.findAll('input')[1]!.element as HTMLInputElement).value).toBe('D:/SelectedKnowledge')
    wrapper.unmount()
  })

  it('switches login and registration on page 01 without persisting passwords or granting access', async () => {
    const wrapper = mountEntry()
    await wrapper.get('input[autocomplete="username"]').setValue('preview-user')
    await wrapper.get('input[autocomplete="current-password"]').setValue('private-draft')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="status"]').text()).toContain('尚未接入')
    expect(useSettingsStore().hasUserId).toBe(false)
    expect(JSON.stringify(localStorage)).not.toContain('private-draft')
    await wrapper.get('.auth-mode-switch button').trigger('click')
    expect(wrapper.get('.auth-page-number').text()).toBe('01')
    expect(wrapper.findAll('input[autocomplete="new-password"]')).toHaveLength(2)
    wrapper.unmount()
  })

  it('preserves model drafts across pages and disables DSH after its backbone changes', async () => {
    const wrapper = mountEntry()
    const model = wrapper.getComponent(ModelConfigStep)
    const fields = model.findAllComponents(AuthField)
    await fields[0]!.get('input').setValue('deepseek-chat')
    await fields[1]!.get('input').setValue('https://example.test/v1')
    await fields[2]!.get('input').setValue('key')
    wrapper.getComponent(AuthFormShell).vm.$emit('navigate', 3)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.auth-page-number').text()).toBe('04')
    expect(wrapper.getComponent(PreferencesStep).props('dshAvailable')).toBe(true)
    await wrapper
      .getComponent(PreferencesStep)
      .findAll('input[type="checkbox"]')
      .at(-1)!
      .setValue(true)
    await fields[0]!.get('input').setValue('gpt-test')
    expect(wrapper.getComponent(PreferencesStep).props('dshAvailable')).toBe(false)
    expect(
      (
        wrapper.getComponent(PreferencesStep).findAll('input[type="checkbox"]').at(-1)!
          .element as HTMLInputElement
      ).checked,
    ).toBe(false)
    expect((fields[1]!.get('input').element as HTMLInputElement).value).toBe(
      'https://example.test/v1',
    )
    wrapper.unmount()
  })
})
