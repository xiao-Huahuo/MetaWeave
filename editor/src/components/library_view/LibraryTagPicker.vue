<!--
  Reusable library tag picker.

  Usage:
  Binds selected tags with v-model and offers existing tags through the shared
  dropdown menu. New text can still be committed with Enter.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
defineOptions({ name: 'LibraryTagPicker' })

const props = withDefaults(defineProps<{
  availableTags: string[]
  single?: boolean
  allowCustom?: boolean
  placeholder?: string
  dropdownAlignOffset?: number
  dropdownZIndex?: number
}>(), {
  single: false,
  allowCustom: true,
  placeholder: '输入标签后回车',
  dropdownAlignOffset: 0,
  dropdownZIndex: 100,
})
const tags = defineModel<string[]>({ required: true })
const draft = ref('')
const expanded = ref(false)
const injectedTags = ref(new Set<string>())
const candidates = computed(() => props.availableTags.filter((name) => !tags.value.includes(name)))
const originalTags = computed(() => tags.value.filter((tag) => !injectedTags.value.has(tag)))
const injectedTagList = computed(() => tags.value.filter((tag) => injectedTags.value.has(tag)))

function addTag(raw = draft.value, injected = false) {
  const name = raw.trim()
  if (name && !tags.value.some((tag) => tag.toLowerCase() === name.toLowerCase())) {
    tags.value = props.single ? [name] : [...tags.value, name]
    if (injected) injectedTags.value = new Set([...injectedTags.value, name])
  }
  draft.value = ''
}

function removeTag(name: string) {
  tags.value = tags.value.filter((tag) => tag !== name)
  const nextInjectedTags = new Set(injectedTags.value)
  nextInjectedTags.delete(name)
  injectedTags.value = nextInjectedTags
}

/** Select one candidate and keep only multi-select menus open for further picks. */
function selectCandidate(name: string, event: Event) {
  addTag(name, true)
  if (props.single) {
    expanded.value = false
  } else {
    event.preventDefault()
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (!props.allowCustom) return
  if (event.key !== 'Enter' && event.key !== ',') return
  event.preventDefault()
  addTag()
}
</script>

<template>
  <DropdownMenu v-model:open="expanded">
    <div class="library-tag-picker">
      <div class="tag-input-wrap form-input-surface">
        <input
          v-model="draft"
          type="text"
          spellcheck="false"
          :readonly="!allowCustom"
          :placeholder="placeholder"
          @click="!allowCustom && (expanded = true)"
          @keydown="handleKeydown"
        />
        <DropdownMenuTrigger as-child>
          <button type="button" :aria-expanded="expanded" title="选择已有标签">
            <IcIcon name="chevron-down" :size="15" />
          </button>
        </DropdownMenuTrigger>
      </div>
      <DropdownMenuPortal>
        <DropdownMenuContent
          align="end"
          :align-offset="dropdownAlignOffset"
          :style="{ zIndex: dropdownZIndex }"
        >
          <DropdownMenuItem v-for="tag in candidates" :key="tag" @select="selectCandidate(tag, $event)">
            <IcIcon name="label" :size="14" />
            <span>{{ tag }}</span>
          </DropdownMenuItem>
          <DropdownMenuLabel v-if="!candidates.length">没有可添加的标签</DropdownMenuLabel>
        </DropdownMenuContent>
      </DropdownMenuPortal>
      <div v-if="tags.length" class="tag-list">
        <div v-if="originalTags.length" class="tag-group">
          <button v-for="tag in originalTags" :key="tag" class="tag-pill selected" type="button" :title="`移除 ${tag}`" @click="removeTag(tag)">
            <span>{{ tag }}</span><IcIcon name="cancel" :size="13" />
          </button>
        </div>
        <div v-if="originalTags.length && injectedTagList.length" class="tag-divider"></div>
        <div v-if="injectedTagList.length" class="tag-group">
          <button v-for="tag in injectedTagList" :key="tag" class="tag-pill selected" type="button" :title="`移除 ${tag}`" @click="removeTag(tag)">
            <span>{{ tag }}</span><IcIcon name="cancel" :size="13" />
          </button>
        </div>
      </div>
    </div>
  </DropdownMenu>
</template>

<style scoped>
.library-tag-picker { display: grid; grid-template-columns: minmax(0, 1fr); min-width: 0; gap: 6px; }
.tag-input-wrap { display: flex; align-items: center; min-width: 0; min-height: 36px; border: 1px solid var(--color-border); border-radius: 999px; background: var(--color-canvas); padding-left: 14px; }
.tag-input-wrap input { flex: 1; min-width: 0; height: 34px; border: 0; outline: 0; background: transparent; color: var(--color-text); font-size: calc(13px * var(--font-scale)); }
.tag-input-wrap button { display: grid; place-items: center; width: 34px; height: 34px; border: 0; border-radius: 50%; background: transparent; color: var(--color-text-muted); cursor: pointer; transition: transform var(--transition-fast); }
.tag-input-wrap button[aria-expanded="true"] { color: var(--color-primary); transform: rotate(180deg); }
.tag-list { display: grid; gap: 10px; }
.tag-group { display: flex; flex-wrap: wrap; gap: 6px; }
.tag-pill { display: inline-flex; align-items: center; gap: 5px; max-width: 160px; min-height: 24px; border: 0; border-radius: 999px; background: color-mix(in srgb, var(--color-tag-1) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); padding: 0 9px; font-size: calc(12px * var(--font-scale)); cursor: pointer; }
.tag-pill:nth-child(6n + 2) { background: color-mix(in srgb, var(--color-tag-2) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); }
.tag-pill:nth-child(6n + 3) { background: color-mix(in srgb, var(--color-tag-3) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); }
.tag-pill:nth-child(6n + 4) { background: color-mix(in srgb, var(--color-tag-4) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); }
.tag-pill:nth-child(6n + 5) { background: color-mix(in srgb, var(--color-tag-5) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); }
.tag-pill:nth-child(6n) { background: color-mix(in srgb, var(--color-tag-6) var(--tag-color-library-strength), transparent); color: var(--color-tag-pill-text); }
.tag-pill span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag-divider { height: 1px; background: var(--color-border-strong); margin: 6px 0; }
</style>
