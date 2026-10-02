<!-- Reusable settings subpage switch using the existing terminal/storage slider styles and motion. -->
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
const props = defineProps<{ modelValue: string; pages: Array<{ key: string; label: string }>; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const container = ref<HTMLElement | null>(null)
const slider = ref({ width: '0px', left: '0px' })
let observer: ResizeObserver | undefined
/** Re-measure the active label after fonts, viewport or selection change. */
async function measure() {
  await nextTick()
  const button = container.value?.querySelector<HTMLElement>('[aria-selected="true"]')
  if (button) slider.value = { width: `${button.offsetWidth}px`, left: `${button.offsetLeft}px` }
}
/** Arrow/Home/End keys follow the same tab order as the visual controls. */
function navigate(event: KeyboardEvent) {
  const index = props.pages.findIndex(p => p.key === props.modelValue)
  const offset = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? props.pages.length - 1 : (index + offset + props.pages.length) % props.pages.length
  if (!offset && !['Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const page = props.pages[next]
  if (page) emit('update:modelValue', page.key)
  void nextTick(() => container.value?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus())
}
watch(() => props.modelValue, measure)
onMounted(() => { void measure(); observer = new ResizeObserver(measure); if (container.value) observer.observe(container.value) })
onBeforeUnmount(() => observer?.disconnect())
</script>
<template>
  <div ref="container" class="settings-resource-page-switch" role="tablist" :aria-label="label" @keydown="navigate">
    <span class="settings-resource-page-slider" :style="slider" aria-hidden="true"></span>
    <button v-for="page in pages" :key="page.key" type="button" role="tab" class="settings-resource-page-button"
      :class="{ active: modelValue === page.key }" :aria-selected="modelValue === page.key" :tabindex="modelValue === page.key ? 0 : -1"
      @click="emit('update:modelValue', page.key)">{{ page.label }}</button>
  </div>
</template>
