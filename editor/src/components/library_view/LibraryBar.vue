<!--
  Virtual library bar (compact row) view.

  Usage:
  Render one book or collection as a horizontal bar in the library list.
  Left thumb shows the cover image or a text key; right column stacks
  title + tags, description, then date + child count. Same interaction
  surface (selection, drag, context menu) as LibraryCard.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'

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
}>()

const emit = defineEmits<{
  open: [item: LibraryItem]
  edit: [item: LibraryItem]
  toggle: [item: LibraryItem]
  select: [item: LibraryItem]
  contextmenu: [event: MouseEvent, item: LibraryItem]
  download: [item: LibraryItem]
  dragStart: [item: LibraryItem]
  dropOn: [item: LibraryItem]
}>()

const dragOver = ref(false)
const privacyStore = usePrivacyStore()
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
const dateLabel = computed(() => {
  const raw = props.item.source_mtime || props.item.updated_at
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw.slice(0, 16)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
})
const badgeText = computed(() => {
  if (isCollection.value) return '集锦'
  if (props.item.content_type === 'web_url') return props.item.source_url
  return props.item.source_name || props.item.source_path || props.item.display_title
})

function handleClick() {
  if (props.multiSelect) {
    emit('toggle', props.item)
    return
  }
  emit('select', props.item)
}

function handleDragStart(event: DragEvent) {
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
    class="library-bar"
    :class="{ selected, missing: !item.source_exists, 'drag-over': dragOver, collection: isCollection }"
    draggable="true"
    @click="handleClick"
    @dblclick.stop="isCollection ? emit('open', item) : emit('edit', item)"
    @contextmenu.prevent="emit('contextmenu', $event, item)"
    @dragstart="handleDragStart"
    @dragover="handleDragOver"
    @dragleave="dragOver = false"
    @drop="handleDrop"
  >
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
    <section class="thumb">
      <div v-if="isPrivate" class="thumb-icon" aria-label="隐私内容不显示封面">
        <IcIcon name="visibility-off" :size="26" />
      </div>
      <img v-else-if="coverUrl" class="thumb-image" :src="coverUrl" alt="" />
      <div v-else-if="item.cover_mode === 'description' && item.description" class="thumb-text">
        {{ item.description }}
      </div>
      <div v-else-if="item.cover_mode === 'title' || isCollection" class="thumb-title">
        {{ item.display_title }}
      </div>
      <div v-else class="thumb-icon">
        <IcIcon v-if="isCollection" name="folder-open" :size="26" />
        <IcIcon v-else-if="item.content_type === 'web_url'" name="link" :size="26" />
        <img v-else-if="fileIcon.src" class="thumb-file-icon" :src="fileIcon.src" alt="" />
        <IcIcon v-else name="image" :size="26" />
      </div>
      <IcIcon v-if="!item.source_exists" name="warning" class="missing-icon" :size="14" />
    </section>
    <section class="bar-meta">
      <div class="bar-title-row">
        <PrivacyButton class="bar-privacy" target-type="library_item" :target-id="item.item_id" />
        <FavoriteButton class="bar-favorite" target-type="library_item" :target-id="item.item_id" />
        <span class="bar-type-icon">
          <IcIcon v-if="isCollection" name="folder-open" :size="16" />
          <IcIcon v-else-if="item.content_type === 'web_url'" name="link" :size="16" />
          <img v-else-if="fileIcon.src" class="bar-type-file-icon" :src="fileIcon.src" alt="" />
          <IcIcon v-else name="image" :size="16" />
        </span>
        <span class="bar-title" :title="item.display_title">{{ item.display_title }}</span>
      </div>
      <div class="bar-source-row">
        <button
          v-if="!multiSelect && item.content_type === 'web_url'"
          class="bar-badge bar-url"
          type="button"
          :title="badgeText"
          @click.stop="emit('open', item)"
        >{{ badgeText }}</button>
        <span
          v-else-if="!multiSelect"
          class="bar-badge"
          :class="{ collection: isCollection }"
          :title="badgeText"
        >{{ badgeText }}</span>
      </div>
      <div class="bar-tag-row">
        <span v-for="tag in item.tags" :key="tag" class="tag-pill" :title="tag">{{ tag }}</span>
      </div>
      <div class="bar-description" :title="item.description">{{ item.description || '无描述' }}</div>
      <div class="bar-foot">
        <span>{{ dateLabel }}</span>
        <div class="bar-foot-actions">
          <span v-if="isCollection" class="bar-count">{{ item.child_count }} 项</span>
          <button
            v-else
            class="bar-download-button"
            type="button"
            title="下载真实文件"
            aria-label="下载真实文件"
            @click.stop="emit('download', item)"
          >
            <IcIcon name="download" :size="14" />
          </button>
        </div>
      </div>
    </section>
  </article>
</template>

<style scoped>
.library-bar {
  position: relative;
  display: flex;
  align-items: stretch;
  min-width: 0;
  min-height: 117.333px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 18px;
  background: var(--color-surface);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
  transition:
    border-color 160ms ease,
    background 160ms ease;
}

.library-bar:hover,
.library-bar.selected {
  background: var(--color-surface-raised);
  border-color: color-mix(in srgb, var(--color-primary) 42%, var(--color-border));
}

.library-bar.selected {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.library-bar.drag-over {
  outline: 2px dashed var(--color-primary);
  outline-offset: 4px;
}

.library-bar.missing {
  outline: 2px solid color-mix(in srgb, var(--color-danger) 72%, transparent);
}

.select-button {
  position: absolute;
  top: 8px;
  right: 8px;
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

.select-button :deep(svg) {
  margin-left: -1px;
}

.select-button.checked {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
}

.thumb {
  position: relative;
  flex: 0 0 104px;
  min-width: 0;
  margin: 6px 0 6px 6px;
  overflow: hidden;
  border-radius: 18px;
  background: var(--color-surface-raised);
}

.thumb-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.thumb-text,
.thumb-title,
.thumb-icon {
  display: grid;
  place-items: center;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.thumb-text {
  padding: 10px;
  color: var(--color-text);
  font-size: calc(10px * var(--font-scale));
  line-height: 1.45;
  text-align: center;
  white-space: pre-wrap;
}

.thumb-title {
  padding: 12px;
  color: var(--color-text);
  font-size: calc(14px * var(--font-scale));
  line-height: 1.25;
  font-weight: 700;
  text-align: center;
  overflow-wrap: anywhere;
}

.thumb-icon {
  color: var(--color-text-muted);
}

.thumb-file-icon {
  width: 40px;
  height: 40px;
  object-fit: contain;
}

.missing-icon {
  position: absolute;
  right: 6px;
  bottom: 6px;
  color: var(--color-danger);
}

.bar-meta {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  flex: 1 1 auto;
  padding: 10px 12px;
}

.bar-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.bar-favorite {
  margin-left: -4px;
}

.bar-privacy {
  margin-left: -4px;
}

.bar-title {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 45%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 700;
  color: var(--color-text);
}

.bar-source-row {
  display: flex;
  align-items: center;
  min-width: 0;
}

.bar-type-icon {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  color: var(--color-text-tertiary);
}

.bar-type-file-icon {
  width: 16px;
  height: 16px;
  object-fit: contain;
}

.bar-tag-row {
  display: flex;
  flex-wrap: nowrap;
  gap: 5px;
  min-width: 0;
  overflow: hidden;
}

.tag-pill {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  max-width: 120px;
  min-height: 20px;
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

.bar-badge {
  flex: 0 0 auto;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: calc(11px * var(--font-scale));
  color: var(--color-text-tertiary);
}

.bar-url {
  padding: 0;
  border: 0;
  background: transparent;
  font-family: inherit;
  cursor: pointer;
}

.bar-url:hover {
  color: var(--color-primary);
}

.bar-badge.collection {
  color: var(--color-primary);
  font-weight: 600;
}

.bar-description {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-muted);
}

.bar-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  font-size: calc(11px * var(--font-scale));
  color: var(--color-text-muted);
}

.bar-count {
  flex: 0 0 auto;
  color: var(--color-primary);
  font-weight: 600;
}

.bar-foot-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.bar-download-button {
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  margin: -3px -3px -3px 0;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.bar-download-button:hover {
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  color: var(--color-primary);
}

@container (max-width: 640px) {
  .library-bar {
    min-height: 92px;
    border-radius: 14px;
  }

  .thumb {
    flex-basis: 76px;
    margin: 4px 0 4px 4px;
    border-radius: 11px;
  }

  .bar-meta {
    gap: 3px;
    padding: var(--space-8);
  }

  .bar-title {
    flex: 1 1 auto;
    max-width: none;
  }

  .bar-description {
    display: none;
  }

  .bar-tag-row {
    min-height: 20px;
  }
}
</style>
