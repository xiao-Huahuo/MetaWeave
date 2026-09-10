<!--
  Component library page.

  Usage:
  Keeps the Uiverse-style component masonry and fixed-tag sidebar, provides an
  internal toolbar, and overlays upload while switching details in-place.
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import ComponentLibraryCard from '@/components/component_library/ComponentLibraryCard.vue'
import ComponentLibraryDetail from '@/components/component_library/ComponentLibraryDetail.vue'
import ComponentNameEditor from '@/components/component_library/ComponentNameEditor.vue'
import ComponentUploadForm from '@/components/component_library/ComponentUploadForm.vue'
import {
  deleteComponentLibraryItem,
  listComponentLibraryItems,
  renameComponentLibraryItem,
} from '@/api/componentLibrary'
import { useFavoritesStore } from '@/stores/favorites'
import { useSettingsStore } from '@/stores/settings'
import { useWorkspaceStore } from '@/stores/workspace'
import {
  COMPONENT_TAGS,
  type ComponentLibraryItem,
  type ComponentTag,
} from '@/types/componentLibrary'

defineOptions({ name: 'ComponentLibraryView' })

const props = withDefaults(defineProps<{
  favoritesOnlyLocked?: boolean
  mobile?: boolean
}>(), {
  favoritesOnlyLocked: false,
  mobile: false,
})

const settingsStore = useSettingsStore()
const workspaceStore = useWorkspaceStore()
const favoritesStore = useFavoritesStore()
const activeTag = ref<ComponentTag>('any')
const components = ref<ComponentLibraryItem[]>([])
const componentQuery = ref('')
const loading = ref(false)
const error = ref('')
const uploadOpen = ref(false)
const sidebarOpen = ref(true)
const selectedComponent = ref<ComponentLibraryItem | null>(null)
const renamingComponentId = ref('')
const deletingComponentId = ref('')
const favoritesOnly = ref(false)
const tagListRef = ref<HTMLElement | null>(null)
const tagHoverTop = ref(0)
const tagHoverVisible = ref(false)

const effectiveFavoritesOnly = computed(() => props.favoritesOnlyLocked || favoritesOnly.value)

/** Filter the loaded tag locally by component name for instant sidebar search. */
const visibleComponents = computed(() => {
  const favoriteIds = favoritesStore.idsFor('component')
  const filtered = effectiveFavoritesOnly.value
    ? components.value.filter((component) => favoriteIds.has(component.component_id))
    : components.value
  const query = componentQuery.value.trim().toLocaleLowerCase()
  if (!query) return filtered
  return filtered.filter((component) => component.title.toLocaleLowerCase().includes(query))
})

/** Sidebar order presents the all-filter first while preserving its API value. */
const sidebarTags: ComponentTag[] = [
  'any',
  ...COMPONENT_TAGS.filter((tag) => tag !== 'any'),
]

const tagIcons: Record<ComponentTag, string> = {
  buttons: 'play',
  checkboxes: 'todo',
  'toggle switches': 'unfold',
  cards: 'view-stream',
  loaders: 'spinner',
  inputs: 'text-fields',
  'radio buttons': 'radio-unchecked',
  forms: 'fact-check',
  patterns: 'layers',
  tooltips: 'info',
  'drawing scripts': 'palette',
  any: 'book',
}

/** Request actual server data for the current user and selected tag. */
async function loadComponents(): Promise<void> {
  const userId = settingsStore.profile.userId
  if (!userId) return
  loading.value = true
  error.value = ''
  try {
    const result = await listComponentLibraryItems(userId, activeTag.value)
    components.value = result.components
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '组件库读取失败'
  } finally {
    loading.value = false
  }
}

/** Refresh the backend-persisted component favorites for the active library. */
async function loadComponentFavorites(): Promise<void> {
  const userId = settingsStore.profile.userId
  if (!userId) return
  await favoritesStore.load(userId, 'component', favoritesStore.activeLibraryId())
}

/** Toggle the local favorite-only filter unless a parent page locks it on. */
function toggleFavoritesOnly(): void {
  if (props.favoritesOnlyLocked) return
  favoritesOnly.value = !favoritesOnly.value
}

/** Resolve one tag button for the sidebar's delegated hover indicator. */
function resolveTagButton(target: EventTarget | null): HTMLElement | null {
  const tagList = tagListRef.value
  if (!tagList || !(target instanceof Element)) return null
  const button = target.closest<HTMLElement>('.tag-option')
  return button && tagList.contains(button) ? button : null
}

/** Move the shared sidebar hover surface behind the pointed or focused tag. */
function moveTagHover(event: MouseEvent | FocusEvent): void {
  const tagList = tagListRef.value
  const button = resolveTagButton(event.target)
  if (!tagList || !button) return
  tagHoverTop.value = button.getBoundingClientRect().top - tagList.getBoundingClientRect().top
  tagHoverVisible.value = true
}

/** Hide the sidebar hover surface after pointer and keyboard focus leave. */
function hideTagHover(event: MouseEvent | FocusEvent): void {
  const focusedButton = resolveTagButton(event instanceof FocusEvent ? event.relatedTarget : document.activeElement)
  if (focusedButton) return
  tagHoverVisible.value = false
}

/** Select one sidebar tag and return from the upload form to its component grid. */
function selectTag(tag: ComponentTag): void {
  activeTag.value = tag
  uploadOpen.value = false
  selectedComponent.value = null
}

/** Show the persisted upload in the matching grid after submission. */
function handleCreated(component: ComponentLibraryItem): void {
  activeTag.value = component.tag
  uploadOpen.value = false
  selectedComponent.value = null
  void loadComponents()
}

/** Open the dedicated large-preview and source-code workbench. */
function openDetails(component: ComponentLibraryItem): void {
  selectedComponent.value = component
  uploadOpen.value = false
}

/** Enter the upload surface from the internal toolbar. */
function openUpload(): void {
  selectedComponent.value = null
  uploadOpen.value = true
}

/** Persist one inline title edit and keep cards and details on the returned path. */
async function renameComponent(item: ComponentLibraryItem, title: string): Promise<void> {
  const previousId = item.component_id
  const previousItem = item
  const optimisticItem = { ...item, title }
  renamingComponentId.value = previousId
  components.value = components.value.map((component) => (
    component.component_id === previousId ? optimisticItem : component
  ))
  if (selectedComponent.value?.component_id === previousId) selectedComponent.value = optimisticItem
  try {
    const result = await renameComponentLibraryItem(settingsStore.profile.userId, previousId, title)
    components.value = components.value.map((component) => (
      component.component_id === previousId ? result.component : component
    ))
    if (selectedComponent.value?.component_id === previousId) selectedComponent.value = result.component
  } catch (caught) {
    components.value = components.value.map((component) => (
      component.component_id === previousId ? previousItem : component
    ))
    if (selectedComponent.value?.component_id === previousId) selectedComponent.value = previousItem
    error.value = caught instanceof Error ? caught.message : '组件重命名失败'
  } finally {
    renamingComponentId.value = ''
  }
}

/** Delete one canonical component through the component-library service. */
async function deleteComponent(item: ComponentLibraryItem): Promise<void> {
  if (!window.confirm(`确认删除“${item.title}”？`)) return
  deletingComponentId.value = item.component_id
  error.value = ''
  try {
    await deleteComponentLibraryItem(settingsStore.profile.userId, item.component_id)
    components.value = components.value.filter((component) => component.component_id !== item.component_id)
    if (selectedComponent.value?.component_id === item.component_id) selectedComponent.value = null
    workspaceStore.showToast(`已删除 ${item.title}`)
  } catch (caught) {
    const message = caught instanceof Error ? caught.message : '组件删除失败'
    error.value = message
    workspaceStore.showToast(message)
  } finally {
    deletingComponentId.value = ''
  }
}

/** Render the all-filter with the user-facing label requested for the sidebar. */
function tagLabel(tag: ComponentTag): string {
  if (tag === 'any') return 'all'
  return tag === 'drawing scripts' ? '绘图脚本' : tag
}

watch(activeTag, () => {
  if (!uploadOpen.value) void loadComponents()
})

watch(
  () => workspaceStore.pendingMainSearchResult,
  (result) => {
    if (result?.source !== 'components') return
    const component = result.item as unknown as ComponentLibraryItem
    activeTag.value = component.tag
    selectedComponent.value = component
    uploadOpen.value = false
    workspaceStore.pendingMainSearchResult = null
  },
  { immediate: true },
)

watch(
  [() => settingsStore.profile.userId, () => settingsStore.activeKnowledgeLibrary?.libraryId],
  () => {
    void Promise.all([loadComponents(), loadComponentFavorites()])
  },
)

onMounted(() => {
  void Promise.all([loadComponents(), loadComponentFavorites()])
})
</script>

<template>
  <section
    class="component-library-view"
    :class="{ mobile, 'sidebar-collapsed': !sidebarOpen }"
  >
    <aside class="tag-sidebar" aria-label="组件标签">
      <div class="sidebar-title">
        <button
          v-if="mobile"
          class="component-sidebar-toggle"
          type="button"
          title="折叠组件库侧边栏"
          aria-label="折叠组件库侧边栏"
          @click="sidebarOpen = false"
        >
          <IcIcon name="arrow-left" :size="18" />
        </button>
        <IcIcon name="grid-view" :size="17" />
        <span>组件库</span>
      </div>
      <label class="component-search">
        <IcIcon name="search" :size="15" />
        <input v-model="componentQuery" type="search" placeholder="搜索组件" aria-label="搜索组件" />
      </label>
      <nav
        ref="tagListRef"
        class="tag-list"
        @mouseover="moveTagHover"
        @mouseleave="hideTagHover"
        @focusin="moveTagHover"
        @focusout="hideTagHover"
      >
        <span
          class="tag-hover-indicator"
          aria-hidden="true"
          :style="{
            transform: `translate3d(0, ${tagHoverTop}px, 0)`,
            opacity: tagHoverVisible ? 1 : 0,
          }"
        ></span>
        <button
          v-for="tag in sidebarTags"
          :key="tag"
          class="tag-option"
          :class="{ active: activeTag === tag && !uploadOpen }"
          type="button"
          :aria-pressed="activeTag === tag && !uploadOpen"
          @click="selectTag(tag)"
        >
          <IcIcon :name="tagIcons[tag]" :size="16" />
          <span>{{ tagLabel(tag) }}</span>
        </button>
      </nav>
    </aside>

    <main class="component-main">
      <header class="component-toolbar">
        <div class="toolbar-context">
          <Transition name="component-sidebar-toggle">
            <button
              v-if="mobile && !sidebarOpen"
              class="component-sidebar-toggle v1-icon-button"
              type="button"
              title="展开组件库侧边栏"
              aria-label="展开组件库侧边栏"
              @click="sidebarOpen = true"
            >
              <IcIcon name="arrow-right" :size="18" />
            </button>
          </Transition>
          <button
            v-if="selectedComponent"
            class="detail-back v1-icon-button"
            type="button"
            title="返回组件列表"
            aria-label="返回组件列表"
            @click="selectedComponent = null"
          >
            <IcIcon name="arrow-left" :size="17" />
          </button>
          <div class="toolbar-copy">
            <ComponentNameEditor
              v-if="selectedComponent"
              :name="selectedComponent.title"
              :saving="renamingComponentId === selectedComponent.component_id"
              @rename="renameComponent(selectedComponent, $event)"
            />
            <strong v-else>浏览组件</strong>
          </div>
        </div>
        <div v-if="!selectedComponent" class="toolbar-actions">
          <button
            class="favorite-filter"
            :class="{ active: effectiveFavoritesOnly }"
            type="button"
            title="我的收藏"
            aria-label="我的收藏"
            :aria-pressed="effectiveFavoritesOnly"
            :disabled="favoritesOnlyLocked"
            @click="toggleFavoritesOnly"
          >
            <IcIcon name="star" :size="17" />
          </button>
          <button
            class="upload-trigger"
            :class="{ active: uploadOpen }"
            type="button"
            @click="openUpload"
          >
            <IcIcon name="add" :size="17" />
            <span>上传组件</span>
          </button>
        </div>
      </header>

      <ComponentUploadForm
        v-if="uploadOpen"
        :user-id="settingsStore.profile.userId"
        @cancel="uploadOpen = false"
        @created="handleCreated"
      />

      <div class="component-content" :class="{ 'detail-content': selectedComponent }">
        <ComponentLibraryDetail
          v-if="selectedComponent"
          :item="selectedComponent"
          :deleting="deletingComponentId === selectedComponent.component_id"
          @delete="deleteComponent"
        />
        <template v-else>
          <div v-if="loading" class="page-state">正在读取组件</div>
          <div v-else-if="error" class="page-state error" role="alert">{{ error }}</div>
          <div v-else-if="!visibleComponents.length" class="page-state">
            {{ componentQuery.trim() ? '没有匹配的组件' : '这个标签下还没有组件' }}
          </div>
          <section v-else class="component-grid" aria-label="组件块">
            <ComponentLibraryCard
              v-for="item in visibleComponents"
              :key="item.component_id"
              :item="item"
              :renaming="renamingComponentId === item.component_id"
              :deleting="deletingComponentId === item.component_id"
              @open="openDetails"
              @rename="renameComponent"
              @delete="deleteComponent"
            />
          </section>
        </template>
      </div>
    </main>
  </section>
</template>

<style scoped>
.component-library-view {
  position: relative;
  display: grid;
  grid-template-columns: 222px minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  height: 100%;
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-ui);
}

.component-sidebar-toggle {
  display: none;
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
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.component-sidebar-toggle:hover {
  background: var(--color-selection-blue-soft);
  color: var(--color-selection-blue);
}

.tag-sidebar {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: var(--space-10);
  margin: var(--space-12);
  padding: var(--space-16) var(--space-12);
  border: 0;
  border-radius: 28px;
  background: var(--color-surface);
  box-shadow: 0 0 0 4px var(--library-form-ring);
  animation: component-sidebar-enter 220ms cubic-bezier(0.23, 1, 0.32, 1) both;
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  min-height: 32px;
  padding: 0 var(--space-10);
  font-size: calc(13px * var(--font-scale));
  font-weight: 700;
}

.component-search {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  min-width: 0;
  width: 100%;
  max-width: 100%;
  height: 30px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text-muted);
}

.component-search:focus-within {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.component-search input {
  min-width: 0;
  width: 100%;
  flex: 1;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
  font-size: calc(13px * var(--font-scale));
}

.tag-list {
  position: relative;
  display: grid;
  gap: var(--space-4);
}

.tag-hover-indicator {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  z-index: 0;
  display: none;
  height: 36px;
  border-radius: 9px;
  background: var(--color-canvas-soft);
  pointer-events: none;
  transition:
    transform 220ms cubic-bezier(0.23, 1, 0.32, 1),
    opacity 150ms ease;
  will-change: transform;
}

.tag-option {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  align-items: center;
  gap: var(--space-8);
  width: 100%;
  min-height: 36px;
  overflow: hidden;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--color-text-secondary);
  padding: 0 var(--space-10);
  cursor: pointer;
  font-size: calc(12px * var(--font-scale));
  text-align: left;
  transition:
    background-color 150ms ease,
    color 150ms ease;
}

.tag-option::before {
  position: absolute;
  top: 7px;
  bottom: 7px;
  left: 0;
  width: 3px;
  border-radius: 999px;
  background: var(--color-primary);
  content: '';
  transform: scaleY(0);
  transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1);
}

.tag-option:hover {
  background: var(--color-canvas-soft);
  color: var(--color-text);
}

.tag-option.active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.tag-option.active::before {
  transform: scaleY(1);
}

.component-main {
  display: grid;
  grid-template-rows: 44px minmax(0, 1fr);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.component-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-12);
  min-width: 0;
  min-height: 44px;
  padding: var(--space-8) var(--space-12);
  border: 0;
  background: color-mix(in srgb, var(--color-surface) 92%, transparent);
  font-size: calc(12px * var(--font-scale));
}

.toolbar-context,
.toolbar-copy,
.toolbar-actions,
.upload-trigger,
.detail-back,
.favorite-filter {
  display: flex;
  align-items: center;
}

.toolbar-context {
  min-width: 0;
  gap: var(--space-8);
}

.toolbar-copy {
  min-width: 0;
}

.toolbar-actions {
  gap: var(--space-4);
}

.toolbar-copy strong {
  max-width: min(52vw, 520px);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toolbar-copy strong {
  font-size: inherit;
}

.component-toolbar .upload-trigger {
  font: inherit;
  font-weight: 700;
}

.detail-back {
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    color 140ms ease,
    transform 140ms cubic-bezier(0.23, 1, 0.32, 1);
}

.detail-back:hover {
  color: var(--color-primary);
}

.favorite-filter {
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
}

.favorite-filter:hover:not(:disabled),
.favorite-filter.active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.favorite-filter:disabled {
  cursor: default;
}

.upload-trigger {
  justify-content: center;
  gap: var(--space-6);
  flex: 0 0 auto;
  min-width: 116px;
  height: 28px;
  min-height: 28px;
  border: 1px solid var(--color-primary);
  border-radius: 999px;
  background: var(--color-primary);
  color: white;
  padding: 0 var(--space-10);
  cursor: pointer;
  font-size: calc(12px * var(--font-scale));
  font-weight: 700;
  white-space: nowrap;
  box-shadow: none;
}

.upload-trigger:hover,
.upload-trigger.active {
  background: color-mix(in srgb, var(--color-primary) 84%, white);
}

.component-content {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: var(--space-16);
}

.component-content.detail-content {
  overflow: hidden;
  padding: 0;
}

.component-grid {
  columns: 280px auto;
  column-gap: var(--space-16);
}

.page-state {
  display: grid;
  place-items: center;
  min-height: 280px;
  color: var(--color-text-muted);
  font-size: calc(13px * var(--font-scale));
}

.page-state.error {
  color: var(--color-danger);
}

@media (hover: hover) and (pointer: fine) {
  .tag-hover-indicator {
    display: block;
  }

  .tag-option:hover:not(.active) {
    background: transparent;
  }

  .detail-back:hover {
    transform: translateX(-2px);
  }
}

@keyframes component-sidebar-enter {
  from { opacity: 0; transform: translateX(-8px) scale(0.985); }
  to { opacity: 1; transform: translateX(0) scale(1); }
}

.component-library-view.mobile {
    grid-template-columns: minmax(0, 1fr);
    overflow: hidden;
}

.component-library-view.mobile .tag-sidebar {
    position: absolute;
    inset: var(--space-8) auto var(--space-8) var(--space-8);
    z-index: 20;
    width: min(280px, calc(100% - var(--space-16)));
    margin: 0;
    padding: var(--space-12);
    overflow: hidden;
    border: 0;
    border-radius: 18px;
    box-shadow: 12px 0 32px rgba(12, 18, 38, 0.22);
    opacity: 1;
    transform: translateX(0);
    animation: none;
    transition: opacity 160ms ease, transform 180ms ease;
}

.component-library-view.mobile.sidebar-collapsed .tag-sidebar {
    pointer-events: none;
    opacity: 0;
    transform: translateX(calc(-100% - var(--space-16)));
}

.component-library-view.mobile .component-sidebar-toggle {
    display: inline-flex;
}

.component-library-view.mobile .sidebar-title {
    display: flex;
    padding: 0;
}

.component-library-view.mobile .component-search {
    flex: none;
}

.component-library-view.mobile .tag-list {
    display: grid;
    overflow-y: auto;
}

.component-library-view.mobile .tag-option {
    width: 100%;
    min-width: 0;
}

.component-library-view.mobile .component-toolbar {
    padding: var(--space-8) var(--space-12);
}

.component-library-view.mobile .component-content {
    padding: var(--space-12);
}

.component-sidebar-toggle-enter-active,
.component-sidebar-toggle-leave-active {
    transition: opacity 160ms ease, transform 180ms ease;
}

.component-sidebar-toggle-enter-from,
.component-sidebar-toggle-leave-to {
    opacity: 0;
    transform: translateX(-12px);
}

@media (prefers-reduced-motion: reduce) {
  .tag-hover-indicator {
    transition: opacity 150ms ease;
  }

  .tag-sidebar {
    animation: none;
    transform: none;
  }

  .tag-option::before,
  .detail-back {
    transform: none;
  }
}
</style>
