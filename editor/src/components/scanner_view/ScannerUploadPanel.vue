<!--
  Scanner idle and running main surface.

  Provides unrestricted file selection, drag/drop, URL entry, task-local OCR
  settings, real bundled examples, and the shared pixel progress presentation.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import PixelLoader from '@/components/common/PixelLoader.vue'
import ScannerParsingSettingsMenu from '@/components/scanner_view/ScannerParsingSettingsMenu.vue'
import { useSettingsStore } from '@/stores/settings'
import { formatProgress } from '@/utils/progress'
import type { ScannerRecord } from '@/api/scanner'
import lightLogo from '@/assets/images/亮色无底图标.png'
import darkLogo from '@/assets/images/暗色无底图标.png'

const props = withDefaults(defineProps<{
  running: ScannerRecord | null
  batch?: boolean
  embedded?: boolean
  busy?: boolean
  busyLabel?: string
  error?: string
}>(), {
  batch: false,
  embedded: false,
  busy: false,
  busyLabel: '正在创建扫描任务',
  error: '',
})
const emit = defineEmits<{
  upload: [file: File, sourceKind?: string]
  uploadBatch: [files: File[]]
  crawl: [url: string]
  crawlBatch: [urls: string[]]
  settingError: [message: string]
}>()

const settingsStore = useSettingsStore()
const picker = ref<HTMLInputElement | null>(null)
const exampleViewport = ref<HTMLElement | null>(null)
const dragging = ref(false)
const urlOpen = ref(false)
const urlDraft = ref('')
const urlError = ref('')
const visibleCount = ref(3)
const carouselOffset = ref(0)
const ocrEnabled = defineModel<boolean>('ocrEnabled', { required: true })
const onlineEnabled = defineModel<boolean>('onlineEnabled', { required: true })
const logo = computed(() => settingsStore.isDark ? darkLogo : lightLogo)
let carouselTimer: number | null = null
let exampleObserver: ResizeObserver | null = null

const exampleModules = import.meta.glob('@/assets/images/example/*.{png,jpg,jpeg,webp}', { eager: true, query: '?url', import: 'default' }) as Record<string, string>
const tagMap: Record<string, string[]> = {
  'FPGA表格': ['表格', 'FPGA'],
  '发表论文加分细则': ['细则', '论文'],
  '同步时序逻辑电路实验': ['实验', '电路'],
  '基本素质测评': ['测评', '表格'],
  '数字逻辑拼接图片': ['拼图', '逻辑'],
  '灰名单': ['名单', '文字'],
  '计算机类教学计划': ['教学', '计划'],
}
const examples = Object.entries(exampleModules).map(([path, src]) => {
  const filename = path.split('/').pop() ?? '示例.png'
  const title = filename.replace(/\.[^.]+$/u, '')
  return { filename, title, src, tags: tagMap[title] ?? ['文档'] }
})
const visibleExamples = computed(() => Array.from(
  { length: Math.min(visibleCount.value, examples.length) },
  (_, index) => examples[(carouselOffset.value + index) % examples.length],
).filter((example): example is typeof examples[number] => Boolean(example)))

/** Open the native file chooser from any non-control point in the upload area. */
function openPicker(): void {
  picker.value?.click()
}

/** Open the shared URL form with stale validation feedback cleared. */
function openUrlDialog(): void {
  urlError.value = ''
  urlOpen.value = true
}

/** Forward selected files through the single or batch scanner contract. */
function onPick(event: Event): void {
  const files = Array.from((event.target as HTMLInputElement).files ?? [])
  if (props.batch && files.length) emit('uploadBatch', files)
  else if (files[0]) emit('upload', files[0])
  if (picker.value) picker.value.value = ''
}

/** Accept dropped files through the single or batch scanner contract. */
function onDrop(event: DragEvent): void {
  dragging.value = false
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (props.batch && files.length) emit('uploadBatch', files)
  else if (files[0]) emit('upload', files[0])
}

/** Submit one URL or a newline-separated batch through the scanner contract. */
function submitUrl(): void {
  const values = [...new Set(urlDraft.value.split(/\r?\n/u).map(value => value.trim()).filter(Boolean))]
  if (!values.length) return
  const invalid = values.find((value) => {
    try {
      return !['http:', 'https:'].includes(new URL(value).protocol)
    } catch {
      return true
    }
  })
  if (invalid) {
    urlError.value = `无效网页地址：${invalid}`
    return
  }
  if (props.batch) emit('crawlBatch', values)
  else emit('crawl', values[0] as string)
  urlDraft.value = ''
  urlError.value = ''
  urlOpen.value = false
}

/** Fetch a bundled asset and submit it through exactly the same upload API. */
async function parseExample(example: { filename: string; src: string }): Promise<void> {
  const response = await fetch(example.src)
  const file = new File([await response.blob()], example.filename, { type: response.headers.get('Content-Type') ?? 'image/png' })
  if (props.batch) emit('uploadBatch', [file])
  else emit('upload', file, 'example')
}

/** Advance by one complete responsive page, wrapping each requested slot. */
function advanceExamples(): void {
  if (examples.length <= visibleCount.value) return
  carouselOffset.value = (carouselOffset.value + visibleCount.value) % examples.length
}

/** Derive the current page size from actual available width instead of viewport assumptions. */
function measureExamples(): void {
  const width = exampleViewport.value?.clientWidth ?? 0
  if (!width) return
  visibleCount.value = Math.max(1, Math.min(examples.length, Math.floor((width + 12) / 222)))
  carouselOffset.value %= Math.max(1, examples.length)
}

onMounted(() => {
  if (exampleViewport.value) {
    exampleObserver = new ResizeObserver(measureExamples)
    exampleObserver.observe(exampleViewport.value)
    measureExamples()
  }
  carouselTimer = window.setInterval(advanceExamples, 3_600)
})

onBeforeUnmount(() => {
  exampleObserver?.disconnect()
  if (carouselTimer !== null) window.clearInterval(carouselTimer)
})
</script>

<template>
  <section v-if="running || busy" class="scanner-running" :class="{ embedded }" aria-live="polite">
    <PixelLoader class="scanner-pixel-loader" />
    <strong>{{ running ? '解析中' : '正在创建' }}</strong>
    <span v-if="running">{{ running.stage_label }}</span>
    <span v-else>{{ busyLabel }}</span>
    <div v-if="running && running.parser_engine !== 'mineru'" class="scanner-progress" role="progressbar" :aria-valuenow="running.progress" aria-valuemin="0" aria-valuemax="100">
      <i :style="{ transform: `scaleX(${running.progress / 100})` }"></i>
    </div>
    <small v-if="running && running.parser_engine !== 'mineru'">{{ formatProgress(running.progress) }}%</small>
  </section>

  <div v-else class="scanner-start" :class="{ embedded }">
    <section
      class="scanner-drop-zone"
      :class="{ dragging }"
      role="button"
      tabindex="0"
      aria-label="拖拽或上传文件"
      @click="openPicker"
      @keydown.enter.prevent="openPicker"
      @keydown.space.prevent="openPicker"
      @dragenter.prevent="dragging = true"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <ScannerParsingSettingsMenu v-model:ocr-enabled="ocrEnabled" v-model:online-enabled="onlineEnabled" @error="emit('settingError', $event)" />
      <span class="scanner-drop-title"><IcIcon name="cloud-upload" :size="17" />拖拽或上传</span>
      <img class="scanner-logo" :src="logo" alt="" />
      <div class="scanner-upload-actions">
        <button type="button" @click.stop="openPicker"><IcIcon name="paperclip" :size="15" />上传文件</button>
        <button type="button" @click.stop="openUrlDialog"><IcIcon name="language" :size="15" />网页链接</button>
      </div>
      <input ref="picker" hidden type="file" :multiple="batch" @change="onPick" />
      <p>拖拽{{ batch ? '多个' : '' }}文件到此处开始解析</p>
      <p v-if="error" class="scanner-action-error" role="alert">{{ error }}</p>
    </section>

    <section class="scanner-examples" aria-labelledby="scanner-examples-title">
      <h2 id="scanner-examples-title"><IcIcon name="image" :size="16" />示例</h2>
      <div ref="exampleViewport" class="scanner-example-viewport">
        <Transition name="scanner-carousel" mode="out-in">
          <div :key="carouselOffset" class="scanner-example-page" :style="{ '--visible-count': visibleExamples.length }">
            <button v-for="example in visibleExamples" :key="example.filename" type="button" class="scanner-example" @click="parseExample(example)">
              <span class="scanner-example-image"><img :src="example.src" :alt="example.title" /></span>
              <span class="scanner-example-copy"><strong>{{ example.title }}</strong><span><i v-for="tag in example.tags" :key="tag">{{ tag }}</i></span></span>
            </button>
          </div>
        </Transition>
      </div>
    </section>
  </div>

  <Teleport to="body">
    <div v-if="urlOpen" class="scanner-url-backdrop" @click.self="urlOpen = false">
      <form class="scanner-url-dialog library-form-surface" role="dialog" aria-modal="true" aria-label="解析网页链接" @submit.prevent="submitUrl">
        <header><strong>网页链接</strong><button type="button" aria-label="关闭" @click="urlOpen = false"><IcIcon name="close" :size="16" /></button></header>
        <label>链接地址<textarea v-if="batch" v-model="urlDraft" class="form-input-surface" rows="5" required autofocus placeholder="每行输入一个 HTTP 或 HTTPS 地址"></textarea><input v-else v-model="urlDraft" class="form-input-surface" type="url" required autofocus placeholder="https://example.com/article" /></label>
        <p v-if="urlError" class="scanner-url-error" role="alert">{{ urlError }}</p>
        <footer><button type="button" @click="urlOpen = false">取消</button><button class="primary" type="submit">开始解析</button></footer>
      </form>
    </div>
  </Teleport>
</template>

<style scoped>
.scanner-start { position: absolute; inset: 0; box-sizing: border-box; display: grid; grid-template-rows: minmax(220px, 3fr) minmax(190px, 2fr); gap: clamp(12px,2.4vh,24px); width: auto; max-width: 1040px; min-width: 0; min-height: 0; margin: 0 auto; padding: clamp(14px,3vw,36px); overflow: hidden; }
.scanner-start.embedded { position:relative; inset:auto; width:100%; height:min(620px,calc(100dvh - 96px)); padding:16px; }
.scanner-drop-zone { position: relative; display: flex; max-width: 100%; min-width: 0; min-height: 0; flex-direction: column; align-items: center; justify-content: center; overflow: hidden; border: 1px dashed var(--color-border-strong); border-radius: 28px; background: var(--color-canvas); cursor: pointer; transition: border-color 180ms ease, background 180ms ease, box-shadow 180ms ease, transform 140ms ease; }
.scanner-drop-zone:hover { border-color: color-mix(in srgb,var(--color-primary) 55%,var(--color-border-strong)); box-shadow: 0 10px 24px color-mix(in srgb,var(--color-text) 10%,transparent); }
.scanner-drop-zone:active { transform: scale(.995); }
.scanner-drop-zone.dragging { border-color: var(--color-primary); background: var(--color-primary-softer); }
.scanner-drop-title { position: absolute; top: 16px; left: 18px; display: inline-flex; align-items: center; gap: 7px; color: var(--color-text-secondary); font-size: calc(13px * var(--font-scale)); font-weight: 650; }
.scanner-logo { width: clamp(54px,7vh,76px); height: clamp(54px,7vh,76px); object-fit: contain; }
.scanner-upload-actions { display: flex; gap: 10px; margin-top: clamp(10px,2vh,20px); }
.scanner-upload-actions button { display: inline-flex; align-items: center; gap: 6px; min-height: 34px; padding: 0 14px; border: 1px solid var(--color-border); border-radius: 999px; background: var(--color-surface); color: var(--color-text); font: inherit; transition: border-color 150ms ease, background 150ms ease, transform 120ms ease; }
.scanner-upload-actions button:hover { border-color: var(--color-primary); background: var(--color-primary-softer); }
.scanner-upload-actions button:active { transform: scale(.97); }
.scanner-drop-zone p { margin: 10px 0 0; color: var(--color-text-muted); font-size: calc(11px * var(--font-scale)); }
.scanner-drop-zone .scanner-action-error { position:absolute; right:18px; bottom:14px; left:18px; overflow:hidden; color:var(--color-danger); text-align:center; text-overflow:ellipsis; white-space:nowrap; }
.scanner-examples { display: grid; grid-template-rows: auto minmax(0,1fr); max-width: 100%; min-width: 0; min-height: 0; }
.scanner-examples h2 { display: flex; align-items: center; gap: 7px; margin: 0 0 8px; font-size: calc(14px * var(--font-scale)); }
.scanner-example-viewport { position: relative; min-width: 0; min-height: 0; overflow: hidden; padding: 2px; }
.scanner-example-page { display: grid; width: 100%; height: 100%; min-width: 0; grid-template-columns: repeat(var(--visible-count),minmax(0,1fr)); gap: 12px; }
.scanner-example { display: grid; grid-template-rows: minmax(0,1fr) auto; min-width: 0; min-height: 0; padding: 0; overflow: hidden; border: 1px solid var(--color-border); border-radius: 28px; background: var(--color-canvas); color: var(--color-text); font: inherit; text-align: left; transition: border-color 200ms ease, box-shadow 200ms ease, transform 180ms cubic-bezier(.16,1,.3,1); }
.scanner-example:hover { border-color: color-mix(in srgb,var(--color-primary) 56%,var(--color-border)); box-shadow: 0 10px 24px color-mix(in srgb,var(--color-text) 11%,transparent); transform: translateY(-2px); }
.scanner-example-image { position: relative; z-index: 0; display: grid; place-items: center; min-height: 0; padding: 10px 12px 0; overflow: visible; }
.scanner-example-image img { width: 100%; height: 100%; max-height: 150px; object-fit: contain; border-radius: 7px; background: white; box-shadow: 0 10px 22px color-mix(in srgb,var(--color-text) 14%,transparent); transform: translateY(5px) translateZ(0); transition: transform 240ms cubic-bezier(.16,1,.3,1), box-shadow 240ms ease; }
.scanner-example:hover img { transform: translateY(-1px) rotate(-1deg) scale(1.025); box-shadow: 0 14px 28px color-mix(in srgb,var(--color-text) 18%,transparent); }
.scanner-example-copy { position: relative; z-index: 1; display: grid; align-content: center; gap: 6px; min-height: 54px; padding: 8px 12px; background: var(--color-canvas); }
.scanner-example-copy strong { overflow: hidden; font-size: calc(12px * var(--font-scale)); text-overflow: ellipsis; white-space: nowrap; }
.scanner-example-copy span { display: flex; flex-wrap: wrap; gap: 5px; }
.scanner-example-copy i { display: inline-flex; min-height: 23px; align-items: center; padding: 0 8px; overflow: hidden; border-radius: 999px; background: color-mix(in srgb,var(--color-primary) 30%,transparent); color: var(--color-tag-pill-text); font-size: 11px; font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.scanner-example-copy i:nth-child(6n + 2) { background: color-mix(in srgb,var(--color-accent) 30%,transparent); }
.scanner-example-copy i:nth-child(6n + 3) { background: color-mix(in srgb,var(--color-success) 30%,transparent); }
.scanner-example-copy i:nth-child(6n + 4) { background: color-mix(in srgb,var(--color-warning) 30%,transparent); }
.scanner-example-copy i:nth-child(6n + 5) { background: rgba(113,70,214,.3); }
.scanner-example-copy i:nth-child(6n) { background: rgba(0,155,166,.3); }
.scanner-carousel-enter-active,.scanner-carousel-leave-active { transition: opacity 220ms ease, transform 280ms cubic-bezier(.23,1,.32,1); }
.scanner-carousel-enter-from { opacity: 0; transform: translateX(32px); }
.scanner-carousel-leave-to { opacity: 0; transform: translateX(-32px); }
.scanner-running { position: absolute; inset: 0; display: grid; place-items: center; align-content: center; min-height: 0; color: var(--color-text); }
.scanner-running.embedded { position:relative; inset:auto; height:min(620px,calc(100dvh - 96px)); }
.scanner-pixel-loader { transform: scale(1.7); margin-bottom: 28px; }
.scanner-running strong { font-family: 'MinecraftAE Pixel', var(--font-ui); font-size: calc(18px * var(--font-scale)); }
.scanner-running span { margin-top: 8px; color: var(--color-text-muted); font-size: calc(12px * var(--font-scale)); }
.scanner-progress { position: relative; width: min(360px, 70vw); height: 7px; margin-top: 18px; overflow: hidden; border-radius: 4px; background: var(--color-border); }
.scanner-progress i { position: absolute; inset: 0; background: var(--color-primary); transform-origin: left; transition: transform 260ms ease; }
.scanner-running small { margin-top: 7px; color: var(--color-text-muted); }
.scanner-url-backdrop { position: fixed; inset: 0; z-index: 1100; display: grid; place-items: center; padding: 16px; background: rgba(0,0,0,.4); }
.scanner-url-dialog { display: grid; gap: 18px; width: min(520px,100%); padding: 18px; border: 4px solid var(--library-form-ring); border-radius: 28px; background: var(--color-surface); color: var(--color-text); }
.scanner-url-dialog header,.scanner-url-dialog footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.scanner-url-dialog header button { display: grid; place-items: center; width: 28px; height: 28px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: var(--color-text-muted); }
.scanner-url-dialog header button:hover { background: color-mix(in srgb,var(--color-text-secondary) 10%,transparent); color: var(--color-text); }
.scanner-url-dialog label { display: grid; gap: 7px; font-size: calc(12px * var(--font-scale)); }
.scanner-url-dialog input,.scanner-url-dialog textarea { padding:0 14px; border-radius:18px; outline:0; color:var(--color-text); font:inherit; }
.scanner-url-dialog input { height:42px; border-radius:999px; }
.scanner-url-dialog textarea { min-height:112px; padding-top:12px; resize:vertical; }
.scanner-url-error { margin:0; color:var(--color-danger); font-size:calc(12px * var(--font-scale)); }
.scanner-url-dialog footer { justify-content: flex-end; }
.scanner-url-dialog footer button { min-height: 32px; padding: 0 16px; border: 1px solid var(--color-border); border-radius: 999px; background: var(--color-surface-raised); color: var(--color-text); }
.scanner-url-dialog footer .primary { border-color: var(--color-primary); background: var(--color-primary); color: white; }
@media (max-width: 768px) { .scanner-start { grid-template-rows: minmax(210px,3fr) minmax(180px,2fr); padding: 12px; } }
@media (max-width: 480px) { .scanner-start { gap: 10px; padding: 8px; } .scanner-start.embedded { height:calc(100dvh - 80px); }.scanner-running.embedded { height:calc(100dvh - 80px); }.scanner-drop-title { top: 12px; left: 14px; } .scanner-upload-actions { gap: 6px; } .scanner-upload-actions button { padding: 0 10px; } .scanner-drop-zone p { display: none; } .scanner-example-copy { min-height: 50px; padding: 6px 9px; } }
@media (prefers-reduced-motion: reduce) { .scanner-drop-zone,.scanner-example,.scanner-example-image img,.scanner-progress i,.scanner-carousel-enter-active,.scanner-carousel-leave-active { transition: none; } .scanner-example:hover,.scanner-example:hover img { transform: none; } }
</style>
