<!--
  Virtual library large-icon card.

  Usage:
  Render one book or collection in the library grid. The card supports selection,
  double-click opening, and drag-moving items into collection cards.
-->
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import { buildApiUrl } from '@/api/client'
import FavoriteButton from '@/components/common/FavoriteButton.vue'
import PrivacyButton from '@/components/common/PrivacyButton.vue'
import { materialFileIconForNode } from '@/components/editor_workspace/materialFileIcons'
import type { LibraryItem } from '@/types/knowledge'
import { usePrivacyStore } from '@/stores/privacy'

const props = defineProps<{
  item: LibraryItem
  selected: boolean
  multiSelect: boolean
  readonly?: boolean
}>()

const emit = defineEmits<{
  open: [item: LibraryItem]
  edit: [item: LibraryItem]
  toggle: [item: LibraryItem]
  select: [item: LibraryItem]
  contextmenu: [event: MouseEvent, item: LibraryItem]
  download: [item: LibraryItem]
  save: [item: LibraryItem, payload: { title?: string; description?: string }]
  dragStart: [item: LibraryItem]
  dropOn: [item: LibraryItem]
}>()

const dragOver = ref(false)
const privacyStore = usePrivacyStore()
const detailsOpen = ref(false)
const titleEditing = ref(false)
const descriptionEditing = ref(false)
const editTitle = ref(props.item.display_title)
const editDescription = ref(props.item.description)
const titleInput = ref<HTMLInputElement | null>(null)
const descriptionInput = ref<HTMLTextAreaElement | null>(null)
watch(() => props.selected, (selected) => {
  if (!selected) detailsOpen.value = false
})
watch(() => props.item, (item) => {
  if (!titleEditing.value) editTitle.value = item.display_title
  if (!descriptionEditing.value) editDescription.value = item.description
}, { deep: true })
const isCollection = computed(() => props.item.item_type === 'collection')
const isPrivate = computed(() => privacyStore.loading || privacyStore.isPrivate('library_item', props.item.item_id))
const fileIcon = computed(() => materialFileIconForNode({
  name: props.item.source_name || props.item.display_title,
  path: props.item.source_path || props.item.source_name,
  isDir: isCollection.value,
}))
const coverUrl = computed(() => {
  if (isPrivate.value) return ''
  if (props.item.cover_mode === 'image' && props.item.cover_asset?.url) {
    return props.item.cover_asset.url
  }
  if (props.item.cover_mode === 'source_image' && props.item.source_path) {
    return buildApiUrl('/knowledge/files/raw', {
      user_id: props.item.user_id,
      path: props.item.source_path,
    })
  }
  return ''
})
const sourceLabel = computed(() => {
  if (isCollection.value) return '集锦'
  if (props.item.content_type === 'web_url') return props.item.source_url
  return props.item.source_name || props.item.source_path || '未关联真实内容'
})
const dateLabel = computed(() => {
  const raw = props.item.source_mtime || props.item.updated_at
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw.slice(0, 16)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
})
const statusText = computed(() => {
  if (isCollection.value) return `${props.item.child_count} 项`
  const parts = [
    props.item.index_status ? `入库 ${props.item.index_status}` : '未入库',
    props.item.graph_status ? `图谱 ${props.item.graph_status}` : '无图谱',
  ]
  return parts.join(' / ')
})

function handleClick() {
  if (props.multiSelect) {
    emit('toggle', props.item)
    return
  }
  emit('select', props.item)
}

async function startTitleEdit() {
  if (isCollection.value || props.readonly) return
  emit('select', props.item)
  editTitle.value = props.item.display_title
  titleEditing.value = true
  await nextTick()
  titleInput.value?.focus()
  titleInput.value?.select()
}

async function startDescriptionEdit() {
  if (isCollection.value || props.readonly) return
  emit('select', props.item)
  detailsOpen.value = true
  editDescription.value = props.item.description
  descriptionEditing.value = true
  await nextTick()
  descriptionInput.value?.focus()
  descriptionInput.value?.select()
}

function saveTitle() {
  if (!titleEditing.value) return
  titleEditing.value = false
  const title = editTitle.value.trim()
  if (title && title !== props.item.title) emit('save', props.item, { title })
  else editTitle.value = props.item.display_title
}

function saveDescription() {
  if (!descriptionEditing.value) return
  descriptionEditing.value = false
  const description = editDescription.value.trim()
  if (description !== props.item.description) emit('save', props.item, { description })
}

function toggleDetails() {
  emit('select', props.item)
  detailsOpen.value = !detailsOpen.value
}

function handleDragStart(event: DragEvent) {
  if (props.readonly) {
    event.preventDefault()
    return
  }
  event.dataTransfer?.setData('text/plain', props.item.item_id)
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
  }
  emit('dragStart', props.item)
}

function handleDragOver(event: DragEvent) {
  if (!isCollection.value) return
  event.preventDefault()
  dragOver.value = true
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'move'
  }
}

function handleDrop(event: DragEvent) {
  if (!isCollection.value) return
  event.preventDefault()
  dragOver.value = false
  emit('dropOn', props.item)
}
</script>

<template>
  <article
    class="library-card"
    :class="{ selected, missing: !item.source_exists, 'drag-over': dragOver, collection: isCollection, 'details-open': detailsOpen }"
    :draggable="!readonly"
    @click="handleClick"
    @dblclick.stop="isCollection ? emit('open', item) : emit('edit', item)"
    @contextmenu.prevent="emit('contextmenu', $event, item)"
    @dragstart="handleDragStart"
    @dragover="handleDragOver"
    @dragleave="dragOver = false"
    @drop="handleDrop"
  >
    <section class="cover" :class="{ 'image-cover': coverUrl }">
      <PrivacyButton class="library-privacy" target-type="library_item" :target-id="item.item_id" />
      <FavoriteButton class="library-favorite" target-type="library_item" :target-id="item.item_id" />
      <button
        v-if="multiSelect"
        class="select-button"
        :class="{ checked: selected }"
        type="button"
        :title="selected ? '取消选择' : '选择'"
        @click.stop="emit('toggle', item)"
      >
        <IcIcon v-if="selected" name="check" :size="14" />
      </button>
      <div v-if="isPrivate" class="icon-cover privacy-cover" aria-label="隐私内容不显示封面">
        <IcIcon name="visibility-off" :size="52" />
      </div>
      <img v-else-if="coverUrl" class="cover-image" :src="coverUrl" alt="" />
      <div v-else-if="item.cover_mode === 'description' && item.description" class="text-cover">
        {{ item.description }}
      </div>
      <div v-else-if="item.cover_mode === 'title' || isCollection" class="title-cover">
        {{ item.display_title }}
      </div>
      <div v-else class="icon-cover">
        <IcIcon v-if="isCollection" name="folder-open" :size="52" />
        <IcIcon v-else-if="item.content_type === 'web_url'" name="link" :size="52" />
        <img v-else-if="fileIcon.src" class="file-icon" :src="fileIcon.src" alt="" />
        <IcIcon v-else name="image" :size="52" />
      </div>
    </section>
    <section class="meta">
      <div class="title-row">
        <button
          class="expand-button"
          :class="{ open: detailsOpen }"
          type="button"
          :title="detailsOpen ? '收起文件名和描述' : '展开文件名和描述'"
          @click.stop="toggleDetails"
        >
          <IcIcon :name="detailsOpen ? 'chevron-down' : 'chevron-right'" :size="14" morph />
        </button>
        <input
          v-if="titleEditing"
          ref="titleInput"
          v-model="editTitle"
          class="title-edit-input"
          type="text"
          aria-label="编辑图书名"
          @blur="saveTitle"
          @keydown.enter.prevent="saveTitle"
          @keydown.escape.prevent="titleEditing = false; editTitle = item.display_title"
        />
        <div v-else class="title" :title="item.display_title" @dblclick.stop="startTitleEdit">{{ item.display_title }}</div>
        <button
          v-if="!isCollection"
          class="download-button"
          type="button"
          title="下载真实文件"
          aria-label="下载真实文件"
          @click.stop="emit('download', item)"
        >
          <IcIcon name="download" :size="15" />
        </button>
      </div>
      <div v-if="item.tags.length" class="tag-row">
        <span v-for="tag in item.tags" :key="tag" class="tag-pill" :title="tag">{{ tag }}</span>
      </div>
      <Transition name="detail-block">
        <div v-if="detailsOpen" class="details-popover" @click.stop>
          <button
            v-if="!isCollection && item.content_type === 'web_url'"
            class="source source-url expandable-block"
            type="button"
            :title="sourceLabel"
            @click="emit('open', item)"
          >
            <IcIcon name="link" :size="13" />
            <span>{{ sourceLabel }}</span>
          </button>
          <div v-else-if="!isCollection" class="source expandable-block" :title="sourceLabel">
            <img v-if="fileIcon.src" class="source-icon" :src="fileIcon.src" alt="" />
            <span>{{ sourceLabel }}</span>
          </div>
          <textarea
            v-if="descriptionEditing"
            ref="descriptionInput"
            v-model="editDescription"
            class="description-edit-input expandable-block"
            aria-label="编辑描述"
            rows="2"
            @blur="saveDescription"
            @keydown.ctrl.enter.prevent="saveDescription"
            @keydown.escape.prevent="descriptionEditing = false; editDescription = item.description"
          ></textarea>
          <div v-else class="description expandable-block" :title="item.description" @dblclick.stop="startDescriptionEdit">
            {{ item.description || '无描述' }}
          </div>
        </div>
      </Transition>
      <div class="foot">
        <span v-if="!item.source_exists" class="missing-label">缺失</span>
        <span>{{ dateLabel }}</span>
        <span>{{ statusText }}</span>
      </div>
    </section>
  </article>
</template>

<style scoped>
.library-card {
  position: relative;
  display: inline-flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  min-width: 0;
  margin-bottom: 16px;
  overflow: visible;
  border: 0;
  background: transparent;
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
  break-inside: avoid;
  page-break-inside: avoid;
  vertical-align: top;
}

.library-card.details-open {
  z-index: 20;
}

.library-card.selected .cover {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.library-card.drag-over .cover {
  outline: 2px dashed var(--color-primary);
  outline-offset: 4px;
}

.library-card.missing .cover {
  outline: 2px solid color-mix(in srgb, var(--color-danger) 72%, transparent);
}

.select-button {
  position: absolute;
  top: 10px;
  right: 70px;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text-muted);
  box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.18);
  cursor: pointer;
}

.library-favorite {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 4;
  background: transparent;
}

.library-privacy {
  position: absolute;
  top: 10px;
  right: 40px;
  z-index: 4;
  background: transparent;
}

.privacy-cover {
  color: var(--color-text-muted);
}

.select-button :deep(svg) {
  margin-left: -1px;
}

.select-button.checked {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
}

.cover {
  position: relative;
  aspect-ratio: 2 / 3;
  min-height: 0;
  overflow: hidden;
  border: 0;
  border-radius: 18px;
  background: var(--color-surface-raised);
  box-shadow: 0 0 0 4px var(--workspace-panel-ring);
  transition: background 160ms ease, box-shadow 160ms ease;
}

.cover.image-cover {
  aspect-ratio: auto;
  display: grid;
  place-items: center;
}

.library-card:hover .cover,
.library-card.selected .cover {
  background: var(--color-surface-raised);
}

.library-card:hover .cover {
  box-shadow: 0 0 0 4px var(--color-primary-soft);
}

.cover-image {
  width: 100%;
  height: auto;
  max-height: 520px;
  object-fit: contain;
  display: block;
}

.text-cover,
.title-cover,
.icon-cover {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
}

.text-cover {
  padding: 18px;
  color: var(--color-text);
  line-height: 1.55;
  overflow: hidden;
  white-space: pre-wrap;
}

.title-cover {
  padding: 22px;
  color: var(--color-text);
  font-size: calc(22px * var(--font-scale));
  line-height: 1.25;
  font-weight: 700;
  text-align: center;
  overflow-wrap: anywhere;
}

.icon-cover {
  color: var(--color-text-muted);
}

.file-icon {
  width: 64px;
  height: 64px;
  object-fit: contain;
}

.meta {
  position: relative;
  display: grid;
  grid-template-rows: auto;
  min-height: 0;
  padding: 0 2px;
  gap: 6px;
  background: transparent;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-width: 0;
  min-height: 24px;
  overflow: hidden;
}

.title-row {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) 24px;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.expand-button {
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 0;
}

.expand-button:hover,
.expand-button.open {
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--color-primary);
}

.download-button {
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.download-button:hover {
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--color-primary);
}

.tag-pill {
  display: inline-flex;
  align-items: center;
  max-width: 118px;
  min-height: 22px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-tag-1) var(--tag-color-library-strength), transparent);
  color: var(--color-tag-pill-text);
  padding: 0 8px;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-pill:nth-child(6n + 2) {
  background: color-mix(in srgb, var(--color-tag-2) var(--tag-color-library-strength), transparent);
  color: var(--color-tag-pill-text);
}

.tag-pill:nth-child(6n + 3) {
  background: color-mix(in srgb, var(--color-tag-3) var(--tag-color-library-strength), transparent);
  color: var(--color-tag-pill-text);
}
.tag-pill:nth-child(6n + 4) { background: color-mix(in srgb, var(--color-tag-4) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); }
.tag-pill:nth-child(6n + 5) { background: color-mix(in srgb, var(--color-tag-5) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); }
.tag-pill:nth-child(6n) { background: color-mix(in srgb, var(--color-tag-6) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); }

@container (max-width: 640px) {
  .library-card {
    gap: var(--space-6);
    margin-bottom: var(--space-10);
  }

  .cover {
    border-radius: 14px;
  }

  .title-cover {
    padding: var(--space-16);
    font-size: calc(18px * var(--font-scale));
  }

  .meta {
    gap: var(--space-4);
  }
}

.title,
.source,
.description,
.foot {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.title,
.source,
.foot {
  white-space: nowrap;
}

.title {
  font-weight: 700;
  color: var(--color-text);
}

.title-edit-input {
  min-width: 0;
  width: 100%;
  height: 24px;
  border: 1px solid var(--color-primary);
  border-radius: 5px;
  outline: 0;
  background: var(--color-canvas);
  color: var(--color-text);
  padding: 0 6px;
  font: inherit;
  font-weight: 700;
}

.source {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--color-text-secondary);
}

.source-url {
  width: 100%;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.source-url:hover {
  color: var(--color-primary);
}

.expandable-block {
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--color-border) 70%, transparent);
  padding: 6px 8px;
}

.source.expandable-block {
  border-radius: 999px;
}

.description.expandable-block {
  border-radius: 18px;
}

.details-popover {
  position: absolute;
  top: calc(100% + 6px);
  left: 2px;
  right: 2px;
  z-index: 10;
  display: grid;
  gap: 6px;
  max-height: 240px;
  overflow-x: hidden;
  overflow-y: auto;
  border-radius: 18px;
  background: color-mix(in srgb, var(--color-canvas) 92%, transparent);
  box-shadow: 0 14px 30px rgba(0, 0, 0, 0.18);
  padding: 6px;
}

.source-icon {
  width: 14px;
  height: 14px;
  object-fit: contain;
  flex: 0 0 auto;
}

.description {
  color: var(--color-text-muted);
  line-height: 1.4;
  white-space: pre-wrap;
}

.description-edit-input {
  width: 100%;
  min-height: 48px;
  resize: vertical;
  outline: 0;
  color: var(--color-text);
  font: inherit;
  line-height: 1.4;
}

.detail-block-enter-active,
.detail-block-leave-active {
  max-height: 240px;
  opacity: 1;
  transform: translateY(0);
  transition:
    max-height 220ms ease,
    opacity 180ms ease,
    transform 220ms ease,
    padding 220ms ease,
    border-width 220ms ease;
}

.detail-block-enter-from,
.detail-block-leave-to {
  max-height: 0;
  opacity: 0;
  transform: translateY(-4px);
  border-width: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.foot {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: calc(11px * var(--font-scale));
  color: var(--color-text-muted);
}

.missing-label {
  color: var(--color-danger);
  font-weight: 700;
}
</style>
