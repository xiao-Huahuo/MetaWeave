<!-- Synchronous Agent questions above ChatInput; uses settings checkboxes, form surfaces and measured page motion. -->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId } from 'vue'
import CreativeCheckbox from '@/components/common/CreativeCheckbox.vue'
import FormHeightTransition from '@/components/common/FormHeightTransition.vue'
import IcIcon from '@/components/common/IcIcon.vue'
import type { AgentQuestionAnswer, AgentQuestionRequest } from '@/api/agent'

const props = defineProps<{ request: AgentQuestionRequest; submitting?: boolean; error?: string }>()
const emit = defineEmits<{ answer: [answers: Record<string, AgentQuestionAnswer>] }>()
const index = ref(0)
/** Discardable, unsent UI drafts; keyed by question so backward navigation keeps selections. */
const answers = ref<Record<string, AgentQuestionAnswer>>(Object.fromEntries(props.request.questions.map(question => [question.id, { selected_options: [], text: '' }])))
const prefix = useId()
const panel = ref<HTMLElement | null>(null)
const current = computed(() => props.request.questions[index.value]!)
const currentAnswer = computed(() => answers.value[current.value.id]!)
const multiple = computed(() => props.request.questions.length > 1)
const complete = computed(() => props.request.questions.every(question => {
  const answer = answers.value[question.id]
  return Boolean(answer?.selected_options.length || answer?.text.trim())
}))
const needsConfirm = computed(() => multiple.value || current.value.multi_select || current.value.allow_text || Boolean(props.error))

/** A single radio choice submits immediately; multiple choices are submitted together. */
function select(option: string, checked: boolean) {
  if (props.submitting) return
  const answer = currentAnswer.value
  answer.selected_options = current.value.multi_select
    ? checked ? [...answer.selected_options, option] : answer.selected_options.filter(value => value !== option)
    : [option]
  if (!multiple.value && !current.value.multi_select) submit()
}
/** Keep submission atomic and reject unfinished batches even when triggered by Enter. */
function submit() {
  if (complete.value && !props.submitting) emit('answer', Object.fromEntries(Object.entries(answers.value).map(([id, answer]) => [id, { selected_options: [...answer.selected_options], text: answer.text }])))
}
/** Keyboard focus follows navigation without trapping the rest of the chat. */
async function focusQuestion() {
  await nextTick()
  panel.value?.querySelector<HTMLElement>('input, textarea')?.focus()
}
function navigate(offset: number) {
  index.value = Math.max(0, Math.min(props.request.questions.length - 1, index.value + offset))
  void focusQuestion()
}
onMounted(focusQuestion)
</script>

<template>
  <form ref="panel" class="agent-question-box" aria-label="Agent 提问" :aria-busy="submitting" @submit.prevent="submit">
    <header v-if="multiple" class="question-navigation">
      <span class="question-number">{{ index + 1 }} / {{ request.questions.length }}</span>
      <div class="question-arrows">
        <button class="v1-icon-button" type="button" aria-label="上一个问题" :disabled="index === 0 || submitting" @click="navigate(-1)"><IcIcon name="arrow-left" :size="16" /></button>
        <button class="v1-icon-button" type="button" aria-label="下一个问题" :disabled="index === request.questions.length - 1 || submitting" @click="navigate(1)"><IcIcon name="arrow-right" :size="16" /></button>
      </div>
    </header>
    <FormHeightTransition :watch-key="index">
      <fieldset :key="current.id" :disabled="submitting" class="question-content">
        <legend class="question-title">{{ current.question }}</legend>
        <div class="question-options">
          <div v-for="(option, optionIndex) in current.options" :key="option" class="question-option" :class="{ selected: currentAnswer.selected_options.includes(option) }">
            <CreativeCheckbox :input-id="`${prefix}-${index}-${optionIndex}`" :name="`${prefix}-${index}`" :input-type="current.multi_select ? 'checkbox' : 'radio'"
              :model-value="currentAnswer.selected_options.includes(option)" :label="option" :disabled="submitting" @update:model-value="select(option, $event)" />
            <label :for="`${prefix}-${index}-${optionIndex}`">{{ option }}</label>
          </div>
        </div>
        <label v-if="current.allow_text" class="question-text-label" :for="`${prefix}-text-${index}`">手动输入</label>
        <textarea v-if="current.allow_text" :id="`${prefix}-text-${index}`" v-model="currentAnswer.text" class="form-input-surface question-text" rows="2" />
      </fieldset>
    </FormHeightTransition>
    <p v-if="error" class="question-error" role="alert">{{ error }}</p>
    <footer v-if="needsConfirm" class="question-footer">
      <button class="question-confirm" type="submit" :disabled="!complete || submitting">{{ submitting ? '提交中…' : '确定' }}</button>
    </footer>
  </form>
</template>

<style scoped>
.agent-question-box { min-width: 0; max-height: min(45dvh, 380px); overflow: auto; box-sizing: border-box; padding: var(--space-12) var(--space-16); border: 0; border-radius: var(--radius-xl); background: var(--input-bg); color: var(--color-text); font-family: var(--font-ui); font-size: var(--font-size-sm); }
.question-navigation, .question-arrows { display: flex; align-items: center; }
.question-navigation { justify-content: space-between; gap: var(--space-8); margin-bottom: var(--space-4); }
.question-number { color: var(--color-text-secondary); font-variant-numeric: tabular-nums; }
.question-content { min-width: 0; margin: 0; padding: 0; border: 0; }
.question-title { width: 100%; box-sizing: border-box; padding: 0 0 var(--space-8); font-weight: var(--font-weight-medium); line-height: var(--line-height-normal); overflow-wrap: anywhere; }
.question-options { display: grid; gap: var(--space-4); }
.question-option { display: flex; align-items: center; gap: var(--space-8); min-width: 0; padding: var(--space-8) var(--space-4); border-radius: var(--radius-sm); transition: background var(--transition-fast); }
.question-option:hover, .question-option.selected { background: var(--color-primary-softer); }
.question-option > label:not(.creative-checkbox) { flex: 1; min-width: 0; cursor: pointer; overflow-wrap: anywhere; line-height: var(--line-height-normal); }
.question-text-label { display: block; margin-block: var(--space-8) var(--space-4); }
.question-text { width: 100%; min-height: 60px; max-height: 120px; box-sizing: border-box; padding: var(--space-8); border-radius: var(--radius-md); outline: none; color: var(--color-text); font: inherit; resize: vertical; }
.question-footer { display: flex; justify-content: flex-end; margin-top: var(--space-8); }
.question-confirm { min-height: 30px; padding: var(--space-4) var(--space-12); border: 0; border-radius: var(--radius-sm); background: var(--color-text); color: var(--color-surface); font: inherit; cursor: pointer; transition: opacity var(--transition-fast), transform var(--transition-fast); }
.question-confirm:active:not(:disabled) { transform: translateY(1px); }
.question-confirm:disabled { opacity: .4; cursor: default; }
.question-confirm:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.question-error { margin: var(--space-8) 0 0; color: var(--color-danger); overflow-wrap: anywhere; }
@media (max-width: 480px) { .agent-question-box { padding: var(--space-10) var(--space-12); max-height: 40dvh; } }
@media (prefers-reduced-motion: reduce) { .question-option, .question-confirm { transition: none; } }
</style>
