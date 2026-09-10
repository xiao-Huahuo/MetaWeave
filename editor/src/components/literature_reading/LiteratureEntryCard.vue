<!--
  Expandable literature reading card.

  Usage:
  LiteratureReadingView supplies a smart-form row summary and lazily loaded
  form detail. The collapsed card follows RecentFileList while expansion shows
  every persisted column through LiteratureFieldBlock.
-->
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import FormHeightTransition from '@/components/common/FormHeightTransition.vue'
import IcIcon from '@/components/common/IcIcon.vue'
import RecentFileThumbnail from '@/components/editor_workspace/RecentFileThumbnail.vue'
import LiteratureFieldBlock from '@/components/literature_reading/LiteratureFieldBlock.vue'
import type { LiteratureEntry } from '@/api/literatureReading'
import type { SmartLiteratureForm, SmartRow } from '@/components/smart_forms/smartLiteratureTable'
import type { KnowledgeFileNode } from '@/types/knowledge'

const props = withDefaults(defineProps<{
  entry: LiteratureEntry
  form: SmartLiteratureForm | null
  row: SmartRow | null
  selected: boolean
  renaming: boolean
  pendingColumnIds: string[]
  defaultExpanded?: boolean
  expandable?: boolean
}>(), {
  defaultExpanded: false,
  expandable: true,
})

const emit = defineEmits<{
  select: []
  expand: []
  contextMenu: [event: MouseEvent]
  fieldContextMenu: [columnId: string, event: MouseEvent]
  updateCell: [columnId: string, value: string]
  download: []
  rename: [title: string]
  fillField: [columnId: string]
}>()

const expanded = ref(props.expandable && props.defaultExpanded)
const renameDraft = ref('')
const renameInput = ref<HTMLInputElement | null>(null)
const node = computed<KnowledgeFileNode>(() => ({
  name: props.entry.file_name,
  path: props.entry.asset_path,
  isDir: false,
  mtime: props.entry.updated_at,
  size: props.entry.file_size,
  indexStatus: 'indexed',
}))
const visibleColumns = computed(() => props.form?.columns.filter((column) => column.type !== 'index') ?? [])

/** Expands the row after requesting its full table detail from the page. */
function toggleExpanded(): void {
  if (!props.expandable) return
  expanded.value = !expanded.value
  if (expanded.value) emit('expand')
}

/** Starts title editing with the current smart title. */
function focusRename(): void {
  renameDraft.value = props.entry.title
  void nextTick(() => renameInput.value?.focus())
}

/** Commits an in-place literature title edit. */
function commitRename(): void {
  const title = renameDraft.value.trim()
  if (title && title !== props.entry.title) emit('rename', title)
}

watch(() => props.renaming, (renaming) => {
  if (renaming) focusRename()
})
watch(() => props.defaultExpanded, (value) => {
  expanded.value = props.expandable && value
})
watch(() => props.expandable, (value) => {
  if (!value) expanded.value = false
})
</script>

<template>
  <article class="literature-card" :class="{ selected, expanded }" @click="emit('select')" @contextmenu.prevent.stop="emit('contextMenu', $event)">
    <div class="card-summary">
      <RecentFileThumbnail :node="node" />
      <div class="summary-copy">
        <input
          v-if="renaming"
          ref="renameInput"
          v-model="renameDraft"
          class="rename-input"
          @click.stop
          @blur="commitRename"
          @keydown.enter.prevent="commitRename"
        />
        <strong v-else :title="entry.title">{{ entry.title }}</strong>
        <span :title="entry.file_name">{{ entry.file_name }}</span>
        <p>{{ entry.content_excerpt || '暂无文献内容' }}</p>
      </div>
      <button v-if="expandable" class="expand-button v1-icon-button" type="button" :title="expanded ? '收起字段' : '展开全部字段'" :aria-label="expanded ? '收起字段' : '展开全部字段'" @click.stop="toggleExpanded">
        <IcIcon :name="expanded ? 'chevron-down' : 'chevron-right'" :size="15" morph />
      </button>
      <time :datetime="entry.entered_at">{{ new Date(entry.entered_at).toLocaleString([], { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }}</time>
    </div>
    <FormHeightTransition :watch-key="expanded ? 'expanded' : 'collapsed'">
      <div v-if="expandable && expanded" class="field-list" @click.stop>
        <LiteratureFieldBlock
          v-for="column in visibleColumns"
          :key="column.id"
          :column="column"
          :cell="row?.cells[column.id] ?? { value: '' }"
          :markdown-path="entry.asset_path"
          :pending="pendingColumnIds.includes(column.id)"
          @update="emit('updateCell', column.id, $event)"
          @download="emit('download')"
          @smart-fill="emit('fillField', column.id)"
          @context-menu="emit('fieldContextMenu', column.id, $event)"
        />
      </div>
    </FormHeightTransition>
  </article>
</template>

<style scoped>
.literature-card {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 18px;
  background: var(--color-surface);
  color: var(--color-text);
  transition: border-color 180ms ease, background-color 180ms ease, box-shadow 180ms ease;
}

.literature-card:hover {
  border-color: color-mix(in srgb, var(--color-primary) 42%, var(--color-border));
  background: var(--color-surface-raised);
}

.literature-card.selected {
  border-color: var(--color-primary);
  outline: 2px solid var(--color-primary);
  outline-offset: -2px;
}

.card-summary {
  display: grid;
  grid-template-columns: 104px minmax(0, 1fr) 28px;
  grid-template-rows: minmax(88px, auto) auto;
  gap: 0 8px;
  min-height: 117px;
  padding: 6px;
  cursor: pointer;
}

.card-summary :deep(.recent-file-thumbnail) {
  grid-row: 1 / 3;
  width: 104px;
  height: 104px;
  border-radius: 18px;
  background: var(--color-surface-raised);
}

.summary-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  padding: 6px 2px;
}

.summary-copy strong,
.summary-copy span,
.summary-copy p {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.summary-copy strong {
  font-size: calc(13px * var(--font-scale));
}

.summary-copy span {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.summary-copy p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: calc(11px * var(--font-scale));
}

.expand-button {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-muted);
  transition: color 160ms ease, background 160ms ease, transform 220ms cubic-bezier(.23,1,.32,1);
}

.expand-button:hover { background: color-mix(in srgb, var(--color-primary) 10%, transparent); color: var(--color-primary); }
.literature-card.expanded .expand-button { transform: rotate(0deg); color: var(--color-primary); }

.card-summary time {
  grid-column: 2 / 4;
  align-self: end;
  padding: 0 2px 3px;
  color: var(--color-text-muted);
  font-size: calc(10px * var(--font-scale));
}

.rename-input {
  width: 100%;
  height: 25px;
  border: 0;
  border-bottom: 1px solid var(--color-primary);
  outline: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
}

.field-list {
  display: grid;
  gap: 8px;
  padding: 8px 9px 10px;
  border-top: 1px solid color-mix(in srgb, var(--color-border) 64%, transparent);
  animation: literature-fields-enter 220ms cubic-bezier(.23,1,.32,1) both;
}

@keyframes literature-fields-enter { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }

@media (max-width: 640px) {
  .literature-card { border-radius: 14px; }
  .card-summary { grid-template-columns: 76px minmax(0, 1fr) 28px; grid-template-rows: minmax(68px, auto) auto; min-height: 92px; padding: 4px; }
  .card-summary :deep(.recent-file-thumbnail) { width: 76px; height: 84px; border-radius: 11px; }
  .summary-copy { padding-block: 3px; }
}
</style>
