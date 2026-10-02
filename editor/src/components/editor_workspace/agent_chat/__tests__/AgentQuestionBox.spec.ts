/* Question interaction contracts: immediate single choice, preserved multi-page drafts and complete batch submission. */
import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import AgentQuestionBox from '../AgentQuestionBox.vue'
import type { AgentQuestionRequest } from '@/api/agent'

const request: AgentQuestionRequest = {
  request_id: 'question1', user_id: 'u1', session_id: 's1', run_id: 'r1', status: 'pending',
  questions: [{ id: 'q1', question: '选择处理方式', options: ['阅读', '编辑'], multi_select: false, allow_text: false }],
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
    { id: 'q2', question: '选择输出', options: ['摘要', '原文'], multi_select: true, allow_text: true }] } } })
  const confirm = wrapper.get<HTMLButtonElement>('button[type="submit"]')
  expect(confirm.element.disabled).toBe(true)
  await wrapper.get('input[type="radio"]').setValue(true)
  expect(wrapper.emitted('answer')).toBeUndefined()
  await wrapper.get('[aria-label="下一个问题"]').trigger('click')
  for (const input of wrapper.findAll('input[type="checkbox"]')) await input.setValue(true)
  await wrapper.get('textarea').setValue('保留引用')
  await wrapper.get('[aria-label="上一个问题"]').trigger('click')
  expect(wrapper.get<HTMLInputElement>('input[type="radio"]').element.checked).toBe(true)
  await wrapper.get('[aria-label="下一个问题"]').trigger('click')
  expect(wrapper.get<HTMLTextAreaElement>('textarea').element.value).toBe('保留引用')
  expect(confirm.element.disabled).toBe(false)
  await confirm.trigger('submit')
  expect(wrapper.emitted('answer')![0]).toEqual([{ q1: { selected_options: ['阅读'], text: '' }, q2: { selected_options: ['摘要', '原文'], text: '保留引用' } }])
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
