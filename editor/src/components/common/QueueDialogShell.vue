<!--
  Shared queue-detail dialog shell.

  Provides the exact modal surface, action row, and content-height transition
  used by queue pages while each domain supplies its own form and detail body.
-->
<script setup lang="ts">
import { nextTick, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  wide?: boolean
  contentKey?: string
}>(), {
  wide: false,
  contentKey: '',
})

const emit = defineEmits<{ close: [] }>()
let dialogElement: HTMLElement | null = null
let transitionEnd: ((event: TransitionEvent) => void) | null = null

/** Animate status-dependent form height without constraining normal overflow. */
async function animateHeight(): Promise<void> {
  const dialog = document.querySelector<HTMLElement>('.queue-dialog')
  if (!dialog) return
  if (dialogElement && transitionEnd) dialogElement.removeEventListener('transitionend', transitionEnd)
  dialogElement = dialog
  dialog.style.height = `${dialog.getBoundingClientRect().height}px`
  await nextTick()
  dialog.style.height = 'auto'
  const nextHeight = dialog.scrollHeight
  transitionEnd = (event: TransitionEvent) => {
    if (event.propertyName !== 'height' || event.target !== dialog) return
    dialog.style.height = 'auto'
    dialog.removeEventListener('transitionend', transitionEnd as (event: TransitionEvent) => void)
    transitionEnd = null
  }
  dialog.addEventListener('transitionend', transitionEnd)
  requestAnimationFrame(() => { dialog.style.height = `${nextHeight}px` })
}

watch(() => [props.open, props.contentKey], () => { if (props.open) void animateHeight() })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="queue-dialog-backdrop" @click.self="emit('close')">
      <section class="queue-dialog" :class="{ wide }" role="dialog" aria-modal="true" :aria-label="title">
        <header class="dialog-head">
          <h2>{{ title }}</h2>
          <button class="icon-btn" type="button" title="关闭" aria-label="关闭" @click="emit('close')"><IcIcon name="close" :size="16" /></button>
        </header>
        <slot></slot>
        <footer v-if="$slots.footer" class="dialog-actions"><slot name="footer"></slot></footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.queue-dialog-backdrop { position:fixed; inset:0; z-index:300; display:grid; place-items:center; padding:16px; background:rgba(0,0,0,.42); }
.queue-dialog { display:grid; gap:14px; width:min(760px,calc(100vw - 32px)); max-height:calc(100vh - 32px); overflow:auto; border:1px solid var(--color-border); border-radius:28px; background:var(--color-surface); color:var(--color-text); font-size:calc(13px * var(--font-scale)); transition:height 280ms cubic-bezier(.22,1,.36,1); }
.queue-dialog.wide { width:min(1280px,calc(100vw - 32px)); }
.dialog-head { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:7px 16px; }
.dialog-head h2 { margin:0; font-size:calc(15px * var(--font-scale)); }
.icon-btn { display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; padding:0; border:0; border-radius:50%; background:transparent; color:var(--color-text-muted); cursor:pointer; }
.icon-btn:hover { background:color-mix(in srgb,var(--color-text-secondary) 10%,transparent); color:var(--color-text); }
.dialog-actions { display:flex; align-items:center; gap:8px; padding:16px; }
.dialog-actions :deep(> span) { flex:1; }
.dialog-actions :deep(.submit-actions) { display:inline-flex; align-items:center; gap:8px; }
.dialog-actions :deep(button) { display:inline-flex; align-items:center; justify-content:center; gap:6px; min-height:32px; padding:0 16px; border:1px solid var(--color-border); border-radius:999px; background:var(--color-surface-raised); color:var(--color-text); font:inherit; font-size:calc(13px * var(--font-scale)); cursor:pointer; }
.dialog-actions :deep(button:active) { transform:scale(.98); }
.dialog-actions :deep(.primary-btn) { border-color:var(--color-primary); background:var(--color-primary); color:#fff; }
.dialog-actions :deep(.danger-btn) { border-color:var(--color-danger); color:var(--color-danger); }
@media (max-width:480px) { .queue-dialog-backdrop { padding:8px; }.queue-dialog,.queue-dialog.wide { width:calc(100vw - 16px); max-height:calc(100dvh - 16px); border-radius:22px; }.dialog-actions { flex-wrap:wrap; padding:12px; } }
@media (prefers-reduced-motion:reduce) { .queue-dialog { transition:none; } }
</style>
