<!--
  Top command bar.

  Usage:
  Shows the active knowledge root, global actions, and navigation links between
  the editor, graph preview, settings, and existing console.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import PixelLoader from '@/components/common/PixelLoader.vue'
import SearchPalette from '@/components/editor_workspace/SearchPalette.vue'
import { modelLifecycleUi, requestModelLifecycleExpansion } from '@/composable/modelLifecycleUi'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import { checkModelDisk } from '@/api/settings'
import { formatProgress } from '@/utils/progress'
import lightLogo from '@/assets/images/亮色无底图标.png'
import darkLogo from '@/assets/images/暗色无底图标.png'
import lightTitle from '@/assets/images/亮色标题.png'
import darkTitle from '@/assets/images/暗色标题.png'
const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
defineProps<{ gitOpen: boolean; browserOpen: boolean; mobile?: boolean }>()

/* ---- 模型阻断模态框 ---- */
const modelModalVisible = ref(false)
const modelModalMessage = ref('')

async function checkEmbeddingBefore(action: () => void): Promise<void> {
  try {
    const status = await checkModelDisk()
    if (status.embedding === 'not_downloaded' || status.embedding === 'error') {
      modelModalMessage.value = 'Embedding 模型未就绪，请先下载'
      modelModalVisible.value = true
      return
    }
  } catch { /* 检查失败时允许继续 */ }
  action()
}

function closeModelModal() {
  modelModalVisible.value = false
}

function goToStorageSettings() {
  modelModalVisible.value = false
  window.location.hash = '#/settings'
  setTimeout(() => {
    window.dispatchEvent(new CustomEvent('agent-settings-tab', { detail: 'storage' }))
  }, 100)
}
const desktopApi = window.agentEditorDesktop
const emit = defineEmits<{
  toggleAgent: []
  openHome: []
  openSettings: []
  toggleTodo: []
  toggleGit: []
  toggleBrowser: []
}>()
const graphRebuilding = computed(() => workspaceStore.graphQueue.length > 0)
/** Compact live graph stage shown beside the aggregate header progress bar. */
const graphProgressLabel = computed(() => {
  const active = workspaceStore.graphQueue.find((item) => item.status === 'running' || item.status === 'cancelling')
  const stats = workspaceStore.graphProgressStats
  const stageCount = active?.stageTotal
    ? ` ${active.stageCurrent ?? 0}/${active.stageTotal}`
    : ''
  return `图谱 ${stats.current}/${stats.total} · ${active?.stageLabel ?? (workspaceStore.graphProgressDetail || '准备中')}${stageCount}`
})
/** Match graph progress density with the current ingestion file and stage. */
const ingestionProgressLabel = computed(() => {
  const stats = workspaceStore.ingestionProgressStats
  const completed = Math.min(stats.total, stats.succeeded + stats.failed)
  return `入库 ${completed}/${stats.total} · ${workspaceStore.ingestionProgressDetail}`
})
const agentActive = computed(() => workspaceStore.agentSidebarOpen)
const todoActive = computed(() => workspaceStore.todoSidebarOpen)
const logoSrc = computed(() => settingsStore.isDark ? darkLogo : lightLogo)
const titleSrc = computed(() => settingsStore.isDark ? darkTitle : lightTitle)

async function handleCloseWindow() {
  if (!(await workspaceStore.confirmSaveDirtyBeforeExit())) {
    return
  }
  desktopApi?.close()
}

</script>

<template>
  <header class="topbar" :class="{ mobile }">
    <div class="brand">
      <button class="logo-btn" type="button" title="回到首页" @click="emit('openHome')">
        <img :src="logoSrc" class="logo-img" alt="MetaWeave" />
      </button>
      <div class="brand-copy">
        <img :src="titleSrc" class="brand-title" alt="MetaWeave" />
      </div>
      <div
        v-if="workspaceStore.ingestionProgressVisible"
        class="ingestion-progress"
        :title="workspaceStore.ingestionProgressDetail"
        aria-live="polite"
      >
        <span class="ingestion-progress-label">{{ ingestionProgressLabel }}</span>
        <span class="ingestion-progress-track" aria-hidden="true">
          <span
            class="ingestion-progress-fill"
            :style="{ width: `${workspaceStore.ingestionProgress}%` }"
          />
        </span>
        <span class="ingestion-progress-percent">{{ formatProgress(workspaceStore.ingestionProgress) }}%</span>
      </div>
      <div
        v-if="workspaceStore.graphProgressVisible"
        class="ingestion-progress graph-progress"
        :title="workspaceStore.graphProgressDetail"
        aria-live="polite"
      >
        <span class="graph-progress-label">{{ graphProgressLabel }}</span>
        <span class="ingestion-progress-track" aria-hidden="true">
          <span
            class="ingestion-progress-fill"
            :style="{ width: `${workspaceStore.graphProgress}%` }"
          />
        </span>
        <span class="ingestion-progress-percent">{{ formatProgress(workspaceStore.graphProgress) }}%</span>
      </div>
    </div>

    <div class="actions">
      <div class="search-center">
        <SearchPalette />
      </div>
      <button
        v-if="modelLifecycleUi.hasNotices && modelLifecycleUi.compact"
        class="model-compact-loader"
        type="button"
        title="展开模型加载进度"
        aria-label="展开模型加载进度"
        @click="requestModelLifecycleExpansion"
      >
        <PixelLoader />
      </button>
      <button class="github-btn-topbar" :class="{ dark: settingsStore.isDark }" type="button" title="GitHub" onclick="window.open('https://github.com/xiao-Huahuo/MetaWeave.git','_blank')">
        <svg class="github-svg-icon" viewBox="0 0 496 512" height="1.2em" xmlns="http://www.w3.org/2000/svg"><path d="M165.9 397.4c0 2-2.3 3.6-5.2 3.6-3.3.3-5.6-1.3-5.6-3.6 0-2 2.3-3.6 5.2-3.6 3-.3 5.6 1.3 5.6 3.6zm-31.1-4.5c-.7 2 1.3 4.3 4.3 4.9 2.6 1 5.6 0 6.2-2s-1.3-4.3-4.3-5.2c-2.6-.7-5.5.3-6.2 2.3zm44.2-1.7c-2.9.7-4.9 2.6-4.6 4.9.3 2 2.9 3.3 5.9 2.6 2.9-.7 4.9-2.6 4.6-4.6-.3-1.9-3-3.2-5.9-2.9zM244.8 8C106.1 8 0 113.3 0 252c0 110.9 69.8 205.8 169.5 239.2 12.8 2.3 17.3-5.6 17.3-12.1 0-6.2-.3-40.4-.3-61.4 0 0-70 15-84.7-29.8 0 0-11.4-29.1-27.8-36.6 0 0-22.9-15.7 1.6-15.4 0 0 24.9 2 38.6 25.8 21.9 38.6 58.6 27.5 72.9 20.9 2.3-16 8.8-27.1 16-33.7-55.9-6.2-112.3-14.3-112.3-110.5 0-27.5 7.6-41.3 23.6-58.9-2.6-6.5-11.1-33.3 2.6-67.9 20.9-6.5 69 27 69 27 20-5.6 41.5-8.5 62.8-8.5s42.8 2.9 62.8 8.5c0 0 48.1-33.6 69-27 13.7 34.7 5.2 61.4 2.6 67.9 16 17.7 25.8 31.5 25.8 58.9 0 96.5-58.9 104.2-114.8 110.5 9.2 7.9 17 22.9 17 46.4 0 33.7-.3 75.4-.3 83.6 0 6.5 4.6 14.4 17.3 12.1C428.2 457.8 496 362.9 496 252 496 113.3 383.5 8 244.8 8zM97.2 352.9c-1.3 1-1 3.3.7 5.2 1.6 1.6 3.9 2.3 5.2 1 1.3-1 1-3.3-.7-5.2-1.6-1.6-3.9-2.3-5.2-1zm-10.8-8.1c-.7 1.3.3 2.9 2.3 3.9 1.6 1 3.6.7 4.3-.7.7-1.3-.3-2.9-2.3-3.9-2-.6-3.6-.3-4.3.7zm32.4 35.6c-1.6 1.3-1 4.3 1.3 6.2 2.3 2.3 5.2 2.6 6.5 1 1.3-1.3.7-4.3-1.3-6.2-2.2-2.3-5.2-2.6-6.5-1zm-11.4-14.7c-1.6 1-1.6 3.6 0 5.9 1.6 2.3 4.3 3.3 5.6 2.3 1.6-1.3 1.6-3.9 0-6.2-1.4-2.3-4-3.3-5.6-2z"></path></svg>
        <span class="github-text-topbar">GitHub</span>
      </button>
      <button class="agent-play-btn" :class="{ active: agentActive }" type="button" title="切换 Agent 面板" @click="emit('toggleAgent')">
        <img :src="logoSrc" class="agent-play-img" alt="MetaWeave" />
        <span class="agent-now">NOW!</span>
        <span class="agent-play">AGENT</span>
      </button>
      <button
        class="topbar-icon-button topbar-browser-btn"
        :class="{ active: browserOpen }"
        type="button"
        title="右侧浏览器"
        aria-label="打开或收起右侧浏览器"
        @click="emit('toggleBrowser')"
      >
        <IcIcon name="language" :size="17" />
      </button>
      <button
        class="topbar-icon-button topbar-git-btn"
        :class="{ active: gitOpen }"
        type="button"
        title="Git 版本控制"
        aria-label="切换右侧 Git 面板"
        @click="emit('toggleGit')"
      >
        <IcIcon name="git" :size="17" />
      </button>
      <button
        class="topbar-icon-button topbar-todo-btn topbar-optional"
        :class="{ active: todoActive }"
        type="button"
        title="待办"
        @click="emit('toggleTodo')"
      >
        <IcIcon name="todo" :size="17" />
      </button>
      <button
        class="topbar-icon-button topbar-optional"
        :class="{ refreshing: graphRebuilding }"
        type="button"
        :disabled="graphRebuilding"
        title="图谱抽取"
        @click="checkEmbeddingBefore(() => { workspaceStore.ingestionViewTab = 'graph-queue'; workspaceStore.mainView = 'ingestion'; workspaceStore.startGraphRebuild(); })"
      >
        <IcIcon name="hub" :size="17" />
      </button>
      <button
        class="topbar-icon-button topbar-optional"
        :class="{ refreshing: workspaceStore.refreshing }"
        type="button"
        :disabled="workspaceStore.refreshing"
        title="重新灌库"
        @click="checkEmbeddingBefore(() => { workspaceStore.ingestionViewTab = 'queue'; workspaceStore.mainView = 'ingestion'; workspaceStore.markIndexing(); })"
      >
        <IcIcon name="ingest" :size="17" />
      </button>
      <button
        v-if="desktopApi?.isDesktop"
        class="topbar-icon-button floating-window-btn"
        type="button"
        title="Agent 悬浮窗"
        aria-label="打开或收起 Agent 悬浮窗"
        @click="desktopApi.floatingToggle()"
      >
        <IcIcon name="open-in-new" :size="14" />
      </button>
      <div v-if="desktopApi?.isDesktop" class="window-controls" aria-label="Window controls">
        <button type="button" title="最小化" @click="desktopApi.minimize">
          <IcIcon name="remove" :size="13" />
        </button>
        <button type="button" title="最大化" @click="desktopApi.toggleMaximize">
          <IcIcon name="open-in-full" :size="13" />
        </button>
        <button class="close-window" type="button" title="关闭" @click="handleCloseWindow">
          <IcIcon name="close" :size="13" />
        </button>
      </div>
    </div>
  </header>
  <!-- 模型阻断模态框 -->
  <Teleport to="body">
    <div v-if="modelModalVisible" class="model-modal-overlay" @click.self="closeModelModal">
      <div class="model-modal">
        <p class="model-modal-message">{{ modelModalMessage }}</p>
        <p class="model-modal-link">
          <a href="#" @click.prevent="goToStorageSettings">前往存储管理页面下载</a>
        </p>
        <div class="model-modal-actions">
          <button class="model-modal-btn close-btn" @click="closeModelModal">关闭</button>
        </div>
      </div>
    </div>
  </Teleport>

  <Transition name="toast-slide">
    <div v-if="workspaceStore.toastVisible" class="toast-banner">
      {{ workspaceStore.toastMessage }}
    </div>
  </Transition>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-8);
  min-height: 64px;
  padding: 0 var(--space-10);
  background: var(--color-chrome-rail-bg);
  -webkit-app-region: drag;
  user-select: none;
  position: relative;
  z-index: 50;
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  flex: 0 1 auto;
  min-width: 0;
  max-width: min(360px, 34vw);
  overflow: hidden;
  z-index: 1;
  padding-left: var(--space-4);
}

.brand-copy {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  -webkit-app-region: no-drag;
}

.logo-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 64px;
  height: 64px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
  -webkit-app-region: no-drag;
}

.logo-btn:hover {
  background: transparent;
}

.logo-img {
  display: block;
  width: 58px;
  height: 58px;
  object-fit: contain;
  opacity: 1;
}

.brand-title {
  display: block;
  width: min(160px, 100%);
  height: auto;
  max-height: 44px;
  object-fit: contain;
  object-position: left center;
}

.search-center {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex: 0 0 28px;
  width: 28px;
  min-width: 28px;
  max-width: 250px;
  order: 90;
  -webkit-app-region: no-drag;
  transition:
    flex-basis 200ms ease-in-out,
    width 200ms ease-in-out;
}

.search-center:has(.search-wrapper.focused) {
  flex-basis: 250px;
  width: 250px;
}

.brand strong {
  display: block;
  overflow: hidden;
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
  font-weight: 650;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  -webkit-app-region: no-drag;
  z-index: 1;
}

.topbar-icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--color-text-secondary);
  -webkit-app-region: no-drag;
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.topbar-icon-button:hover,
.topbar-icon-button.active {
  background: var(--color-primary-softer);
  color: var(--color-primary);
}

.topbar-icon-button:disabled {
  cursor: default;
  opacity: 0.35;
}

.topbar-icon-button.refreshing :deep(svg) {
  animation: refresh-spin 900ms linear infinite;
}

.floating-window-btn {
  display: none;
}

.github-btn-topbar {
  border: 1px solid var(--color-border);
  border-radius: 50%;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition-duration: .4s;
  cursor: pointer;
  position: relative;
  background-color: #fff;
  overflow: hidden;
  flex-shrink: 0;
  margin-inline: 4px;
  z-index: 1;
}

.model-compact-loader {
  display: inline-grid;
  place-items: center;
  width: 36px;
  height: 24px;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  flex: 0 0 auto;
  margin-right: var(--space-8);
  -webkit-app-region: no-drag;
}

.github-btn-topbar.dark {
  background-color: rgb(31, 31, 31);
  border-color: var(--color-border);
}

.github-btn-topbar.dark .github-svg-icon path {
  fill: #fff;
}

.github-btn-topbar.dark .github-text-topbar {
  color: #fff;
}

.github-svg-icon {
  transition-duration: .3s;
}

.github-svg-icon path {
  fill: #000;
}

.github-text-topbar {
  position: absolute;
  color: #000;
  width: 120px;
  font-weight: 600;
  opacity: 0;
  transition-duration: .4s;
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
}

.github-btn-topbar:hover {
  width: 90px;
  transition-duration: .4s;
  border-radius: 30px;
  box-shadow: 0 0 0 2px var(--color-border), 0 0 0 4px var(--color-border);
  z-index: 3;
}

.github-btn-topbar:hover .github-text-topbar {
  opacity: 1;
  transition-duration: .4s;
}

.github-btn-topbar:hover .github-svg-icon {
  opacity: 0;
  transition-duration: .3s;
}

.agent-play-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 24px;
  padding: 0 10px;
  border: 0;
  border-radius: 999px;
  background-color: var(--color-primary);
  color: #fff;
  text-transform: uppercase;
  letter-spacing: 1px;
  font-weight: 600;
  font-family: var(--font-ui);
  font-size: calc(10px * var(--font-scale));
  cursor: pointer;
  position: relative;
  overflow: hidden;
  transition: all 0.5s ease;
}

.agent-play-btn:active {
  transform: scale(0.9);
  transition: all 100ms ease;
}

.agent-play-img {
  width: 14px;
  height: 14px;
  object-fit: contain;
  transition: all 0.5s ease;
  z-index: 2;
  filter: brightness(0) invert(1);
}

.agent-play {
  transition: all 0.5s ease;
  transition-delay: 300ms;
}

.agent-play-btn:hover .agent-play-img {
  transform: scale(2.5) translateX(14px);
  transform-origin: left center;
}

.agent-now {
  position: absolute;
  left: 0;
  transform: translateX(-100%);
  transition: all 0.5s ease;
  z-index: 2;
}

.agent-play-btn:hover .agent-now {
  transform: translateX(6px);
  transition-delay: 300ms;
}

.agent-play-btn:hover .agent-play {
  transform: translateX(200%);
  transition-delay: 300ms;
}

.agent-play-btn.active {
  background-color: color-mix(in srgb, var(--color-primary) 80%, #000);
}

.ingestion-progress {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  width: min(300px, 36vw);
  height: 16px;
  padding: 0 var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-canvas) 92%, var(--color-primary) 8%);
  color: var(--color-primary);
  font-family: var(--font-ui);
  font-size: calc(9px * var(--font-scale));
  font-weight: 700;
  line-height: 1;
  -webkit-app-region: no-drag;
}

.ingestion-progress-track {
  display: block;
  flex: 1 1 auto;
  height: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 14%, transparent);
}

.ingestion-progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary);
  transition: width 140ms ease;
}

.ingestion-progress-percent {
  flex: 0 0 auto;
  white-space: nowrap;
}

.graph-progress {
  width: min(300px, 36vw);
  border-color: color-mix(in srgb, var(--color-primary) 50%, #14b8a6 50%);
  background: color-mix(in srgb, var(--color-canvas) 92%, #14b8a6 8%);
  color: #14b8a6;
}

.ingestion-progress-label,
.graph-progress-label {
  max-width: 164px;
  overflow: hidden;
  color: inherit;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.brand:has(.ingestion-progress) {
  max-width: min(680px, 62vw);
}

.graph-progress .ingestion-progress-track {
  background: color-mix(in srgb, #14b8a6 14%, transparent);
}

.graph-progress .ingestion-progress-fill {
  background: #14b8a6;
}

@keyframes refresh-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.toast-banner {
  position: fixed;
  top: 72px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 999;
  padding: var(--space-8) var(--space-20);
  border: 0;
  border-radius: var(--radius-lg);
  background: #fff;
  color: #333;
  font-size: calc(13px * var(--font-scale));
  font-weight: 600;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.15);
  pointer-events: none;
}

.toast-slide-enter-active {
  transition: all 280ms cubic-bezier(0.16, 1, 0.3, 1);
}

.toast-slide-leave-active {
  transition: all 220ms ease-in;
}

.toast-slide-enter-from {
  opacity: 0;
  transform: translateX(-50%) translateY(-12px);
}

.toast-slide-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-8px);
}

kbd {
  padding: 0 4px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(10px * var(--font-scale));
}

.window-controls {
  display: inline-flex;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  order: 110;
}

.window-controls button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 24px;
  border: 0;
  border-left: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-secondary);
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.window-controls button:first-child {
  border-left: 0;
}

.window-controls button:hover {
  background: var(--color-surface-raised);
  color: var(--color-text);
}

.window-controls .close-window:hover {
  background: var(--color-accent);
  color: white;
}

@media (max-width: 1040px) {
  .github-btn-topbar {
    display: none;
  }
}

@media (max-width: 920px) {
  .agent-play-btn {
    width: 24px;
    padding: 0;
    gap: 0;
  }

  .agent-play,
  .agent-now {
    display: none;
  }

  .agent-play-btn:hover .agent-play-img {
    transform: none;
  }
}

@media (max-width: 820px) {
  .topbar {
    gap: var(--space-6);
  }

  .brand {
    max-width: min(240px, 42vw);
  }

  .topbar-optional {
    display: none;
  }
}

@media (max-width: 760px) {
  .topbar {
    align-items: center;
    padding: 0 var(--space-10);
  }

  .actions {
    flex-shrink: 0;
  }

  .brand {
    flex: 0 1 auto;
    max-width: min(220px, 48vw);
  }

  .brand-copy {
    display: none;
  }

  .search-center:has(.search-wrapper.focused) {
    flex: 0 1 250px;
    min-width: 160px;
  }
}

.topbar.mobile {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) auto;
  justify-content: stretch;
  padding: 0 var(--space-10);
}

.topbar.mobile .actions > * {
  display: none;
}

.topbar.mobile .brand {
  display: flex;
  width: 100%;
  max-width: none;
  overflow: hidden;
}

.topbar.mobile .brand-copy {
  display: none;
}

.topbar.mobile .actions {
  flex: 0 0 auto;
  justify-content: flex-end;
  overflow: visible;
}

.topbar.mobile .agent-play-btn,
.topbar.mobile .model-compact-loader,
.topbar.mobile .topbar-browser-btn,
.topbar.mobile .topbar-git-btn,
.topbar.mobile .topbar-todo-btn,
.topbar.mobile .search-center,
.topbar.mobile .window-controls {
  display: inline-flex;
}

.topbar.mobile .agent-play-btn {
  order: 1;
  width: 28px;
  padding: 0;
  gap: 0;
}

.topbar.mobile .agent-play,
.topbar.mobile .agent-now {
  display: none;
}

.topbar.mobile .agent-play-btn:hover .agent-play-img {
  transform: none;
}

.topbar.mobile .topbar-browser-btn {
  order: 2;
}

.topbar.mobile .topbar-git-btn {
  order: 3;
}

.topbar.mobile .topbar-todo-btn {
  order: 4;
}

.topbar.mobile .search-center {
  order: 5;
}

.topbar.mobile .window-controls {
  order: 6;
}

/* ---- 模型阻断模态框 ---- */
:global(.model-modal-overlay) {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
}

:global(.model-modal) {
  width: 380px;
  max-width: 90vw;
  padding: 24px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.35);
}

:global(.model-modal-message) {
  margin: 0 0 12px;
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
  line-height: 1.5;
}

:global(.model-modal-link) {
  margin: 0 0 16px;
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
}

:global(.model-modal-link a) {
  color: var(--color-primary);
  text-decoration: underline;
  cursor: pointer;
}

:global(.model-modal-link a:hover) {
  color: var(--color-primary-active);
}

:global(.model-modal-actions) {
  display: flex;
  gap: var(--space-8);
  justify-content: flex-end;
}

:global(.model-modal-btn) {
  padding: 6px 18px;
  border: 0;
  border-radius: var(--radius-sm);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  transition: opacity var(--transition-fast);
}

:global(.close-btn) {
  background: var(--color-border);
  color: var(--color-text);
}

:global(.close-btn:hover) {
  opacity: 0.8;
}
</style>
