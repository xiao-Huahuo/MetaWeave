<!--
  Inline search bar + dropdown results.

  Usage:
  Embedded in TopCommandBar or SearchPage. Both variants share the same
  history, search toggles, AI action, and grouped result preview dropdown.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import PixelLoader from '@/components/common/PixelLoader.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import type { SearchSource, UnifiedSearchResult } from '@/types/unifiedSearch'
import { SEARCH_SOURCE_PRESENTATION } from '@/utils/searchSourcePresentation'

defineOptions({ name: 'SearchPalette' })

const props = withDefaults(defineProps<{
  variant?: 'toolbar' | 'page'
}>(), {
  variant: 'toolbar',
})

const emit = defineEmits<{
  submit: []
}>()

const workspaceStore = useWorkspaceStore()

const inputEl = ref<HTMLInputElement | null>(null)
const wrapperEl = ref<HTMLElement | null>(null)
const dropdownEl = ref<HTMLElement | null>(null)
const focused = ref(false)
const dropdownPos = ref({ top: 0, left: 0, width: 0 })
let wrapperResizeObserver: ResizeObserver | null = null
let anchorFrame: number | null = null

function updateDropdownPos() {
  if (!wrapperEl.value) return
  const rect = wrapperEl.value.getBoundingClientRect()
  const next = { top: rect.bottom + 4, left: rect.left, width: rect.width }
  if (next.top !== dropdownPos.value.top || next.left !== dropdownPos.value.left || next.width !== dropdownPos.value.width) {
    dropdownPos.value = next
  }
}

const showDropdown = computed(() => focused.value)

function handleClickOutside(event: MouseEvent) {
  const target = event.target as Node
  if (
    wrapperEl.value
    && !wrapperEl.value.contains(target)
    && !dropdownEl.value?.contains(target)
  ) {
    focused.value = false
  }
}

/** Track position, not only size, while surrounding sidebars animate. */
function trackDropdownAnchor() {
  updateDropdownPos()
  if (focused.value) anchorFrame = window.requestAnimationFrame(trackDropdownAnchor)
}

/** Start one bounded animation-frame loop for the currently open dropdown. */
function startAnchorTracking() {
  if (anchorFrame !== null) window.cancelAnimationFrame(anchorFrame)
  anchorFrame = window.requestAnimationFrame(trackDropdownAnchor)
}

/** Stop position tracking immediately after the menu closes. */
function stopAnchorTracking() {
  if (anchorFrame !== null) window.cancelAnimationFrame(anchorFrame)
  anchorFrame = null
}

onMounted(() => {
  document.addEventListener('mousedown', handleClickOutside)
  updateDropdownPos()
  window.addEventListener('resize', updateDropdownPos)
  if (wrapperEl.value && typeof ResizeObserver !== 'undefined') {
    wrapperResizeObserver = new ResizeObserver(updateDropdownPos)
    wrapperResizeObserver.observe(wrapperEl.value)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleClickOutside)
  window.removeEventListener('resize', updateDropdownPos)
  wrapperResizeObserver?.disconnect()
  wrapperResizeObserver = null
  stopAnchorTracking()
})

function selectHistory(query: string) {
  workspaceStore.searchQuery = query
  workspaceStore.performSearch(query)
  inputEl.value?.focus()
}

watch(() => workspaceStore.searchOpen, (open) => {
  if (open) {
    nextTick(() => inputEl.value?.focus())
  }
})

function onFocus() {
  focused.value = true
  nextTick(() => {
    updateDropdownPos()
    startAnchorTracking()
  })
}

/** Collapse only when keyboard focus leaves the complete search control. */
function onBlur(event: FocusEvent) {
  const nextTarget = event.relatedTarget as Node | null
  if (!wrapperEl.value?.contains(nextTarget) && !dropdownEl.value?.contains(nextTarget)) {
    focused.value = false
    stopAnchorTracking()
  }
}

/** Open one dropdown result through its owning library workflow. */
function handleOpenResult(result: UnifiedSearchResult) {
  void workspaceStore.openSearchResultSidebar(result)
  focused.value = false
  stopAnchorTracking()
}

function toggleFulltext() {
  workspaceStore.fulltextEnabled = !workspaceStore.fulltextEnabled
  if (workspaceStore.searchQuery.trim()) {
    workspaceStore.performSearch(workspaceStore.searchQuery)
  }
}

function toggleSemantic() {
  workspaceStore.semanticEnabled = !workspaceStore.semanticEnabled
  if (workspaceStore.searchQuery.trim()) {
    workspaceStore.performSearch(workspaceStore.searchQuery)
  }
}

/** Toggle one backend source while the store protects the last active source. */
function toggleSource(source: SearchSource) {
  workspaceStore.toggleSearchSource(source)
}

function clearQuery() {
  workspaceStore.searchQuery = ''
  inputEl.value?.focus()
}

function askAgentSearch() {
  const q = workspaceStore.searchQuery.trim()
  if (!q) return
  const sourceLabels = workspaceStore.searchSources.map((source) => SEARCH_SOURCE_PRESENTATION[source].label).join('、')
  workspaceStore.agentSidebarOpen = true
  workspaceStore.pendingAgentPrompt = `请使用四库联合搜索工具搜索“${q}”。搜索范围：${sourceLabels}；全文搜索：${workspaceStore.fulltextEnabled ? '开启' : '关闭'}；语义搜索：${workspaceStore.semanticEnabled ? '开启' : '关闭'}。`
}

/** Submits through the owning page or navigates there from the toolbar. */
function handleSubmit() {
  workspaceStore.searchQuery = workspaceStore.searchQuery.trim()
  if (props.variant === 'page') {
    emit('submit')
  } else {
    workspaceStore.setMainView('search')
  }
  focused.value = false
}

/** Focuses the shared input when its owning view becomes active. */
function focus() {
  focused.value = true
  nextTick(() => inputEl.value?.focus())
}

defineExpose({ focus })
</script>

<template>
  <div
    ref="wrapperEl"
    class="search-wrapper"
    :class="{ focused: focused, 'page-variant': variant === 'page' }"
  >
    <div class="search-bar">
      <button
        v-if="variant === 'toolbar'"
        class="toolbar-search-btn"
        type="button"
        aria-label="搜索"
        @click="focus"
      >
        <IcIcon name="search" :size="16" class="search-icon" />
      </button>
      <IcIcon v-else name="search" :size="16" class="search-icon" />
      <input
        ref="inputEl"
        v-model="workspaceStore.searchQuery"
        type="text"
        :placeholder="variant === 'page' ? '搜索文件...' : ''"
        class="search-input"
        aria-label="搜索文件"
        :aria-expanded="showDropdown"
        aria-haspopup="listbox"
        @focus="onFocus"
        @click="onFocus"
        @blur="onBlur"
        @keydown.enter.prevent="handleSubmit"
      />
      <PixelLoader v-if="workspaceStore.searching" class="search-pixel-loader" />
      <button
        v-if="workspaceStore.searchQuery && !workspaceStore.searching"
        class="clear-btn"
        type="button"
        @click="clearQuery"
      >
        <IcIcon name="close" :size="12" />
      </button>
      <button
        v-if="variant === 'page'"
        class="search-submit-btn"
        :class="{ 'search-box-submit': variant === 'page' }"
        type="button"
        @click="handleSubmit"
      >
        <IcIcon name="search" :size="12" class="submit-icon" />
        <span class="submit-label">Search</span>
      </button>
    </div>

    <!-- Dropdown results -->
    <Teleport to="body">
      <Transition name="dropdown">
        <div
          v-if="showDropdown"
          ref="dropdownEl"
          class="search-dropdown"
          :class="{ 'page-search-dropdown': variant === 'page' }"
          :style="{
            position: 'fixed',
            top: dropdownPos.top + 'px',
            left: dropdownPos.left + 'px',
            width: dropdownPos.width + 'px',
          }"
        >
        <!-- Toggle row: always visible -->
        <div class="toggle-row">
          <button
            class="toggle-btn"
            :class="{ on: workspaceStore.fulltextEnabled }"
            type="button"
            @mousedown.prevent="toggleFulltext"
          >
            <div class="toggle-inner">
              <div class="toggle-dot"></div>
              <span class="toggle-label">内容搜索</span>
            </div>
            <div class="toggle-overlay">
              <div class="toggle-overlay-inner">
                <IcIcon name="manage-search" :size="12" />
                <span>内容搜索</span>
                <svg xmlns="http://www.w3.org/2000/svg" class="toggle-arrow" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 12h14"></path>
                  <path stroke-linecap="round" stroke-linejoin="round" d="M13 6l6 6-6 6"></path>
                </svg>
              </div>
            </div>
          </button>
          <button
            class="toggle-btn"
            :class="{ on: workspaceStore.semanticEnabled }"
            type="button"
            @mousedown.prevent="toggleSemantic"
          >
            <div class="toggle-inner">
              <div class="toggle-dot"></div>
              <span class="toggle-label">语义搜索</span>
            </div>
            <div class="toggle-overlay">
              <div class="toggle-overlay-inner">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                </svg>
                <span>语义搜索</span>
                <svg xmlns="http://www.w3.org/2000/svg" class="toggle-arrow" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 12h14"></path>
                  <path stroke-linecap="round" stroke-linejoin="round" d="M13 6l6 6-6 6"></path>
                </svg>
              </div>
            </div>
          </button>
          <button
            class="ai-search-btn"
            type="button"
            title="AI 帮你搜索"
            @mousedown.prevent="askAgentSearch"
          >
            <IcIcon name="auto-awesome" :size="12" />
          </button>
        </div>

        <div class="source-toggle-row" :class="{ 'toolbar-source-row': variant === 'toolbar' }" aria-label="搜索来源">
          <button
            v-for="(presentation, source) in SEARCH_SOURCE_PRESENTATION"
            :key="source"
            class="source-toggle-btn"
            :class="{ on: workspaceStore.searchSources.includes(source) }"
            type="button"
            :title="presentation.label"
            :aria-label="presentation.label"
            :aria-pressed="workspaceStore.searchSources.includes(source)"
            :style="{ '--source-color': presentation.color }"
            @mousedown.prevent="toggleSource(source)"
          >
            <IcIcon class="source-toggle-icon" :name="presentation.icon" :size="14" />
            <span v-if="variant === 'page'" class="source-toggle-label">{{ presentation.label }}</span>
          </button>
        </div>

        <!-- History: no query, has history -->
        <template v-if="!workspaceStore.searchQuery && workspaceStore.searchHistory.length">
          <div class="result-list">
            <div class="history-header">
              <span class="group-label">最近搜索</span>
              <button class="history-clear-btn" type="button" title="清除历史" @mousedown.prevent="workspaceStore.clearSearchHistory()">
                <IcIcon name="trash" :size="11" />
              </button>
            </div>
            <button
              v-for="item in workspaceStore.searchHistory"
              :key="item"
              class="result-row history-row"
              type="button"
              @mousedown.prevent="selectHistory(item)"
            >
              <IcIcon name="schedule" :size="12" class="history-icon" />
              <span class="history-text">{{ item }}</span>
            </button>
          </div>
        </template>

        <!-- Search mode: has query -->
        <template v-if="workspaceStore.searchQuery">
          <!-- Results -->
          <div v-if="workspaceStore.searchResults" class="result-list">
            <button
              v-for="item in workspaceStore.searchResults.results.slice(0, 12)"
              :key="`${item.source}:${item.id}`"
              class="result-row"
              type="button"
              @mousedown.prevent="handleOpenResult(item)"
            >
              <span class="result-name">{{ item.title }}</span>
              <span class="result-meta">{{ item.snippet || item.locator }}</span>
              <span class="result-source">{{ SEARCH_SOURCE_PRESENTATION[item.source].label }}</span>
            </button>
          </div>
          <div v-else-if="!workspaceStore.searching" class="result-list empty-state">
            {{ workspaceStore.searchError || '无匹配结果' }}
          </div>
        </template>
      </div>
    </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.search-wrapper {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-width: 336px;
  width: 100%;
  margin: 2px 0;
  z-index: 100;
}

.search-wrapper:not(.page-variant) {
  width: 28px;
  max-width: 100%;
  margin-left: auto;
  opacity: 1;
  transition:
    width 200ms ease-in-out,
    opacity 200ms ease-in-out;
}

.search-wrapper.focused:not(.page-variant) {
  width: 250px;
  opacity: 1;
}

.search-wrapper.page-variant {
  max-width: none;
  margin: 0;
}

.search-bar {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-6);
  height: 26px;
  padding: 0 1px 0 var(--space-12);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  transition: border-color var(--transition-fast);
}

.search-wrapper:not(.page-variant):not(.focused) .search-bar {
  justify-content: center;
  gap: 0;
  padding: 0;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 50%;
  background: transparent;
}

.search-wrapper:not(.page-variant):not(.focused):hover .search-bar {
  background: var(--color-primary-softer);
}

.search-wrapper:not(.page-variant):not(.focused):hover .search-icon,
.search-wrapper:not(.page-variant):not(.focused):hover .toolbar-search-btn {
  color: var(--color-primary);
}

.search-wrapper:not(.page-variant):not(.focused) .search-input,
.search-wrapper:not(.page-variant):not(.focused) .search-pixel-loader,
.search-wrapper:not(.page-variant):not(.focused) .clear-btn {
  display: none;
}

.page-variant .search-bar {
  height: 48px;
  gap: 10px;
  padding: 0 4px 0 18px;
  border-width: 2px;
}

.page-variant .search-input {
  font-size: calc(15px * var(--font-scale));
}

.page-variant .clear-btn {
  width: 22px;
  height: 22px;
}

.page-variant .search-submit-btn {
  width: auto;
  height: 38px;
  padding: 0 20px 0 38px;
  line-height: 38px;
}

.page-variant .submit-icon {
  left: 14px;
}

.page-variant .submit-label {
  opacity: 1;
}

:root[data-theme="dark"] .search-bar {
  background: #1c1c20;
  border-color: #2a2a30;
}

:root[data-theme="light"] .search-bar {
  background: var(--color-surface);
  border-color: var(--color-border);
}

.search-wrapper.focused .search-bar {
  border-color: var(--color-primary);
}

.search-icon {
  flex-shrink: 0;
  color: var(--color-text-muted);
}

.toolbar-search-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.toolbar-search-btn:focus-visible {
  border-radius: 999px;
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.search-input {
  flex: 1;
  min-width: 0;
  height: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
}

:root[data-theme="dark"] .search-input::placeholder {
  color: #6b6b78;
}

:root[data-theme="light"] .search-input::placeholder {
  color: #9393a0;
}

.search-pixel-loader {
  flex-shrink: 0;
}

.clear-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  border: 0;
  border-radius: 999px;
  background: var(--color-border);
  color: var(--color-text-secondary);
  cursor: pointer;
  padding: 0;
}

.clear-btn:hover {
  background: var(--color-border-strong);
  color: var(--color-text);
}

.search-submit-btn {
  position: relative;
  height: 22px;
  width: 22px;
  padding: 0 0 0 22px;
  border: 1px solid var(--color-primary);
  border-radius: 999px;
  background: transparent;
  color: var(--color-primary);
  font-size: calc(11px * var(--font-scale));
  font-weight: 600;
  cursor: pointer;
  flex-shrink: 0;
  overflow: hidden;
  isolation: isolate;
  white-space: nowrap;
  line-height: 22px;
  transition: color 0.3s 0.1s ease-out;
  outline: none;
  text-align: center;
}

.search-submit-btn::before {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  margin: auto;
  content: "";
  border-radius: 50%;
  display: block;
  width: 20em;
  height: 20em;
  left: -5em;
  text-align: center;
  transition: box-shadow 0.5s ease-out;
  z-index: 0;
}

.submit-icon {
  position: absolute;
  left: 5px;
  top: 50%;
  z-index: 1;
  transform: translateY(-50%);
}

.submit-label {
  position: relative;
  z-index: 1;
  opacity: 0;
  transition: opacity 180ms ease;
}

.search-submit-btn:hover {
  color: #fff;
}

.search-submit-btn:hover::before {
  box-shadow: inset 0 0 0 10em var(--color-primary);
}

.search-submit-btn:hover .submit-label {
  opacity: 1;
}

/* Dropdown */
.search-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  z-index: 100;
  max-height: 360px;
  overflow: hidden;
  border: 1px solid var(--color-border-strong);
  border-radius: 13px;
  background: var(--color-surface);
}

.search-dropdown.page-search-dropdown {
  max-height: 520px;
  border-radius: 24px;
}

.search-dropdown.page-search-dropdown .result-list {
  max-height: 450px;
}

:root[data-theme="dark"] .search-dropdown {
  background: #1c1c20;
  border-color: #2a2a30;
}

:root[data-theme="light"] .search-dropdown {
  background: var(--color-surface);
  border-color: var(--color-border);
}

.toggle-row {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-6) var(--space-10);
  border-bottom: 1px solid var(--color-border);
}

.source-toggle-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-4);
  padding: 0 var(--space-10) var(--space-8);
  border-bottom: 1px solid var(--color-border);
}

.source-toggle-btn {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-6);
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--source-color);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
  cursor: pointer;
  opacity: 0.42;
  transition: opacity var(--transition-fast), border-color var(--transition-fast);
}

.source-toggle-btn.on {
  border-bottom-color: var(--source-color);
  opacity: 1;
}

.source-toggle-btn:hover,
.source-toggle-btn:focus-visible {
  opacity: 1;
}

.source-toggle-icon {
  color: currentColor;
}

.source-toggle-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toolbar-source-row .source-toggle-btn {
  min-height: 26px;
  padding-inline: 0;
}

.toggle-btn {
  position: relative;
  cursor: pointer;
  overflow: hidden;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  background: transparent;
  padding: 0;
  font-size: calc(11px * var(--font-scale));
  font-weight: 500;
  font-family: var(--font-ui);
  color: var(--color-text-muted);
  box-shadow: none;
  transition: all 0.3s;
  outline: none;
}

.toggle-btn .toggle-inner {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 12px;
  transition: all 0.3s;
}

.toggle-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-text-muted);
  transition: all 0.3s;
}

.toggle-label {
  transition: all 0.3s;
  white-space: nowrap;
}

.toggle-overlay {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 10;
  display: flex;
  height: 100%;
  width: 100%;
  transform: translateX(100%);
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: var(--color-primary);
  color: #fff;
  opacity: 0;
  transition: all 0.3s;
}

.toggle-overlay-inner {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  padding: 2px 12px;
}

.toggle-overlay-inner span {
  font-size: calc(11px * var(--font-scale));
  font-weight: 500;
  line-height: 1;
}

.toggle-arrow {
  width: 12px;
  height: 12px;
  line-height: 1;
}

/* Off state hover: overlay fades in, inner fades out */
.toggle-btn:not(.on):hover .toggle-inner {
  opacity: 0;
}

.toggle-btn:not(.on):hover .toggle-overlay {
  transform: translateX(0);
  opacity: 1;
}

.toggle-btn:not(.on):hover {
  border-color: var(--color-primary);
}

/* On state: primary border + dot */
.toggle-btn.on {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.toggle-btn.on .toggle-dot {
  background: var(--color-primary);
}

/* On state hover: overlay fades in, inner fades out */
.toggle-btn.on:hover .toggle-inner {
  opacity: 0;
}

.toggle-btn.on:hover .toggle-overlay {
  transform: translateX(0);
  opacity: 1;
}

.ai-search-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 1px solid var(--color-accent);
  border-radius: 999px;
  background: transparent;
  color: var(--color-accent);
  cursor: pointer;
  transition:
    border-color var(--transition-fast),
    color var(--transition-fast),
    background var(--transition-fast);
}

.ai-search-btn:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
  background: rgba(235, 36, 99, 0.12);
}

.result-list {
  max-height: 300px;
  overflow: auto;
  padding: var(--space-6);
}

.result-group {
  padding: var(--space-2) 0;
}

.group-label {
  padding: var(--space-4) var(--space-8);
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.result-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-8);
  width: 100%;
  padding: var(--space-6) var(--space-8);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text);
  text-align: left;
  cursor: pointer;
}

.result-row:hover {
  background: var(--color-primary-soft);
}

.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-8);
}

.history-clear-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.history-clear-btn:hover {
  background: var(--color-primary-soft);
  color: var(--color-text);
}

.history-row {
  align-items: center;
  gap: var(--space-8);
}

.history-icon {
  flex-shrink: 0;
  color: var(--color-text-muted);
}

.history-text {
  font-size: calc(13px * var(--font-scale));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-name {
  font-size: calc(13px * var(--font-scale));
  font-weight: 600;
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-meta {
  font-size: calc(12px * var(--font-scale));
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.result-source {
  flex: 0 0 auto;
  align-self: center;
  color: var(--color-primary);
  font-size: calc(10px * var(--font-scale));
  white-space: nowrap;
}

@media (max-width: 420px) {
  .source-toggle-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

hr {
  margin: var(--space-4) var(--space-6);
  border: 0;
  border-top: 1px solid var(--color-border);
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-20);
  color: var(--color-text-muted);
  font-size: calc(13px * var(--font-scale));
}

/* Transition */
.dropdown-enter-active {
  transition: opacity 120ms ease, transform 120ms ease;
}

.dropdown-leave-active {
  transition: opacity 100ms ease, transform 100ms ease;
}

.dropdown-enter-from {
  opacity: 0;
  transform: translateY(-4px);
}

.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
