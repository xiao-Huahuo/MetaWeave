<!--
  Unified local small-icon component.

  Usage:
  Callers pick a semantic name. Protocol/feature icons and exact DSH matches render from local SVG assets;
  missing semantics use bundled morphicons/Lucide data. Set morph on a stable
  stateful instance so icon-name changes animate instead of swapping abruptly.
-->
<script setup lang="ts">
import { MorphIcon } from 'morphicons/vue'
import { computed, useAttrs } from 'vue'

import { DSH_ICON_FILES, FEATURE_ICON_FILES, FALLBACK_MORPH_ICON, MORPH_ICONS } from './iconRegistry'

defineOptions({ name: 'IcIcon', inheritAttrs: false })

const props = withDefaults(defineProps<{
  name: string
  size?: number
  morph?: boolean
}>(), {
  size: 18,
  morph: false,
})

const attrs = useAttrs()
const rawIcons = {
  ...import.meta.glob('@/assets/icons/svg/dsh/*.svg', {
    query: '?raw', import: 'default', eager: true,
  }),
  ...import.meta.glob('@/assets/icons/svg/features/*.svg', {
    query: '?raw', import: 'default', eager: true,
  }),
} as Record<string, string>

const rawIconsByFile = Object.fromEntries(
  Object.entries(rawIcons).map(([path, raw]) => [path.split('/').pop(), raw]),
)
const featureFile = computed(() => FEATURE_ICON_FILES[props.name])
const localFile = computed(() => featureFile.value ?? DSH_ICON_FILES[props.name])
const useMorphIcon = computed(() => (props.morph && !featureFile.value) || !localFile.value)
const morphIcon = computed(() => MORPH_ICONS[props.name] ?? FALLBACK_MORPH_ICON)
const localRaw = computed(() => localFile.value ? rawIconsByFile[localFile.value] ?? '' : '')

const svgInner = computed(() => {
  const match = localRaw.value.match(/<svg[^>]*>([\s\S]*)<\/svg>/u)
  return match ? match[1] : ''
})
const viewBox = computed(() => localRaw.value.match(/viewBox="([^"]+)"/u)?.[1] ?? '0 0 16 16')
</script>

<template>
  <MorphIcon
    v-if="useMorphIcon"
    v-bind="attrs"
    class="ic-icon"
    data-icon-source="morphicons"
    :data-icon-name="name"
    :icon="morphIcon"
    :size="size"
    :stroke-width="1.8"
    :style="{ fontSize: `${size}px` }"
    spring="snappy"
    reduced-motion="user"
  />
  <svg
    v-else
    v-bind="attrs"
    class="ic-icon"
    :data-icon-source="featureFile ? 'feature' : 'dsh'"
    :data-icon-name="name"
    xmlns="http://www.w3.org/2000/svg"
    width="1em"
    height="1em"
    :viewBox="viewBox"
    fill="currentColor"
    :style="{ fontSize: `${size}px` }"
    :aria-hidden="true"
    v-html="svgInner"
  ></svg>
</template>

<style scoped>
.ic-icon {
  display: block;
  flex: 0 0 auto;
  width: 1em;
  height: 1em;
}
</style>
