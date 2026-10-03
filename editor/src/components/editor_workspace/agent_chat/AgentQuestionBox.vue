<!-- Synchronous Agent questions above ChatInput; uses settings checkboxes, form surfaces and measured page motion. -->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import CreativeCheckbox from '@/components/common/CreativeCheckbox.vue'
import FormHeightTransition from '@/components/common/FormHeightTransition.vue'
import IcIcon from '@/components/common/IcIcon.vue'
import type { AgentQuestion, AgentQuestionAnswer, AgentQuestionRequest } from '@/api/agent'

const props = defineProps<{ request: AgentQuestionRequest; submitting?: boolean; error?: string }>()
const emit = defineEmits<{ answer: [answers: Record<string, AgentQuestionAnswer>] }>()
const index = ref(0)
/** Discardable, unsent UI drafts; keyed by question so backward navigation keeps selections. */
const answers = ref<Record<string, AgentQuestionAnswer>>(Object.fromEntries(props.request.questions.map(question => [question.id, { selected_options: [], text: '' }])))
const prefix = useId()
const panel = ref<HTMLElement | null>(null)
const track = ref<HTMLElement | null>(null)
const transitioning = ref(false)
/** This component owns the bounded CSS-transition fallback and clears it on disposal. */
let transitionFallback: ReturnType<typeof setTimeout> | undefined
const current = computed(() => props.request.questions[index.value]!)
/** Legacy pure input requests remain readable; a choice question never gains a second text task. */
function isInputQuestion(question: AgentQuestion) {
  return question.type === 'input' || (!question.type && question.options.length === 0 && question.allow_text)
}
const isInput = computed(() => isInputQuestion(current.value))
const currentAnswer = computed(() => answers.value[current.value.id]!)
const multiple = computed(() => props.request.questions.length > 1)
const complete = computed(() => props.request.questions.every(question => {
  const answer = answers.value[question.id]
  const input = isInputQuestion(question)
  return input ? Boolean(answer?.text.trim()) : Boolean(answer?.selected_options.length)
}))
const needsConfirm = computed(() => multiple.value || current.value.multi_select || isInput.value || Boolean(props.error))
const trackStyle = computed(() => ({ transform: `translateX(-${index.value * 100}%)` }))

/** All page drafts are initialized from the immutable request and remain mounted during sliding. */
function answerFor(id: string) { return answers.value[id]! }

/** A single radio choice submits immediately; multiple choices are submitted together. */
function select(questionId: string, option: string, checked: boolean) {
  if (props.submitting || transitioning.value || questionId !== current.value.id || isInput.value) return
  const answer = currentAnswer.value
  answer.selected_options = current.value.multi_select
    ? checked ? [...answer.selected_options, option] : answer.selected_options.filter(value => value !== option)
    : [option]
  if (!current.value.multi_select) {
    if (multiple.value) navigate(1)
    else submit()
  }
}
/** Keep submission atomic and reject unfinished batches even when triggered by Enter. */
function submit() {
  if (complete.value && !props.submitting) emit('answer', Object.fromEntries(Object.entries(answers.value).map(([id, answer]) => [id, { selected_options: [...answer.selected_options], text: answer.text }])))
}
/** Keyboard focus follows navigation without trapping the rest of the chat. */
async function focusQuestion() {
  await nextTick()
  panel.value?.querySelector<HTMLElement>('.question-content.is-active input')?.focus()
}
/** Release navigation after real motion, cancellation, reduced motion or its bounded fallback. */
function finishSlide() {
  if (transitionFallback !== undefined) clearTimeout(transitionFallback)
  transitionFallback = undefined
  transitioning.value = false
  void focusQuestion()
}
function onTrackTransition(event: TransitionEvent) {
  if (event.target === track.value && event.propertyName === 'transform') finishSlide()
}
function navigate(offset: number) {
  if (props.submitting || transitioning.value) return
  const next = Math.max(0, Math.min(props.request.questions.length - 1, index.value + offset))
  if (next === index.value) return
  const duration = track.value ? Number.parseFloat(getComputedStyle(track.value).transitionDuration) : 0
  transitioning.value = duration > 0 && !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  index.value = next
  if (transitioning.value) transitionFallback = setTimeout(finishSlide, 700)
  else void nextTick(finishSlide)
}
/** Enter explicitly completes multi-select/input; IME confirmation and repeated keys never advance. */
function completeOnEnter(event: KeyboardEvent) {
  if (event.isComposing || (event.target as HTMLElement).closest('button')) return
  event.preventDefault()
  if (event.repeat || event.isComposing || props.submitting || transitioning.value) return
  const answered = isInput.value ? currentAnswer.value.text.trim() : currentAnswer.value.selected_options.length
  if (!answered) return
  if (!multiple.value) submit()
  else if (index.value < props.request.questions.length - 1) navigate(1)
  else panel.value?.querySelector<HTMLButtonElement>('.question-confirm')?.focus()
}
onMounted(focusQuestion)
onBeforeUnmount(() => { if (transitionFallback !== undefined) clearTimeout(transitionFallback) })
</script>

<template>
  <form ref="panel" class="agent-question-box" aria-label="Agent 提问" :aria-busy="submitting" @submit.prevent="submit" @keydown.enter="completeOnEnter">
    <!-- Only the decorative surface overlaps the composer; text and controls stay above it. -->
    <div class="question-surface settings-block-surface" aria-hidden="true"></div>
    <div class="question-body">
    <header class="question-header">
    <div v-if="multiple" class="question-navigation">
      <span class="question-number">{{ index + 1 }} / {{ request.questions.length }}</span>
      <div class="question-arrows">
        <button class="v1-icon-button" type="button" aria-label="上一个问题" :disabled="index === 0 || submitting || transitioning" @click="navigate(-1)"><IcIcon name="arrow-left" :size="16" /></button>
        <button class="v1-icon-button" type="button" aria-label="下一个问题" :disabled="index === request.questions.length - 1 || submitting || transitioning" @click="navigate(1)"><IcIcon name="arrow-right" :size="16" /></button>
      </div>
    </div>
    <div class="question-carousel-viewport">
      <div class="question-carousel-track" :style="trackStyle">
        <h3 v-for="(question, pageIndex) in request.questions" :id="`${prefix}-title-${pageIndex}`" :key="question.id"
          class="question-title question-carousel-page" :class="{ 'is-active': pageIndex === index }" :aria-hidden="pageIndex !== index">{{ question.question }}</h3>
      </div>
    </div>
    </header>
    <FormHeightTransition :watch-key="index">
      <div class="question-carousel-viewport">
      <div ref="track" class="question-carousel-track" :style="trackStyle" @transitionend="onTrackTransition" @transitioncancel="onTrackTransition">
      <fieldset v-for="(question, pageIndex) in request.questions" :key="question.id" :disabled="submitting || transitioning || pageIndex !== index"
        :inert="pageIndex !== index" :aria-hidden="pageIndex !== index" class="question-content question-carousel-page" :class="{ 'is-active': pageIndex === index }" :aria-labelledby="`${prefix}-title-${pageIndex}`">
        <div v-if="!isInputQuestion(question)" class="question-options">
          <div v-for="(option, optionIndex) in question.options" :key="option" class="question-option" :class="{ selected: answerFor(question.id).selected_options.includes(option) }">
            <CreativeCheckbox :input-id="`${prefix}-${pageIndex}-${optionIndex}`" :name="`${prefix}-${pageIndex}`" :input-type="question.multi_select ? 'checkbox' : 'radio'"
              :model-value="answerFor(question.id).selected_options.includes(option)" :label="option" :disabled="submitting || transitioning || pageIndex !== index" @update:model-value="select(question.id, option, $event)" />
            <label :for="`${prefix}-${pageIndex}-${optionIndex}`">{{ option }}</label>
          </div>
        </div>
        <input v-if="isInputQuestion(question)" :id="`${prefix}-text-${pageIndex}`" v-model="answerFor(question.id).text" type="text"
          :aria-label="question.question" class="form-input-capsule question-text" placeholder="试试手动输入" autocomplete="off" />
      </fieldset>
      </div>
      </div>
    </FormHeightTransition>
    <p v-if="error" class="question-error" role="alert">{{ error }}</p>
    <footer v-if="needsConfirm" class="question-footer">
      <button class="question-confirm" type="submit" :disabled="!complete || submitting">{{ submitting ? '提交中…' : '确定' }}</button>
    </footer>
    </div>
  </form>
</template>

<style scoped>
.agent-question-box { position: relative; min-width: 0; box-sizing: border-box; padding: var(--space-12) var(--space-16) calc(var(--question-overlap, 32px) + var(--space-12)); border: 0; color: var(--color-text); font-family: var(--font-chat); font-size: var(--font-size-base); }
.question-surface { position: absolute; inset: 0; z-index: 0; pointer-events: none; }
.question-carousel-viewport { position: relative; min-width: 0; overflow: hidden; }
/* Match the existing home carousel: full-width slides move together in either direction. */
.question-carousel-track { display: flex; align-items: flex-start; width: 100%; transition: transform 600ms cubic-bezier(0.22, 1, 0.36, 1); }
.question-carousel-page { flex: 0 0 100%; width: 100%; min-width: 0; min-height: 0; box-sizing: border-box; }
.question-carousel-page:not(.is-active) { height: 0; overflow: visible; }
.question-body { position: relative; z-index: 2; min-width: 0; max-height: min(45dvh, 380px); overflow: auto; padding: var(--space-4); }
/* Keep the current question and navigation available when long choices need their own scroll. */
.question-header { position: sticky; top: 0; z-index: 1; background: var(--color-surface); }
.question-navigation, .question-arrows { display: flex; align-items: center; }
.question-navigation { justify-content: space-between; gap: var(--space-8); margin-bottom: var(--space-4); }
.question-number { color: var(--color-text-secondary); font-variant-numeric: tabular-nums; }
.question-content { min-width: 0; margin: 0; padding: 0; border: 0; }
.question-title { width: 100%; box-sizing: border-box; margin: 0; padding: 0 0 var(--space-8); font-size: var(--font-size-base); font-weight: var(--font-weight-medium); line-height: var(--line-height-normal); overflow-wrap: anywhere; }
.question-options { display: grid; gap: var(--space-4); }
.question-option { display: flex; align-items: center; gap: var(--space-8); min-width: 0; padding: var(--space-8) var(--space-12); border-radius: 999px; transition: background var(--transition-fast); }
.question-option:hover, .question-option.selected { background: var(--color-primary-softer); }
.question-option > label:not(.creative-checkbox) { flex: 1; min-width: 0; cursor: pointer; overflow-wrap: anywhere; line-height: var(--line-height-normal); }
.question-text { width: 100%; min-width: 0; min-height: 38px; box-sizing: border-box; margin-block: var(--space-4); padding: var(--space-8) var(--space-12); outline: none; color: var(--color-text); font: inherit; }
.question-text::placeholder { color: var(--color-text-muted); }
.question-footer { position: sticky; bottom: 0; z-index: 1; display: flex; justify-content: flex-end; margin-top: var(--space-8); padding-top: var(--space-4); background: var(--color-surface); }
.question-confirm { min-height: 32px; padding: var(--space-4) var(--space-16); border: 0; border-radius: 999px; background: var(--color-text); color: var(--color-surface); font: inherit; cursor: pointer; transition: opacity var(--transition-fast), transform var(--transition-fast); }
.question-confirm:active:not(:disabled) { transform: translateY(1px); }
.question-confirm:disabled { opacity: .4; cursor: default; }
.question-confirm:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.question-error { margin: var(--space-8) 0 0; color: var(--color-danger); overflow-wrap: anywhere; }
@media (max-width: 480px) { .agent-question-box { padding: var(--space-10) var(--space-8) calc(var(--question-overlap, 32px) + var(--space-12)); } .question-body { max-height: 40dvh; } .question-option { padding-inline: var(--space-4); } }
@media (prefers-reduced-motion: reduce) { .question-option, .question-confirm, .question-carousel-track { transition: none; } }
</style>
