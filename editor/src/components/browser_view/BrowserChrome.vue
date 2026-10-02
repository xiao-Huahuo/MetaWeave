<!--
  Workspace browser chrome.

  Usage:
  BrowserPage provides navigation state and commands. This component renders
  the tab/address chrome and reports the exact native web-surface bounds.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'

defineOptions({ name: 'BrowserChrome' })

const address = defineModel<string>('address', { required: true })
const props = defineProps<{
  state: BrowserViewState
  desktopAvailable: boolean
  proxyActive: boolean
  sidebar?: boolean
}>()
const emit = defineEmits<{
  bounds: [bounds: BrowserViewBounds]
  command: [command: 'back' | 'forward' | 'home' | 'reload' | 'stop' | 'external']
  navigate: [value: string]
  openSettings: []
  closeSidebar: []
}>()

const surface = ref<HTMLElement | null>(null)
let resizeObserver: ResizeObserver | null = null

const shortTitle = computed(() => props.state.title?.trim() || '新标签页')

/** Mirror the DOM viewport rectangle to Electron's native View coordinates. */
function reportBounds() {
  const rect = surface.value?.getBoundingClientRect()
  if (!rect || rect.width < 1 || rect.height < 1) return
  const frame = surface.value?.closest<HTMLElement>('.browser-frame')
  if (!frame) return
  emit('bounds', {
    x: rect.x, y: rect.y, width: rect.width, height: rect.height,
    borderRadius: Number.parseFloat(getComputedStyle(frame).borderBottomLeftRadius) || 0,
  })
}

/** Navigate from the address field without imposing URL syntax on the user. */
function submitAddress() {
  if (address.value.trim()) emit('navigate', address.value)
}

onMounted(async () => {
  await nextTick()
  resizeObserver = new ResizeObserver(reportBounds)
  if (surface.value) resizeObserver.observe(surface.value)
  window.addEventListener('resize', reportBounds)
  reportBounds()
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('resize', reportBounds)
})
</script>

<template>
  <section class="browser-frame" aria-label="内置浏览器">
    <div class="tabs-head">
      <div class="active-tab" :title="shortTitle">
        <span class="tab-round tab-round-left"><i></i></span>
        <IcIcon name="language" :size="14" />
        <span class="tab-title">{{ shortTitle }}</span>
        <button
          v-if="sidebar"
          class="browser-tab-close"
          type="button"
          title="关闭右侧浏览器"
          aria-label="关闭右侧浏览器"
          @click="$emit('closeSidebar')"
        >
          <IcIcon name="close" :size="13" />
        </button>
        <span class="tab-round tab-round-right"><i></i></span>
      </div>
      <div class="browser-status">
        <span class="proxy-state" :class="{ active: proxyActive }">
          {{ proxyActive ? '代理' : '直连' }}
        </span>
        <button type="button" title="浏览器设置" aria-label="浏览器设置" @click="$emit('openSettings')">
          <IcIcon name="settings" :size="16" />
        </button>
      </div>
    </div>

    <div class="browser-toolbar">
      <button
        type="button"
        title="后退"
        aria-label="后退"
        :disabled="!state.canGoBack"
        @click="$emit('command', 'back')"
      >
        <IcIcon name="arrow-left" :size="17" />
      </button>
      <button
        type="button"
        title="前进"
        aria-label="前进"
        :disabled="!state.canGoForward"
        @click="$emit('command', 'forward')"
      >
        <IcIcon name="arrow-right" :size="17" />
      </button>
      <button
        type="button"
        :title="state.loading ? '停止' : '刷新'"
        :aria-label="state.loading ? '停止' : '刷新'"
        @click="$emit('command', state.loading ? 'stop' : 'reload')"
      >
        <IcIcon :name="state.loading ? 'close' : 'refresh'" :size="16" morph :class="{ spinning: state.loading }" />
      </button>
      <button type="button" title="主页" aria-label="主页" @click="$emit('command', 'home')">
        <IcIcon name="home" :size="16" />
      </button>

      <div class="address-shell">
        <IcIcon name="lock" :size="13" />
        <input
          v-model="address"
          type="text"
          autocomplete="off"
          spellcheck="false"
          aria-label="地址和搜索栏"
          placeholder="搜索 Google 或输入网址"
          @keydown.enter.prevent="submitAddress"
        />
      </div>

      <button type="button" title="在系统浏览器打开" aria-label="在系统浏览器打开" @click="$emit('command', 'external')">
        <IcIcon name="open-in-new" :size="16" />
      </button>
    </div>

    <div v-if="state.loading" class="loading-line" aria-hidden="true"></div>
    <div ref="surface" class="browser-surface">
      <div v-if="!desktopAvailable" class="desktop-required">
        <IcIcon name="language" :size="28" />
        <strong>内置浏览器仅在 Electron 桌面端可用</strong>
      </div>
    </div>
  </section>
</template>

<style scoped>
.browser-frame {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border-radius: inherit;
  background: var(--color-surface);
}

.tabs-head {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  height: 40px;
  padding: 6px 8px 0 22px;
  background: var(--color-chrome-rail-bg);
}

.active-tab {
  position: relative;
  display: flex;
  align-items: center;
  gap: 7px;
  width: min(240px, 34vw);
  height: 34px;
  padding: 0 12px;
  border-radius: 8px 8px 0 0;
  background: var(--color-surface);
  color: var(--color-text-secondary);
}

.tab-title {
  min-width: 0;
  overflow: hidden;
  font-size: calc(11px * var(--font-scale));
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.browser-tab-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  margin-left: auto;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.browser-tab-close:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.tab-round {
  position: absolute;
  bottom: 0;
  width: 12px;
  height: 12px;
  overflow: hidden;
  background: var(--color-surface);
}

.tab-round i {
  display: block;
  width: 100%;
  height: 100%;
  background: var(--color-chrome-rail-bg);
}

.tab-round-left {
  left: -12px;
}

.tab-round-left i {
  border-radius: 0 0 8px 0;
}

.tab-round-right {
  right: -12px;
}

.tab-round-right i {
  border-radius: 0 0 0 8px;
}

.browser-status {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 34px;
}

.browser-status button,
.browser-toolbar button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-secondary);
}

.browser-status button:hover,
.browser-toolbar button:hover:not(:disabled) {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.browser-toolbar button:disabled {
  opacity: 0.32;
}

.proxy-state {
  padding: 3px 8px;
  border-radius: 999px;
  color: var(--color-text-muted);
  font-size: calc(10px * var(--font-scale));
}

.proxy-state.active {
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.browser-toolbar {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 4px;
  height: 46px;
  padding: 7px 10px;
  background: var(--color-surface);
  box-shadow: 0 1px 0 var(--color-border-subtle);
}

.address-shell {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  gap: 7px;
  min-width: 80px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text-muted);
  transition: border-color 150ms ease, background 150ms ease;
}

.address-shell:focus-within {
  border-color: var(--color-primary);
  background: var(--color-surface-raised);
}

.address-shell input {
  width: 100%;
  min-width: 0;
  padding: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

.loading-line {
  position: absolute;
  top: 84px;
  left: 0;
  z-index: 3;
  width: 28%;
  height: 2px;
  background: var(--color-primary);
  animation: browser-loading 1.2s ease-in-out infinite;
}

.browser-surface {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  background: var(--color-canvas);
}

.desktop-required {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: var(--space-10);
  color: var(--color-text-muted);
}

.desktop-required strong {
  font-size: calc(13px * var(--font-scale));
  font-weight: 500;
}

.spinning {
  animation: browser-spin 800ms linear infinite;
}

@keyframes browser-loading {
  0% { transform: translateX(-110%); }
  55% { width: 42%; }
  100% { transform: translateX(360%); }
}

@keyframes browser-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 680px) {
  .tabs-head {
    padding-left: 18px;
  }

  .active-tab {
    width: min(180px, 48vw);
  }

  .browser-toolbar {
    gap: 2px;
    padding-inline: 6px;
  }

  .browser-toolbar > button:nth-of-type(4) {
    display: none;
  }
}
</style>
