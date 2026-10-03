/* Question interaction contracts: immediate single choice, preserved multi-page drafts and complete batch submission. */
import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import AgentQuestionBox from '../AgentQuestionBox.vue'
import type { AgentQuestionRequest } from '@/api/agent'

const request: AgentQuestionRequest = {
  request_id: 'question1', user_id: 'u1', session_id: 's1', run_id: 'r1', status: 'pending',
  questions: [{ id: 'q1', type: 'select', question: '选择处理方式', options: ['阅读', '编辑'], multi_select: false, allow_text: false }],
}
vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })

it('submits one radio choice immediately without a confirm button', async () => {
  const wrapper = mount(AgentQuestionBox, { props: { request } })
  expect(wrapper.find('button[type="submit"]').exists()).toBe(false)
  await wrapper.get('input[type="radio"]').setValue(true)
  expect(wrapper.emitted('answer')![0]).toEqual([{ q1: { selected_options: ['阅读'], text: '' } }])
})

it('keeps drafts across back/forward navigation and prevents incomplete batches', async () => {
  const wrapper = mount(AgentQuestionBox, { props: { request: { ...request, questions: [request.questions[0]!,
    { id: 'q2', type: 'select', question: '选择输出', options: ['摘要', '原文'], multi_select: true, allow_text: false },
    { id: 'q3', type: 'input', question: '需要哪个角色', options: [], multi_select: false, allow_text: true }] } } })
  const confirm = wrapper.get<HTMLButtonElement>('button[type="submit"]')
  expect(confirm.element.disabled).toBe(true)
  await wrapper.get('input[type="radio"]').setValue(true)
  expect(wrapper.emitted('answer')).toBeUndefined()
  expect(wrapper.get('.question-number').text()).toBe('2 / 3')
  for (const input of wrapper.findAll('.question-content.is-active input[type="checkbox"]')) await input.setValue(true)
  expect(wrapper.find('.question-content.is-active input[type="text"]').exists()).toBe(false)
  expect(confirm.element.disabled).toBe(true)
  await wrapper.get('[aria-label="上一个问题"]').trigger('click')
  expect(wrapper.get<HTMLInputElement>('.question-content.is-active input[type="radio"]').element.checked).toBe(true)
  await wrapper.get('[aria-label="下一个问题"]').trigger('click')
  await wrapper.get('[aria-label="下一个问题"]').trigger('click')
  await wrapper.get('input[type="text"]').setValue('芙宁娜')
  expect(wrapper.findAll('.question-content.is-active input[type="checkbox"], .question-content.is-active input[type="radio"]')).toHaveLength(0)
  await wrapper.get('[aria-label="上一个问题"]').trigger('click')
  await wrapper.get('[aria-label="下一个问题"]').trigger('click')
  expect(wrapper.get<HTMLInputElement>('input[type="text"]').element.value).toBe('芙宁娜')
  expect(confirm.element.disabled).toBe(false)
  await confirm.trigger('submit')
  expect(wrapper.emitted('answer')![0]).toEqual([{ q1: { selected_options: ['阅读'], text: '' }, q2: { selected_options: ['摘要', '原文'], text: '' }, q3: { selected_options: [], text: '芙宁娜' } }])
})

it('auto-advances each single choice once and keeps the last question for batch confirmation', async () => {
  const wrapper = mount(AgentQuestionBox, { props: { request: { ...request, questions: [
    request.questions[0]!, { ...request.questions[0]!, id: 'q2' }, { ...request.questions[0]!, id: 'q3' },
  ] } } })
  const stale = wrapper.get('.question-content.is-active input[type="radio"]')
  await stale.setValue(true)
  expect(wrapper.get('.question-number').text()).toBe('2 / 3')
  await stale.trigger('change')
  expect(wrapper.get('.question-number').text()).toBe('2 / 3')
  await wrapper.get('.question-content.is-active input[type="radio"]').setValue(true)
  expect(wrapper.get('.question-number').text()).toBe('3 / 3')
  await wrapper.get('.question-content.is-active input[type="radio"]').setValue(true)
  expect(wrapper.get('.question-number').text()).toBe('3 / 3')
  expect(wrapper.emitted('answer')).toBeUndefined()
  expect(wrapper.get<HTMLButtonElement>('button[type="submit"]').element.disabled).toBe(false)
  await wrapper.get('[aria-label="上一个问题"]').trigger('click')
  expect(wrapper.get('.question-number').text()).toBe('2 / 3')
  expect(wrapper.get<HTMLInputElement>('.question-content.is-active input[type="radio"]').element.checked).toBe(true)
  wrapper.unmount()
})

it('requires Enter to finish input and multi-select, ignoring empty, IME and repeat keys', async () => {
  const wrapper = mount(AgentQuestionBox, { props: { request: { ...request, questions: [
    { id: 'text', type: 'input', question: '角色名', options: [], multi_select: false, allow_text: true },
    { ...request.questions[0]!, id: 'many', multi_select: true },
    { id: 'last', type: 'input', question: '补充内容', options: [], multi_select: false, allow_text: true },
  ] } } })
  const input = wrapper.get('.question-content.is-active input[type="text"]')
  await input.trigger('keydown', { key: 'Enter' })
  expect(wrapper.get('.question-number').text()).toBe('1 / 3')
  await input.setValue('芙宁娜')
  await input.trigger('keydown', { key: 'Enter', isComposing: true })
  await input.trigger('keydown', { key: 'Enter', repeat: true })
  expect(wrapper.get('.question-number').text()).toBe('1 / 3')
  await input.trigger('keydown', { key: 'Enter' })
  expect(wrapper.get('.question-number').text()).toBe('2 / 3')
  const choices = wrapper.findAll('.question-content.is-active input[type="checkbox"]')
  for (const choice of choices) await choice.setValue(true)
  expect(wrapper.get('.question-number').text()).toBe('2 / 3')
  await choices[0]!.trigger('keydown', { key: 'Enter' })
  expect(wrapper.get('.question-number').text()).toBe('3 / 3')
  const last = wrapper.get('.question-content.is-active input[type="text"]')
  await last.setValue('保留引用')
  await last.trigger('keydown', { key: 'Enter' })
  expect(wrapper.emitted('answer')).toBeUndefined()
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('answer')![0]).toEqual([{ text: { selected_options: [], text: '芙宁娜' }, many: { selected_options: ['阅读', '编辑'], text: '' }, last: { selected_options: [], text: '保留引用' } }])
  wrapper.unmount()
})

it('single multi-select waits for confirmation and shows recoverable server errors', async () => {
  const wrapper = mount(AgentQuestionBox, { props: { request: { ...request, questions: [{ ...request.questions[0]!, multi_select: true }] } } })
  await wrapper.get('input[type="checkbox"]').setValue(true)
  expect(wrapper.emitted('answer')).toBeUndefined()
  await wrapper.setProps({ submitting: true })
  expect(wrapper.get<HTMLButtonElement>('button[type="submit"]').element.disabled).toBe(true)
  await wrapper.setProps({ submitting: false, error: '提交失败，请重试' })
  expect(wrapper.get('[role="alert"]').text()).toContain('提交失败')
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('answer')).toHaveLength(1)
})

it('renders a separate input question with the requested placeholder and no visible manual-input label', async () => {
  const wrapper = mount(AgentQuestionBox, { props: { request: { ...request, questions: [
    { id: 'q1', type: 'input', question: '请输入角色名', options: [], multi_select: false, allow_text: true },
  ] } } })
  const input = wrapper.get('input[type="text"]')
  expect(input.attributes('placeholder')).toBe('试试手动输入')
  expect(input.classes()).toContain('form-input-capsule')
  expect(wrapper.text()).not.toContain('手动输入')
  expect(wrapper.find('.question-surface.settings-block-surface').exists()).toBe(true)
  expect(wrapper.find('textarea').exists()).toBe(false)
  const confirm = wrapper.get<HTMLButtonElement>('button[type="submit"]')
  await input.setValue('   ')
  expect(confirm.element.disabled).toBe(true)
  await input.setValue('芙宁娜')
  expect(wrapper.emitted('answer')).toBeUndefined()
  await wrapper.get('form').trigger('submit')
  expect(wrapper.emitted('answer')![0]).toEqual([{ q1: { selected_options: [], text: '芙宁娜' } }])
})
