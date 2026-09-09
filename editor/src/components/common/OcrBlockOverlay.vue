<!--
  OCR spatial block overlay.

  Place inside the same positioned element as an image or PDF page so native
  scroll and zoom transforms affect pixels and boxes identically.
-->
<script setup lang="ts">
import { computed } from 'vue'

import type { ScannerOcrBlock } from '@/api/scanner'

const props = defineProps<{
  blocks: ScannerOcrBlock[]
  page: number
  width: number
  height: number
  activeBlockId?: string
  lockedBlockId?: string
}>()
const emit = defineEmits<{
  blockHover: [blockId: string]
  blockLeave: []
  blockSelect: [blockId: string]
}>()

const visibleBlocks = computed(() => props.blocks.filter((block) => (
  block.page === props.page
  && block.bbox.length === 4
  && block.bbox.every(Number.isFinite)
)))

/** Use a persisted id when available and a page/order key otherwise. */
function blockId(block: ScannerOcrBlock): string {
  return `${block.page}:${block.id ?? block.order}`
}
</script>

<template>
  <svg
    v-if="width > 0 && height > 0"
    class="ocr-block-overlay"
    :viewBox="`0 0 ${width} ${height}`"
    preserveAspectRatio="none"
    aria-label="OCR 结构区域"
    @pointerleave="emit('blockLeave')"
  >
    <rect
      v-for="block in visibleBlocks"
      :key="blockId(block)"
      class="ocr-block"
      :class="{
        active: activeBlockId === blockId(block),
        locked: lockedBlockId === blockId(block),
      }"
      :data-block-id="blockId(block)"
      :x="block.bbox[0]"
      :y="block.bbox[1]"
      :width="Math.max(0, block.bbox[2] - block.bbox[0])"
      :height="Math.max(0, block.bbox[3] - block.bbox[1])"
      vector-effect="non-scaling-stroke"
      @pointerenter="emit('blockHover', blockId(block))"
      @pointerdown.stop
      @click.stop="emit('blockSelect', blockId(block))"
    />
  </svg>
</template>

<style scoped>
.ocr-block-overlay { position: absolute; inset: 0; z-index: 2; width: 100%; height: 100%; overflow: visible; pointer-events: none; }
.ocr-block { fill: color-mix(in srgb,var(--color-primary) 7%,transparent); stroke: color-mix(in srgb,var(--color-primary) 72%,white); stroke-width: 1.25; pointer-events: auto; cursor: pointer; transition: fill 120ms ease, stroke-width 120ms ease; }
.ocr-block.active,.ocr-block.locked { fill: color-mix(in srgb,var(--color-primary) 20%,transparent); stroke: var(--color-primary); stroke-width: 2; }
.ocr-block.locked { stroke-dasharray: 5 3; }
@media (prefers-reduced-motion: reduce) { .ocr-block { transition: none; } }
</style>
