<!--
  Shared native card for one four-library search result.

  Usage:
  SearchPage and Agent-mounted results both use this component so file, book,
  component, and literature blocks retain the exact same native presentation.
-->
<script setup lang="ts">
import type { LiteratureEntry } from '@/api/literatureReading'
import ComponentLibraryCard from '@/components/component_library/ComponentLibraryCard.vue'
import LibraryCard from '@/components/library_view/LibraryCard.vue'
import LiteratureEntryCard from '@/components/literature_reading/LiteratureEntryCard.vue'
import SearchFileMediumTile from '@/components/search_page/SearchFileMediumTile.vue'
import type { ComponentLibraryItem } from '@/types/componentLibrary'
import type { KnowledgeFileNode, LibraryItem } from '@/types/knowledge'
import type { UnifiedSearchResult } from '@/types/unifiedSearch'

defineOptions({ name: 'SearchNativeResultCard' })

defineProps<{
  result: UnifiedSearchResult
  selected?: boolean
}>()

const emit = defineEmits<{
  activate: [result: UnifiedSearchResult]
  open: [result: UnifiedSearchResult]
}>()
</script>

<template>
  <SearchFileMediumTile
    v-if="result.source === 'files'"
    :node="result.item as unknown as KnowledgeFileNode"
    :selected="selected"
    @preview="emit('activate', result)"
    @open="emit('open', result)"
  />
  <LibraryCard
    v-else-if="result.source === 'library'"
    :item="result.item as unknown as LibraryItem"
    :library-id="result.library_id"
    :selected="false"
    :multi-select="false"
    readonly
    @select="emit('activate', result)"
    @open="emit('activate', result)"
    @edit="emit('activate', result)"
    @download="emit('activate', result)"
  />
  <ComponentLibraryCard
    v-else-if="result.source === 'components'"
    :item="result.item as unknown as ComponentLibraryItem"
    :library-id="result.library_id"
    readonly
    @open="emit('activate', result)"
  />
  <LiteratureEntryCard
    v-else
    :entry="result.item as unknown as LiteratureEntry"
    :form="null"
    :row="null"
    :selected="false"
    :renaming="false"
    :pending-column-ids="[]"
    :expandable="false"
    @select="emit('activate', result)"
  />
</template>
