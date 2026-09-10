<!--
  Appearance settings section.

  Usage:
  Edits theme mode and global font stacks. The parent owns persistence.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import LibraryCoverUploader from '@/components/library_view/LibraryCoverUploader.vue'
import type { LibraryAsset } from '@/types/knowledge'
import type { SidebarDisplayMode, ThemeMode } from '@/types/settings'

const uiFontFamiliesDraft = defineModel<string[]>('uiFontFamiliesDraft', { required: true })
const textFontFamiliesDraft = defineModel<string[]>('textFontFamiliesDraft', { required: true })
const uiFontSizePercentDraft = defineModel<number>('uiFontSizePercentDraft', { required: true })
const textFontSizePercentDraft = defineModel<number>('textFontSizePercentDraft', { required: true })
const themePrimaryColorDraft = defineModel<string>('themePrimaryColorDraft', { required: true })
const themeSoftColorDraft = defineModel<string>('themeSoftColorDraft', { required: true })
const tagColorsDraft = defineModel<string[]>('tagColorsDraft', { required: true })
const tagColorsTranslucentDraft = defineModel<boolean>('tagColorsTranslucentDraft', { required: true })

const props = defineProps<{
  themeOptions: Array<{ value: ThemeMode; label: string }>
  themeMode: ThemeMode
  sidebarDisplayMode: SidebarDisplayMode
  availableFontFamilies: string[]
  fontsLoading: boolean
  showBacklinks: boolean
  userId: string
  backgroundCoverUrl: string
}>()

const emit = defineEmits<{
  setThemeMode: [mode: ThemeMode]
  saveFontFamilies: [payload: { target: 'ui' | 'text'; families: string[] }]
  saveFontSize: [payload: { target: 'ui' | 'text'; percent: number }]
  previewThemeColors: []
  previewTagColors: []
  saveThemeColors: []
  saveTagColors: []
  resetThemeColors: []
  resetTagColors: []
  setSidebarDisplayMode: [mode: SidebarDisplayMode]
  setShowBacklinks: [value: boolean]
  setBackgroundCover: [url: string]
  resetBackgroundCover: []
}>()

const activeFontPicker = ref<'ui' | 'text' | null>(null)
const uiFontQuery = ref('')
const textFontQuery = ref('')
const sidebarSwitchRef = ref<HTMLElement | null>(null)
const sidebarSliderStyle = ref({ width: '0px', left: '0px' })

function normalizeFontFamily(value: string): string {
  return value.replace(/[;{}]/g, '').trim()
}

function normalizeThemeColor(value: string): string {
  const color = value.trim()
  if (/^#[0-9a-fA-F]{6}$/u.test(color)) return color.toLowerCase()
  return ''
}

function handleThemeColorTextInput(target: 'primary' | 'soft', value: string) {
  const normalized = normalizeThemeColor(value)
  if (!normalized) return
  if (target === 'primary') {
    themePrimaryColorDraft.value = normalized
  } else {
    themeSoftColorDraft.value = normalized
  }
  emit('previewThemeColors')
}

function handleThemeColorPickerInput(target: 'primary' | 'soft', value: string) {
  if (target === 'primary') {
    themePrimaryColorDraft.value = value
  } else {
    themeSoftColorDraft.value = value
  }
  emit('previewThemeColors')
}

function handleTagColorInput(index: number, value: string) {
  const normalized = normalizeThemeColor(value)
  if (!normalized) return
  const nextColors = [...tagColorsDraft.value]
  nextColors[index] = normalized
  tagColorsDraft.value = nextColors
  emit('previewTagColors')
}

function handleTagTranslucencyInput(value: boolean) {
  tagColorsTranslucentDraft.value = value
  emit('previewTagColors')
}

function activeFamilies(target: 'ui' | 'text'): string[] {
  return target === 'ui' ? uiFontFamiliesDraft.value : textFontFamiliesDraft.value
}

function activeQuery(target: 'ui' | 'text'): string {
  return target === 'ui' ? uiFontQuery.value : textFontQuery.value
}

function setActiveQuery(target: 'ui' | 'text', value: string) {
  if (target === 'ui') {
    uiFontQuery.value = value
  } else {
    textFontQuery.value = value
  }
}

function filteredFontOptions(target: 'ui' | 'text'): string[] {
  const selected = new Set(activeFamilies(target).map((item) => item.toLowerCase()))
  const query = activeQuery(target).toLowerCase()
  return props.availableFontFamilies
    .filter((family) => !selected.has(family.toLowerCase()))
    .filter((family) => !query || family.toLowerCase().includes(query))
    .slice(0, 80)
}

const uiFontOptions = computed(() => filteredFontOptions('ui'))
const textFontOptions = computed(() => filteredFontOptions('text'))

function normalizeFontSizePercent(value: number | string): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 100
  return Math.max(50, Math.min(150, Math.round(parsed)))
}

function saveFamilies(target: 'ui' | 'text', families: string[]) {
  emit('saveFontFamilies', { target, families })
}

function updateFontSize(target: 'ui' | 'text', value: number | string) {
  const normalized = normalizeFontSizePercent(value)
  if (target === 'ui') {
    uiFontSizePercentDraft.value = normalized
  } else {
    textFontSizePercentDraft.value = normalized
  }
  emit('saveFontSize', { target, percent: normalized })
}

function saveFontSize(target: 'ui' | 'text') {
  const draft = target === 'ui' ? uiFontSizePercentDraft : textFontSizePercentDraft
  const normalized = normalizeFontSizePercent(draft.value)
  draft.value = normalized
  emit('saveFontSize', { target, percent: normalized })
}

function addFontFamily(target: 'ui' | 'text', family: string) {
  const normalized = normalizeFontFamily(family)
  if (!normalized) return
  const current = activeFamilies(target)
  if (current.some((item) => item.toLowerCase() === normalized.toLowerCase())) {
    activeFontPicker.value = null
    return
  }
  saveFamilies(target, [...current, normalized])
  setActiveQuery(target, '')
  activeFontPicker.value = null
}

function removeFontFamily(target: 'ui' | 'text', family: string) {
  saveFamilies(target, activeFamilies(target).filter((item) => item !== family))
}

function handleFontInputKeydown(event: KeyboardEvent, target: 'ui' | 'text') {
  if (event.key !== 'Enter') return
  event.preventDefault()
  addFontFamily(target, activeQuery(target))
}

function handleDocumentPointerDown(event: PointerEvent) {
  const target = event.target as HTMLElement | null
  if (!target?.closest('.font-family-control')) {
    activeFontPicker.value = null
  }
}

/** Forward the persistent asset URL to the appearance settings owner. */
function handleBackgroundUploaded(asset: LibraryAsset) {
  emit('setBackgroundCover', asset.url)
}

function updateSidebarSlider() {
  void nextTick(() => {
    const container = sidebarSwitchRef.value
    const active = container?.querySelector<HTMLElement>('.settings-resource-page-button.active')
    if (!active) return
    sidebarSliderStyle.value = {
      width: `${active.offsetWidth}px`,
      left: `${active.offsetLeft}px`,
    }
  })
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown)
  updateSidebarSlider()
})

watch(() => props.sidebarDisplayMode, updateSidebarSlider)

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown)
})
</script>

<template>
  <div class="setting-section">
    <h3>主题</h3>
    <div class="theme-row">
      <button
        v-for="option in themeOptions"
        :key="option.value"
        :class="['theme-'+option.value, { active: themeMode === option.value }]"
        type="button"
        @click="$emit('setThemeMode', option.value)"
      >
        {{ option.label }}
      </button>
    </div>

    <div class="color-control">
      <div class="color-control-header">
        <label>主主题色</label>
        <span>按钮、选中态和 header Agent 入口</span>
      </div>
      <div class="color-row">
        <input
          :value="themePrimaryColorDraft"
          class="color-picker"
          type="color"
          @input="handleThemeColorPickerInput('primary', ($event.target as HTMLInputElement).value)"
        />
        <input
          :value="themePrimaryColorDraft"
          class="color-text"
          spellcheck="false"
          @change="handleThemeColorTextInput('primary', ($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>

    <div class="color-control">
      <div class="color-control-header">
        <label>柔和主题色</label>
        <span>浅紫背景、hover 和弱选中态</span>
      </div>
      <div class="color-row">
        <input
          :value="themeSoftColorDraft"
          class="color-picker"
          type="color"
          @input="handleThemeColorPickerInput('soft', ($event.target as HTMLInputElement).value)"
        />
        <input
          :value="themeSoftColorDraft"
          class="color-text"
          spellcheck="false"
          @change="handleThemeColorTextInput('soft', ($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>

    <div class="model-actions appearance-actions">
      <button class="save-model-btn" type="button" @click="$emit('saveThemeColors')">保存主题色</button>
      <button class="cancel-model-btn" type="button" @click="$emit('resetThemeColors')">重置默认色</button>
    </div>

    <h3 style="margin-top: 20px">标签</h3>
    <div v-for="(color, index) in tagColorsDraft" :key="index" class="color-control">
      <div class="color-control-header">
        <label>标签色 {{ index + 1 }}</label>
      </div>
      <div class="color-row">
        <input
          :value="color"
          class="color-picker"
          type="color"
          :aria-label="`标签色 ${index + 1}`"
          @input="handleTagColorInput(index, ($event.target as HTMLInputElement).value)"
        />
        <input
          :value="color"
          class="color-text"
          spellcheck="false"
          :aria-label="`标签色 ${index + 1} 十六进制值`"
          @change="handleTagColorInput(index, ($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>

    <div class="page-display-control tag-translucency-control">
      <div class="page-display-header">
        <label for="tag-colors-translucent-setting">半透明效果</label>
      </div>
      <div class="toggle-row">
        <input
          id="tag-colors-translucent-setting"
          type="checkbox"
          :checked="tagColorsTranslucentDraft"
          @change="handleTagTranslucencyInput(($event.target as HTMLInputElement).checked)"
        />
      </div>
    </div>

    <div class="model-actions appearance-actions">
      <button class="save-model-btn" type="button" @click="$emit('saveTagColors')">保存标签色</button>
      <button class="cancel-model-btn" type="button" @click="$emit('resetTagColors')">重置标签色</button>
    </div>

    <div class="background-cover-control">
      <div class="background-cover-header">
        <label>背景封面图片</label>
      </div>
      <div class="background-cover-body">
        <LibraryCoverUploader
          :user-id="userId"
          :preview-url="backgroundCoverUrl"
          empty-label="点击或拖拽上传背景封面"
          @uploaded="handleBackgroundUploaded"
        />
        <button
          class="cancel-model-btn"
          type="button"
          aria-label="重置背景封面"
          :disabled="!backgroundCoverUrl"
          @click="emit('resetBackgroundCover')"
        >
          重置
        </button>
      </div>
    </div>

    <h3 style="margin-top: 20px">页面</h3>
    <div class="page-display-control">
      <div class="page-display-header">
        <label>侧边栏展示</label>
      </div>
      <div ref="sidebarSwitchRef" class="settings-resource-page-switch" role="group" aria-label="侧边栏展示">
        <span class="settings-resource-page-slider" :style="sidebarSliderStyle" aria-hidden="true"></span>
        <button
          class="settings-resource-page-button"
          type="button"
          :class="{ active: sidebarDisplayMode === 'icons' }"
          @click="$emit('setSidebarDisplayMode', 'icons')"
        >
          图标栏
        </button>
        <button
          class="settings-resource-page-button"
          type="button"
          :class="{ active: sidebarDisplayMode === 'management' }"
          @click="$emit('setSidebarDisplayMode', 'management')"
        >
          管理栏
        </button>
      </div>
    </div>

    <div class="page-display-control backlinks-display-control">
      <div class="page-display-header">
        <label for="show-backlinks-setting">显示反向链接</label>
      </div>
      <div class="toggle-row">
        <input
          id="show-backlinks-setting"
          type="checkbox"
          :checked="showBacklinks"
          @change="emit('setShowBacklinks', ($event.target as HTMLInputElement).checked)"
        />
      </div>
    </div>

    <h3 style="margin-top: 20px">字体</h3>
    <div class="font-family-control font-size-control" data-font-size="ui">
      <div class="font-family-header">
        <label>UI 字体大小</label>
        <span>{{ uiFontSizePercentDraft }}%</span>
      </div>
      <div class="font-size-row">
        <input
          :value="uiFontSizePercentDraft"
          aria-label="UI 字体大小"
          max="150"
          min="50"
          step="1"
          type="range"
          @change="saveFontSize('ui')"
          @input="updateFontSize('ui', ($event.target as HTMLInputElement).value)"
        />
        <input
          :value="uiFontSizePercentDraft"
          aria-label="UI 字体大小百分比"
          class="font-size-number"
          max="150"
          min="50"
          step="1"
          type="number"
          @blur="saveFontSize('ui')"
          @change="saveFontSize('ui')"
          @input="updateFontSize('ui', ($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>

    <div class="font-family-control font-size-control" data-font-size="text">
      <div class="font-family-header">
        <label>正文字体大小</label>
        <span>{{ textFontSizePercentDraft }}%</span>
      </div>
      <div class="font-size-row">
        <input
          :value="textFontSizePercentDraft"
          aria-label="正文字体大小"
          max="150"
          min="50"
          step="1"
          type="range"
          @change="saveFontSize('text')"
          @input="updateFontSize('text', ($event.target as HTMLInputElement).value)"
        />
        <input
          :value="textFontSizePercentDraft"
          aria-label="正文字体大小百分比"
          class="font-size-number"
          max="150"
          min="50"
          step="1"
          type="number"
          @blur="saveFontSize('text')"
          @change="saveFontSize('text')"
          @input="updateFontSize('text', ($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>

    <div class="font-family-control">
      <div class="font-family-header">
        <label>界面字体</label>
        <span>{{ uiFontFamiliesDraft.length ? `${uiFontFamiliesDraft.length} 个字体家族` : '使用默认字体栈' }}</span>
      </div>
      <div class="font-chip-row">
        <button
          v-for="family in uiFontFamiliesDraft"
          :key="family"
          class="font-chip"
          type="button"
          @click="removeFontFamily('ui', family)"
        >
          {{ family }} x
        </button>
        <button class="font-add-button" type="button" @click.stop="activeFontPicker = activeFontPicker === 'ui' ? null : 'ui'">
          添加字体
        </button>
      </div>
      <div v-if="activeFontPicker === 'ui'" class="font-picker-popover" @pointerdown.stop>
        <input
          v-model="uiFontQuery"
          autocomplete="off"
          placeholder="搜索或输入字体家族"
          spellcheck="false"
          @keydown="handleFontInputKeydown($event, 'ui')"
        />
        <div class="font-option-list">
          <button
            v-for="family in uiFontOptions"
            :key="family"
            type="button"
            @click="addFontFamily('ui', family)"
          >
            <span :style="{ fontFamily: family }">{{ family }}</span>
          </button>
          <button v-if="uiFontQuery.trim()" type="button" @click="addFontFamily('ui', uiFontQuery)">
            添加 "{{ uiFontQuery.trim() }}"
          </button>
          <p v-if="fontsLoading" class="font-empty">正在读取本机字体...</p>
          <p v-else-if="!uiFontOptions.length && !uiFontQuery.trim()" class="font-empty">没有可添加字体</p>
        </div>
      </div>
    </div>

    <div class="font-family-control">
      <div class="font-family-header">
        <label>文字字体</label>
        <span>{{ textFontFamiliesDraft.length ? `${textFontFamiliesDraft.length} 个字体家族` : '使用默认字体栈' }}</span>
      </div>
      <div class="font-chip-row">
        <button
          v-for="family in textFontFamiliesDraft"
          :key="family"
          class="font-chip"
          type="button"
          @click="removeFontFamily('text', family)"
        >
          {{ family }} x
        </button>
        <button class="font-add-button" type="button" @click.stop="activeFontPicker = activeFontPicker === 'text' ? null : 'text'">
          添加字体
        </button>
      </div>
      <div v-if="activeFontPicker === 'text'" class="font-picker-popover font-picker-popover--above" @pointerdown.stop>
        <input
          v-model="textFontQuery"
          autocomplete="off"
          placeholder="搜索或输入字体家族"
          spellcheck="false"
          @keydown="handleFontInputKeydown($event, 'text')"
        />
        <div class="font-option-list">
          <button
            v-for="family in textFontOptions"
            :key="family"
            type="button"
            @click="addFontFamily('text', family)"
          >
            <span :style="{ fontFamily: family }">{{ family }}</span>
          </button>
          <button v-if="textFontQuery.trim()" type="button" @click="addFontFamily('text', textFontQuery)">
            添加 "{{ textFontQuery.trim() }}"
          </button>
          <p v-if="fontsLoading" class="font-empty">正在读取本机字体...</p>
          <p v-else-if="!textFontOptions.length && !textFontQuery.trim()" class="font-empty">没有可添加字体</p>
        </div>
      </div>
    </div>
    <p class="setting-hint">字体按从左到右的顺序组成 font-family;留空时使用原默认 fallback。</p>
  </div>
</template>

<style scoped>
.color-control-header span,
.page-display-header span,
.font-family-header span,
.font-empty,
.setting-hint {
  display: none;
}

.save-model-btn {
  background: var(--color-primary);
  color: #fff;
}

.cancel-model-btn {
  width: auto;
  min-width: 0;
  flex: 0 0 auto;
  padding: 0 var(--space-16);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  white-space: nowrap;
}

.background-cover-control {
  display: grid;
  grid-template-columns: var(--settings-label-width, 112px) minmax(0, 360px);
  align-items: start;
  gap: var(--space-12);
  margin-top: var(--space-16);
}

.background-cover-header label {
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
}

.background-cover-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: var(--space-8);
  min-width: 0;
}

.background-cover-body :deep(.library-cover-uploader) {
  min-height: 180px;
}

.background-cover-body .cancel-model-btn:disabled {
  cursor: default;
  opacity: 0.4;
}

:global(.settings-body .color-control),
:global(.settings-body .page-display-control),
:global(.settings-body .font-family-control) {
  display: flex;
  align-items: center;
  gap: var(--space-12);
  padding-left: 0 !important;
}

.color-control-header,
.page-display-header,
.font-family-header {
  flex: 0 0 var(--settings-label-width, 112px);
  min-width: 0;
  margin-bottom: 0;
}

.color-control-header label,
.page-display-header label,
.font-family-header label {
  width: var(--settings-label-width, 112px) !important;
  margin-left: 0 !important;
}

.color-row,
.settings-resource-page-switch,
.font-size-row,
.font-chip-row {
  flex: 0 1 auto;
  min-width: 0;
}

.font-size-row input[type='range'] {
  width: 100%;
  min-width: 0;
}

.font-picker-popover--above {
  top: auto;
  bottom: calc(100% + 4px);
}

.settings-resource-page-switch {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 2px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
}

.settings-resource-page-slider {
  position: absolute;
  top: 2px;
  height: calc(100% - 4px);
  border-radius: 999px;
  background: var(--color-primary-softer);
  pointer-events: none;
  transition: left 250ms ease, width 250ms ease;
}

.settings-resource-page-button {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 28px;
  padding: 0 var(--space-8);
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
}

.settings-resource-page-button:hover,
.settings-resource-page-button.active {
  color: var(--color-primary);
}
</style>

