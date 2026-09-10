<!--
  Editor activity bar.

  Usage:
  Renders the icon-only left rail for opening editor side panels and navigating
  to future workspace tools. Buttons expose native tooltips through title text.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import ThemeToggleButton from '@/components/common/ThemeToggleButton.vue'
import lightLogo from '@/assets/images/亮色无底图标.png'
import darkLogo from '@/assets/images/暗色无底图标.png'
import type { SidebarDisplayMode } from '@/types/settings'

const props = defineProps<{
  displayMode: SidebarDisplayMode
  homeActive: boolean
  fileOpen: boolean
  gitActive: boolean
  agentOpen: boolean
  resourcesActive: boolean
  favoritesActive: boolean
  privacyActive: boolean
  libraryActive: boolean
  componentLibraryActive: boolean
  vaultActive: boolean
  formsActive: boolean
  literatureActive: boolean
  ingestionActive: boolean
  scannerActive?: boolean
  batchScannerActive?: boolean
  visualizationActive: boolean
  agentActive: boolean
  agentQueueActive: boolean
  graphActive: boolean
  dashboardActive: boolean
  debugActive: boolean
  feedbackOpen: boolean
  searchActive: boolean
  browserActive: boolean
  settingsActive: boolean
  isDark: boolean
}>()

const emit = defineEmits<{
  openHome: []
  toggleFile: []
  toggleGit: []
  openResources: []
  openFavorites: []
  openPrivacy: []
  openLibrary: []
  openComponentLibrary: []
  openVault: []
  openForms: []
  openLiterature: []
  openIngestion: []
  openScanner: []
  openBatchScanner: []
  openVisualization: []
  toggleAgent: []
  openAgentQueue: []
  toggleGraph: []
  openDashboard: []
  toggleFeedback: []
  openDebug: []
  openSearch: []
  openBrowser: []
  knowledgeMenuVisibilityChange: [open: boolean]
  openSettings: []
  toggleTheme: []
}>()

function handleRipple(e: MouseEvent) {
  const el = e.currentTarget as HTMLElement
  el.querySelectorAll('.ripple-effect').forEach((item) => item.remove())
  const ripple = document.createElement('span')
  ripple.className = 'ripple-effect'
  el.appendChild(ripple)
  ripple.addEventListener('animationend', () => ripple.remove(), { once: true })
  window.setTimeout(() => ripple.remove(), 450)
}

const agentIconSrc = computed(() => {
  if (props.agentActive && props.displayMode === 'management') return lightLogo
  return darkLogo
})
type ActivityMenu = 'knowledge' | 'scanner' | 'entertainment' | 'mine'

/** Only one rail submenu stays open so every grouped entry shares the library interaction model. */
const activeMenu = ref<ActivityMenu | null>(null)
const knowledgeActive = computed(() => (
  props.resourcesActive
  || props.libraryActive
  || props.componentLibraryActive
  || props.vaultActive
  || props.formsActive
  || props.literatureActive
))
const entertainmentActive = computed(() => props.visualizationActive || props.agentQueueActive)
const scannerGroupActive = computed(() => props.scannerActive || props.batchScannerActive)
const mineActive = computed(() => props.favoritesActive || props.privacyActive || props.feedbackOpen)
const activityBarRef = ref<HTMLElement | null>(null)
const hoverIndicatorTop = ref(0)
const hoverIndicatorVisible = ref(false)
const knowledgeSubmenuRef = ref<HTMLElement | null>(null)
const knowledgeHoverIndicatorTop = ref(0)
const knowledgeHoverIndicatorVisible = ref(false)

/** Let native workspace surfaces yield while any DOM submenu is visible. */
watch(activeMenu, (menu) => {
  knowledgeHoverIndicatorVisible.value = false
  emit('knowledgeMenuVisibilityChange', menu !== null)
})

/** Resolves a rail button from delegated hover/focus events. */
function resolveActivityButton(target: EventTarget | null): HTMLElement | null {
  const activityBar = activityBarRef.value
  if (!activityBar || !(target instanceof Element)) return null
  const button = target.closest<HTMLElement>('.activity-button')
  if (!button || !activityBar.contains(button)) return null
  const submenu = button.closest('.knowledge-submenu')
  return submenu
    ? submenu.closest('.knowledge-group')?.querySelector<HTMLElement>('.knowledge-button') ?? null
    : button
}

/** Places the shared hover indicator behind a navigation button. */
function positionHoverIndicator(button: HTMLElement): void {
  const activityBar = activityBarRef.value
  if (!activityBar) return
  hoverIndicatorTop.value = button.getBoundingClientRect().top - activityBar.getBoundingClientRect().top
  hoverIndicatorVisible.value = true
}

/** Moves the shared indicator through delegated pointer and focus events. */
function moveHoverIndicator(event: MouseEvent | FocusEvent): void {
  const button = resolveActivityButton(event.target)
  if (button) positionHoverIndicator(button)
}

/** Hides the indicator unless keyboard focus remains within the activity bar. */
function hideHoverIndicator(event: MouseEvent | FocusEvent): void {
  const nextTarget = event instanceof FocusEvent ? event.relatedTarget : document.activeElement
  const focusedButton = resolveActivityButton(nextTarget)
  if (focusedButton) {
    positionHoverIndicator(focusedButton)
    return
  }
  hoverIndicatorVisible.value = false
}

/** Moves the submenu indicator behind the currently pointed knowledge entry. */
function moveKnowledgeHoverIndicator(event: MouseEvent | FocusEvent): void {
  const submenu = knowledgeSubmenuRef.value
  if (!submenu || !(event.target instanceof Element)) return
  const button = event.target.closest<HTMLElement>('.activity-button')
  if (!button || !submenu.contains(button)) return
  knowledgeHoverIndicatorTop.value = button.getBoundingClientRect().top - submenu.getBoundingClientRect().top
  knowledgeHoverIndicatorVisible.value = true
}

/** Hides the submenu indicator after pointer and keyboard focus leave the submenu. */
function hideKnowledgeHoverIndicator(event: MouseEvent | FocusEvent): void {
  const submenu = knowledgeSubmenuRef.value
  const nextTarget = event instanceof FocusEvent ? event.relatedTarget : document.activeElement
  if (submenu && nextTarget instanceof Node && submenu.contains(nextTarget)) return
  knowledgeHoverIndicatorVisible.value = false
}

/** Toggles one library-style grouped menu and closes any sibling menu. */
function toggleActivityMenu(menu: ActivityMenu) {
  activeMenu.value = activeMenu.value === menu ? null : menu
}

/** Closes a compact submenu after navigation while expanded management menus stay visible. */
function closeActivityMenu() {
  if (props.displayMode === 'management') return
  activeMenu.value = null
}

/** Close the expanded branch whenever pointer interaction leaves its trigger and submenu. */
function closeActivityMenuOnOutsidePointer(event: Event): void {
  const activityBar = activityBarRef.value
  if (!activeMenu.value || !activityBar || !(event.target instanceof Node)) return
  const activeTrigger = activityBar.querySelector<HTMLElement>('.knowledge-button[aria-expanded="true"]')
  const activeGroup = activeTrigger?.closest<HTMLElement>('.knowledge-group')
  if (!activeGroup?.contains(event.target)) activeMenu.value = null
}

onMounted(() => document.addEventListener('pointerdown', closeActivityMenuOnOutsidePointer))
onBeforeUnmount(() => document.removeEventListener('pointerdown', closeActivityMenuOnOutsidePointer))
</script>

<template>
  <nav
    ref="activityBarRef"
    class="activity-bar"
    :class="{ management: displayMode === 'management' }"
    aria-label="Editor activity bar"
    @mouseover="moveHoverIndicator"
    @mouseleave="hideHoverIndicator"
    @focusin="moveHoverIndicator"
    @focusout="hideHoverIndicator"
  >
    <span
      class="activity-hover-indicator"
      aria-hidden="true"
      :style="{
        transform: `translate3d(0, ${hoverIndicatorTop}px, 0)`,
        opacity: hoverIndicatorVisible ? 1 : 0,
      }"
    ></span>
    <ThemeToggleButton :dark="isDark" @toggle="emit('toggleTheme')" />
    <button
      class="activity-button"
      :class="{ active: homeActive }"
      type="button"
      title="主页"
      aria-label="主页"
      @mousedown.prevent="handleRipple"
      @click="emit('openHome')"
    >
      <IcIcon name="home" :size="18" />
      <span class="activity-label">主页</span>
    </button>
    <button
      class="activity-button"
      :class="{ active: fileOpen }"
      type="button"
      title="Files"
      aria-label="Files"
      @mousedown.prevent="handleRipple"
      @click="emit('toggleFile')"
    >
      <IcIcon name="folder" :size="18" />
      <span class="activity-label">文件</span>
    </button>
    <div class="knowledge-group">
      <button
        class="activity-button knowledge-button"
        :class="{ active: knowledgeActive }"
        type="button"
      title="库"
      aria-label="库"
        :aria-expanded="activeMenu === 'knowledge'"
        @mousedown="handleRipple"
        @click.stop="toggleActivityMenu('knowledge')"
      >
        <IcIcon name="book" :size="18" />
        <span class="activity-label">库</span>
        <IcIcon class="knowledge-chevron" :class="{ 'is-open': activeMenu === 'knowledge' }" name="chevron-right" :size="14" />
      </button>
      <Transition name="knowledge-submenu">
        <div
          v-if="activeMenu === 'knowledge'"
          ref="knowledgeSubmenuRef"
          class="knowledge-submenu"
          aria-label="知识库菜单"
          @mouseover="moveKnowledgeHoverIndicator"
          @mouseleave="hideKnowledgeHoverIndicator"
          @focusin="moveKnowledgeHoverIndicator"
          @focusout="hideKnowledgeHoverIndicator"
        >
          <span
            class="knowledge-hover-indicator"
            aria-hidden="true"
            :style="{
              transform: `translate3d(0, ${knowledgeHoverIndicatorTop}px, 0)`,
              opacity: knowledgeHoverIndicatorVisible ? 1 : 0,
            }"
          ></span>
          <button
            class="activity-button"
            :class="{ active: resourcesActive }"
            type="button"
            title="文件资源管理器"
            aria-label="文件资源管理器"
            @mousedown.prevent="handleRipple"
            @click="emit('openResources'); closeActivityMenu()"
          >
            <IcIcon class="library-entry-icon library-color-files" name="folder-open" :size="18" />
            <span class="activity-label">文件资源管理器</span>
          </button>
          <button
            class="activity-button"
            :class="{ active: libraryActive }"
            type="button"
            title="图书馆"
            aria-label="图书馆"
            @mousedown.prevent="handleRipple"
            @click="emit('openLibrary'); closeActivityMenu()"
          >
            <IcIcon class="library-entry-icon library-color-library" name="book" :size="18" />
            <span class="activity-label">图书馆</span>
          </button>
          <button
            class="activity-button"
            :class="{ active: componentLibraryActive }"
            type="button"
            title="组件库"
            aria-label="组件库"
            @mousedown.prevent="handleRipple"
            @click="emit('openComponentLibrary'); closeActivityMenu()"
          >
            <IcIcon class="library-entry-icon library-color-components" name="grid-view" :size="18" />
            <span class="activity-label">组件库</span>
          </button>
          <button
            class="activity-button"
            :class="{ active: vaultActive }"
            type="button"
            title="密码库"
            aria-label="密码库"
            @mousedown.prevent="handleRipple"
            @click="emit('openVault'); closeActivityMenu()"
          >
            <IcIcon class="library-entry-icon library-color-vault" name="shield" :size="18" />
            <span class="activity-label">密码库</span>
          </button>
          <button
            class="activity-button"
            :class="{ active: formsActive }"
            type="button"
            title="智能表格"
            aria-label="智能表格"
            @mousedown.prevent="handleRipple"
            @click="emit('openForms'); closeActivityMenu()"
          >
            <IcIcon class="library-entry-icon library-color-forms" name="table-chart" :size="18" />
            <span class="activity-label">智能表格</span>
          </button>
          <button
            class="activity-button"
            :class="{ active: literatureActive }"
            type="button"
            title="文献阅读"
            aria-label="文献阅读"
            @mousedown.prevent="handleRipple"
            @click="emit('openLiterature'); closeActivityMenu()"
          >
            <IcIcon class="library-entry-icon library-color-literature" name="document" :size="18" />
            <span class="activity-label">文献阅读</span>
          </button>
        </div>
      </Transition>
    </div>
    <button
      class="activity-button"
      :class="{ active: agentActive }"
      type="button"
      title="Agent"
      aria-label="Agent"
      @mousedown.prevent="handleRipple"
      @click="emit('toggleAgent')"
    >
      <img :src="agentIconSrc" class="activity-agent-icon" alt="" />
      <span class="activity-label">Agent</span>
    </button>
    <div class="knowledge-group">
      <button
        class="activity-button knowledge-button"
        :class="{ active: scannerGroupActive }"
        type="button"
        title="扫描"
        aria-label="扫描"
        :aria-expanded="activeMenu === 'scanner'"
        @mousedown="handleRipple"
        @click.stop="toggleActivityMenu('scanner')"
      >
        <IcIcon name="center-focus" :size="18" />
        <span class="activity-label">扫描</span>
        <IcIcon class="knowledge-chevron" :class="{ 'is-open': activeMenu === 'scanner' }" name="chevron-right" :size="14" />
      </button>
      <Transition name="knowledge-submenu">
        <div
          v-if="activeMenu === 'scanner'"
          ref="knowledgeSubmenuRef"
          class="knowledge-submenu"
          aria-label="扫描菜单"
          @mouseover="moveKnowledgeHoverIndicator"
          @mouseleave="hideKnowledgeHoverIndicator"
          @focusin="moveKnowledgeHoverIndicator"
          @focusout="hideKnowledgeHoverIndicator"
        >
          <span
            class="knowledge-hover-indicator"
            aria-hidden="true"
            :style="{
              transform: `translate3d(0, ${knowledgeHoverIndicatorTop}px, 0)`,
              opacity: knowledgeHoverIndicatorVisible ? 1 : 0,
            }"
          ></span>
          <button
            class="activity-button"
            :class="{ active: scannerActive }"
            type="button"
            title="扫描器"
            aria-label="扫描器"
            @mousedown.prevent="handleRipple"
            @click="emit('openScanner'); closeActivityMenu()"
          >
            <IcIcon name="center-focus" :size="18" />
            <span class="activity-label">扫描器</span>
          </button>
          <button
            class="activity-button"
            :class="{ active: batchScannerActive }"
            type="button"
            title="扫描队列"
            aria-label="扫描队列"
            @mousedown.prevent="handleRipple"
            @click="emit('openBatchScanner'); closeActivityMenu()"
          >
            <IcIcon name="checklist" :size="18" />
            <span class="activity-label">扫描队列</span>
          </button>
        </div>
      </Transition>
    </div>
    <button
      class="activity-button"
      :class="{ active: searchActive }"
      type="button"
      title="Search"
      aria-label="Search"
      @mousedown.prevent="handleRipple"
      @click="emit('openSearch')"
    >
      <IcIcon name="search" :size="18" />
      <span class="activity-label">搜索</span>
    </button>
    <button
      class="activity-button"
      :class="{ active: browserActive }"
      type="button"
      title="浏览器"
      aria-label="浏览器"
      @mousedown.prevent="handleRipple"
      @click="emit('openBrowser')"
    >
      <IcIcon name="language" :size="18" />
      <span class="activity-label">浏览器</span>
    </button>
    <button
      class="activity-button"
      :class="{ active: graphActive }"
      type="button"
      title="Knowledge graph"
      aria-label="Knowledge graph"
      @mousedown.prevent="handleRipple"
      @click="emit('toggleGraph')"
    >
      <IcIcon name="hub" :size="18" />
      <span class="activity-label">图谱</span>
    </button>
    <button
      class="activity-button"
      :class="{ active: dashboardActive }"
      type="button"
      title="Dashboard"
      aria-label="Dashboard"
      @mousedown.prevent="handleRipple"
      @click="emit('openDashboard')"
    >
      <IcIcon name="dashboard" :size="18" />
      <span class="activity-label">看板</span>
    </button>
    <div class="knowledge-group">
      <button
        class="activity-button knowledge-button"
        :class="{ active: entertainmentActive }"
        type="button"
        title="娱乐功能"
        aria-label="娱乐功能"
        :aria-expanded="activeMenu === 'entertainment'"
        @mousedown="handleRipple"
        @click.stop="toggleActivityMenu('entertainment')"
      >
        <IcIcon name="auto-awesome" :size="18" />
        <span class="activity-label">娱乐功能</span>
        <IcIcon class="knowledge-chevron" :class="{ 'is-open': activeMenu === 'entertainment' }" name="chevron-right" :size="14" />
      </button>
      <Transition name="knowledge-submenu">
        <div
          v-if="activeMenu === 'entertainment'"
          ref="knowledgeSubmenuRef"
          class="knowledge-submenu"
          aria-label="娱乐功能菜单"
          @mouseover="moveKnowledgeHoverIndicator"
          @mouseleave="hideKnowledgeHoverIndicator"
          @focusin="moveKnowledgeHoverIndicator"
          @focusout="hideKnowledgeHoverIndicator"
        >
          <span
            class="knowledge-hover-indicator"
            aria-hidden="true"
            :style="{
              transform: `translate3d(0, ${knowledgeHoverIndicatorTop}px, 0)`,
              opacity: knowledgeHoverIndicatorVisible ? 1 : 0,
            }"
          ></span>
          <button
            class="activity-button"
            :class="{ active: agentQueueActive }"
            type="button"
            title="任务队列"
            aria-label="任务队列"
            @mousedown.prevent="handleRipple"
            @click="emit('openAgentQueue'); closeActivityMenu()"
          >
            <IcIcon name="checklist" :size="18" />
            <span class="activity-label">任务队列</span>
          </button>
          <button
            class="activity-button"
            :class="{ active: visualizationActive }"
            type="button"
            title="MD-HTML"
            aria-label="MD-HTML"
            @mousedown.prevent="handleRipple"
            @click="emit('openVisualization'); closeActivityMenu()"
          >
            <IcIcon name="code" :size="18" />
            <span class="activity-label">MD-HTML</span>
          </button>
        </div>
      </Transition>
    </div>
    <div class="bottom-group">
      <button
        class="activity-button"
        :class="{ active: ingestionActive }"
        type="button"
        title="入库进度"
        aria-label="入库进度"
        @mousedown.prevent="handleRipple"
        @click="emit('openIngestion')"
      >
        <IcIcon name="ingest" :size="18" />
        <span class="activity-label">入库</span>
      </button>
      <button
        class="activity-button"
        :class="{ active: debugActive }"
        type="button"
        title="Debug"
        aria-label="Debug"
        @mousedown.prevent="handleRipple"
      @click="emit('openDebug')"
      >
        <IcIcon name="bug" :size="18" />
        <span class="activity-label">Debug</span>
      </button>
      <div class="knowledge-group">
        <button
          class="activity-button knowledge-button"
          :class="{ active: mineActive }"
          type="button"
          title="我的"
          aria-label="我的"
          :aria-expanded="activeMenu === 'mine'"
          @mousedown="handleRipple"
          @click.stop="toggleActivityMenu('mine')"
        >
          <IcIcon name="group" :size="18" />
          <span class="activity-label">我的</span>
          <IcIcon class="knowledge-chevron" :class="{ 'is-open': activeMenu === 'mine' }" name="chevron-right" :size="14" />
        </button>
        <Transition name="knowledge-submenu">
          <div
            v-if="activeMenu === 'mine'"
            ref="knowledgeSubmenuRef"
            class="knowledge-submenu"
            aria-label="我的菜单"
            @mouseover="moveKnowledgeHoverIndicator"
            @mouseleave="hideKnowledgeHoverIndicator"
            @focusin="moveKnowledgeHoverIndicator"
            @focusout="hideKnowledgeHoverIndicator"
          >
            <span
              class="knowledge-hover-indicator"
              aria-hidden="true"
              :style="{
                transform: `translate3d(0, ${knowledgeHoverIndicatorTop}px, 0)`,
                opacity: knowledgeHoverIndicatorVisible ? 1 : 0,
              }"
            ></span>
            <button
              class="activity-button"
              :class="{ active: favoritesActive }"
              type="button"
              title="我的收藏"
              aria-label="我的收藏"
              @mousedown.prevent="handleRipple"
              @click="emit('openFavorites'); closeActivityMenu()"
            >
              <IcIcon name="star" :size="18" />
              <span class="activity-label">我的收藏</span>
            </button>
            <button
              class="activity-button"
              :class="{ active: privacyActive }"
              type="button"
              title="我的隐私"
              aria-label="我的隐私"
              @mousedown.prevent="handleRipple"
              @click="emit('openPrivacy'); closeActivityMenu()"
            >
              <IcIcon name="visibility-off" :size="18" />
              <span class="activity-label">我的隐私</span>
            </button>
            <button
              class="activity-button"
              :class="{ active: feedbackOpen }"
              type="button"
              title="用户反馈"
              aria-label="用户反馈"
              @mousedown.prevent="handleRipple"
              @click="emit('toggleFeedback'); closeActivityMenu()"
            >
              <IcIcon name="feedback" :size="18" />
              <span class="activity-label">用户反馈</span>
            </button>
          </div>
        </Transition>
      </div>
      <button
        class="activity-button"
        :class="{ active: settingsActive }"
        type="button"
        title="Settings"
        aria-label="Settings"
        @mousedown.prevent="handleRipple"
      @click="emit('openSettings')"
      >
        <IcIcon name="settings" :size="18" />
        <span class="activity-label">设置</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.activity-bar {
  position: relative;
  z-index: 100;
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: var(--space-4);
  width: 100%;
  height: 100%;
  padding: var(--space-8) var(--space-4);
  border: 1px solid var(--color-activity-bar-border);
  background: var(--color-activity-bar-bg);
  box-shadow: 0 0 0 4px var(--color-activity-bar-ring);
  overflow: visible;
  transition: padding 180ms ease;
}

.activity-bar:not(.management) {
  width: calc(100% - 16px);
  height: calc(100% - 24px);
  margin: 12px 4px 12px 12px;
  padding: var(--space-8) 3px;
  border-radius: 20px;
}

.activity-bar.management {
  left: -4px;
  align-items: stretch;
  height: calc(100% - 24px);
  margin: 12px 0;
  padding: var(--space-8) var(--space-6);
  border-radius: 0 28px 28px 0;
}

.activity-hover-indicator {
  position: absolute;
  top: 0;
  left: 50%;
  z-index: 0;
  display: none;
  width: 36px;
  height: 36px;
  margin-left: -18px;
  border-radius: 50%;
  background: var(--color-activity-bar-hover);
  pointer-events: none;
  transition:
    transform 220ms cubic-bezier(0.23, 1, 0.32, 1),
    opacity 150ms ease;
  will-change: transform;
}

.activity-bar.management .activity-hover-indicator {
  right: var(--space-6);
  left: var(--space-6);
  width: auto;
  height: 32px;
  margin-left: 0;
  border-radius: var(--radius-sm);
}

@media (hover: hover) and (pointer: fine) {
  .activity-hover-indicator {
    display: block;
  }
}

@media (prefers-reduced-motion: reduce) {
  .activity-hover-indicator {
    transition: opacity 150ms ease;
  }
}

.activity-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  width: 36px;
  height: 36px;
  border: 1px solid transparent;
  border-radius: 50%;
  background: transparent;
  color: var(--color-activity-bar-muted);
  position: relative;
  overflow: hidden;
  transition:
    width 180ms ease,
    gap 180ms ease,
    padding 180ms ease,
    background 0.25s,
    border-color 0.25s,
    color 0.25s;
}

.activity-button:hover,
.activity-button:focus-visible {
  color: var(--color-activity-bar-text);
}

.activity-bar.management .activity-button {
  justify-content: center;
  width: 100%;
  height: 32px;
  padding: 0 32px;
  gap: 0;
  border-radius: var(--radius-sm);
}

.activity-bar.management .activity-button > :deep(.ic-icon:not(.knowledge-chevron)),
.activity-bar.management .activity-button > .activity-agent-icon {
  position: absolute;
  top: 50%;
  left: var(--space-8);
  transform: translateY(-50%);
}

.knowledge-group {
  position: relative;
  z-index: 101;
}

.activity-bar.management .knowledge-group {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  gap: var(--space-4);
}

.knowledge-button .knowledge-chevron {
  position: absolute;
  top: 50%;
  right: var(--space-8);
  display: none;
  width: 14px;
  height: 14px;
  margin-left: auto;
  transform: translateY(-50%);
  transition: transform 180ms ease;
}

.activity-bar.management .knowledge-button .knowledge-chevron {
  display: block;
}

.knowledge-button .knowledge-chevron.is-open {
  transform: translateY(-50%) rotate(90deg);
}

.knowledge-submenu {
  position: absolute;
  top: 50%;
  left: calc(100% + var(--space-8));
  z-index: 1000;
  display: grid;
  gap: var(--space-4);
  min-width: 48px;
  width: 48px;
  padding: var(--space-8) 3px;
  border: 1px solid var(--color-activity-bar-border);
  border-radius: 20px;
  background: var(--color-activity-bar-bg);
  box-shadow: 0 0 0 4px var(--color-activity-bar-ring);
  transform: translateY(-50%);
}

.activity-bar.management .knowledge-submenu {
  position: relative;
  top: auto;
  left: auto;
  min-width: 0;
  width: auto;
  padding: 0 0 0 var(--space-12);
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  transform: none;
}

/* File-tree style hierarchy guide for the expanded library branch. */
.activity-bar.management .knowledge-submenu::before {
  position: absolute;
  top: 16px;
  bottom: 16px;
  left: 5px;
  width: 1px;
  border-radius: 999px;
  background: var(--color-activity-bar-guide);
  content: '';
  opacity: 0.9;
  transition: opacity 180ms ease;
}

.knowledge-hover-indicator {
  position: absolute;
  top: 0;
  left: 50%;
  z-index: 0;
  display: none;
  width: 36px;
  height: 36px;
  margin-left: -18px;
  border-radius: 50%;
  background: var(--color-activity-bar-hover);
  pointer-events: none;
  transition:
    transform 220ms cubic-bezier(0.23, 1, 0.32, 1),
    opacity 150ms ease;
  will-change: transform;
}

.activity-bar.management .knowledge-hover-indicator {
  right: 0;
  left: var(--space-12);
  width: auto;
  height: 32px;
  margin-left: 0;
  border-radius: var(--radius-sm);
}

@media (hover: hover) and (pointer: fine) {
  .knowledge-hover-indicator {
    display: block;
  }
}

@media (prefers-reduced-motion: reduce) {
  .knowledge-hover-indicator {
    transition: opacity 150ms ease;
  }
}

.knowledge-submenu .activity-button {
  z-index: 1;
  width: 36px;
}

.activity-bar:not(.management) .knowledge-submenu .activity-button {
  margin-inline: auto;
}

.activity-bar.management .knowledge-submenu .activity-button {
  width: 100%;
  overflow: visible;
}

.activity-bar.management .knowledge-submenu .activity-button::before {
  position: absolute;
  top: 50%;
  left: -7px;
  width: 7px;
  height: 1px;
  border-radius: 999px;
  background: var(--color-activity-bar-guide);
  content: '';
  transform: translateY(-50%);
}

.activity-bar.management .knowledge-submenu .activity-button.active::before {
  background: var(--color-primary);
}

.activity-bar.management .knowledge-submenu .activity-label {
  max-width: 136px;
  opacity: 1;
  transform: translateX(0);
}

.knowledge-submenu-enter-active,
.knowledge-submenu-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
  transform-origin: top left;
}

.activity-bar.management .knowledge-submenu-enter-active,
.activity-bar.management .knowledge-submenu-leave-active {
  max-height: 240px;
  overflow: hidden;
  transition: max-height 220ms ease, opacity 180ms ease, transform 180ms ease;
}

.activity-bar.management .knowledge-submenu-enter-from,
.activity-bar.management .knowledge-submenu-leave-to {
  max-height: 0;
  opacity: 0;
  transform: translateY(-4px);
}

.activity-bar.management .knowledge-submenu-enter-to,
.activity-bar.management .knowledge-submenu-leave-from {
  max-height: 240px;
  opacity: 1;
  transform: translateY(0);
}

.knowledge-submenu-enter-from,
.knowledge-submenu-leave-to {
  opacity: 0;
  transform: translateX(-6px) scale(0.98);
}

.knowledge-submenu-enter-to,
.knowledge-submenu-leave-from {
  opacity: 1;
  transform: translateX(0) scale(1);
}

.activity-bar:not(.management) .knowledge-submenu-enter-from,
.activity-bar:not(.management) .knowledge-submenu-leave-to {
  transform: translate(-6px, -50%) scale(0.98);
}

.activity-bar:not(.management) .knowledge-submenu-enter-to,
.activity-bar:not(.management) .knowledge-submenu-leave-from {
  transform: translateY(-50%) scale(1);
}

.ripple-effect {
  position: absolute;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  background: var(--color-primary);
  animation: ripple-expand 0.35s ease-out;
  pointer-events: none;
  will-change: transform;
  z-index: 0;
}

@keyframes ripple-expand {
  0% {
    transform: scale(0);
    opacity: 1;
  }
  100% {
    transform: scale(2.5);
    opacity: 0;
  }
}

.activity-button.active {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #ffffff;
}

.activity-bar.management .activity-button.active {
  border-color: transparent;
  background: var(--color-activity-bar-active-bg);
  color: var(--color-activity-bar-active-text);
}

.activity-agent-icon {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  object-fit: contain;
  position: relative;
  z-index: 1;
}

.activity-button :deep(svg) {
  flex: 0 0 auto;
  position: relative;
  z-index: 1;
}

.library-color-files { color: var(--color-search-files); }
.library-color-library { color: var(--color-search-library); }
.library-color-components { color: var(--color-search-components); }
.library-color-vault { color: var(--color-library-vault); }
.library-color-forms { color: var(--color-library-forms); }
.library-color-literature { color: var(--color-search-literature); }

.activity-label {
  display: inline-block;
  position: relative;
  z-index: 1;
  max-width: 0;
  overflow: hidden;
  opacity: 0;
  color: currentColor;
  font-size: calc(12px * var(--font-scale));
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  transform: translateX(-6px);
  transition:
    max-width 180ms ease,
    opacity 140ms ease,
    transform 180ms ease;
}

.activity-bar.management .activity-label {
  width: 100%;
  max-width: none;
  opacity: 1;
  text-align: left;
  transform: translateX(0);
  transition-delay: 40ms;
}

.bottom-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
  margin-top: auto;
}

.activity-bar.management .bottom-group {
  align-items: stretch;
  width: 100%;
}
</style>
