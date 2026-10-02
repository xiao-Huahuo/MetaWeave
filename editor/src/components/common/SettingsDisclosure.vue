<!-- Animated settings disclosure: shared rail chevron with measured height, opacity and movement on enter/leave. -->
<script setup lang="ts">
import { ref, useId } from 'vue'
import DisclosureChevron from './DisclosureChevron.vue'
const props = withDefaults(defineProps<{ label: string; defaultOpen?: boolean; disabled?: boolean }>(), { defaultOpen: false, disabled: false })
const emit = defineEmits<{ toggle: [open: boolean] }>()
const open = ref(props.defaultOpen)
const panelId = useId()
/** Keep slot content mounted so forms and credentials survive collapse. */
function toggle() { open.value = !open.value; emit('toggle', open.value) }
/** Measure real content instead of imposing the rail menu's 240px ceiling on long tool lists. */
function beforeEnter(element: Element) {
  const node = element as HTMLElement
  if (!node.style.height) node.style.height = '0px'
}
function enter(element: Element) {
  const node = element as HTMLElement
  void node.offsetHeight
  node.style.height = `${node.scrollHeight}px`
}
function beforeLeave(element: Element) { (element as HTMLElement).style.height = `${element.getBoundingClientRect().height}px` }
function leave(element: Element) {
  const node = element as HTMLElement
  void node.offsetHeight
  node.style.height = '0px'
}
function finish(element: Element) { (element as HTMLElement).style.height = '' }
/** Rapid direction changes continue from the visible height instead of jumping to auto or zero. */
function freeze(element: Element) { (element as HTMLElement).style.height = `${element.getBoundingClientRect().height}px` }
</script>
<template>
  <div class="settings-disclosure">
    <div class="settings-disclosure-heading">
      <button class="settings-disclosure-trigger" type="button" :disabled="disabled" :aria-expanded="open" :aria-controls="panelId" @click="toggle">
        <span>{{ label }}</span><DisclosureChevron :open="open" />
      </button>
      <slot name="actions" />
    </div>
    <Transition name="settings-disclosure" @before-enter="beforeEnter" @enter="enter" @after-enter="finish"
      @before-leave="beforeLeave" @leave="leave" @after-leave="finish" @enter-cancelled="freeze" @leave-cancelled="freeze">
      <div v-show="open" :id="panelId" class="settings-disclosure-panel"><div class="settings-disclosure-content"><slot /></div></div>
    </Transition>
  </div>
</template>
<style scoped>
.settings-disclosure { min-width: 0; font-size: calc(12px * var(--font-scale)); }
.settings-disclosure-heading { display: flex; align-items: center; gap: var(--space-8); }
.settings-disclosure-trigger { display: flex; align-items: center; justify-content: space-between; flex: 1; min-width: 0; gap: var(--space-12); width: 100%; padding: var(--space-8) 0; border: 0; background: transparent; color: var(--color-text-secondary); font: inherit; text-align: left; cursor: pointer; }
.settings-disclosure-trigger > span { min-width: 0; overflow-wrap: anywhere; }
.settings-disclosure-trigger:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.settings-disclosure-panel { min-width: 0; }
.settings-disclosure-content { min-width: 0; padding-block: var(--space-4); }
</style>
<style src="./settings-disclosure-motion.css" scoped></style>
