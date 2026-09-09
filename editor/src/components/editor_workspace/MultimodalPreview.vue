<!--
  Multimodal file preview surface.

  Usage:
  Renders backend preview payloads for images, videos, PDFs, tables,
  DOCX-derived HTML, and unsupported binary files in the editor center pane.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import DOMPurify from 'dompurify'
import mpegts from 'mpegts.js'

import ImagePreviewer from '@/components/common/ImagePreviewer.vue'
import { useImagePreviewer } from '@/components/common/useImagePreviewer'
import type { ImagePreviewItem } from '@/components/common/useImagePreviewer'
import PdfPreview from '@/components/editor_workspace/PdfPreview.vue'
import { buildApiUrl } from '@/api/client'
import type { FilePreviewPayload } from '@/types/knowledge'
import type { ScannerOcrBlock } from '@/api/scanner'

const props = defineProps<{
  preview: FilePreviewPayload | null
  blocks?: ScannerOcrBlock[]
  activeBlockId?: string
  lockedBlockId?: string
}>()
const emit = defineEmits<{
  blockHover: [blockId: string]
  blockLeave: []
  blockSelect: [blockId: string]
}>()

const imagePreviewer = useImagePreviewer()
const videoElement = ref<HTMLVideoElement | null>(null)
let transportStreamPlayer: ReturnType<typeof mpegts.createPlayer> | null = null

const safeHtml = computed(() => DOMPurify.sanitize(props.preview?.html ?? '', {
  ALLOWED_ATTR: ['src', 'alt', 'class', 'href', 'target', 'rel', 'width', 'height'],
  ADD_TAGS: ['img'],
}))

const imageFiles = computed(() => {
  if (props.preview?.kind !== 'image') return []
  const src = props.preview.raw_url ? buildApiUrl(props.preview.raw_url) : (props.preview.data_url || '')
  return [{ src, alt: props.preview.path || '' }]
})

const previewSource = computed(() => {
  if (!props.preview) {
    return ''
  }
  if (props.preview.raw_url) {
    return buildApiUrl(props.preview.raw_url)
  }
  return props.preview.data_url ?? ''
})

function destroyTransportStreamPlayer() {
  if (!transportStreamPlayer) return
  transportStreamPlayer.unload()
  transportStreamPlayer.detachMediaElement()
  transportStreamPlayer.destroy()
  transportStreamPlayer = null
}

async function syncVideoPlayer() {
  destroyTransportStreamPlayer()
  if (props.preview?.kind !== 'video' || props.preview.video_container !== 'mpegts') return
  await nextTick()
  if (!videoElement.value || !previewSource.value || !mpegts.isSupported()) return
  transportStreamPlayer = mpegts.createPlayer({
    type: 'mpegts',
    isLive: false,
    url: previewSource.value,
    filesize: props.preview.size,
  }, {
    lazyLoad: true,
    autoCleanupSourceBuffer: true,
    rangeLoadZeroStart: true,
  })
  transportStreamPlayer.attachMediaElement(videoElement.value)
  transportStreamPlayer.load()
}

watch(
  () => [props.preview?.path, props.preview?.video_container, props.preview?.size],
  syncVideoPlayer,
  { immediate: true, flush: 'post' },
)

onBeforeUnmount(destroyTransportStreamPlayer)

function maxColumns(rows: string[][]): number {
  return rows.reduce((max, row) => Math.max(max, row.length), 0)
}

function handleDocumentClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (target.tagName !== 'IMG' || !(target instanceof HTMLImageElement) || !target.src) {
    return
  }
  const root = target.closest('.document-preview')
  if (!root) return
  const allImgs = root.querySelectorAll<HTMLImageElement>('img[src]')
  const items: ImagePreviewItem[] = []
  let clickIndex = -1
  allImgs.forEach((img, i) => {
    if (img === target) clickIndex = i
    items.push({ src: img.src, alt: img.alt || undefined })
  })
  if (clickIndex >= 0) {
    imagePreviewer.open(items, clickIndex)
  }
}
</script>

<template>
  <article class="multimodal-preview">
    <div v-if="!preview" class="preview-message">没有可用预览。</div>

    <ImagePreviewer
      v-else-if="preview.kind === 'image'"
      mode="embedded"
      :files="imageFiles"
      :blocks="blocks"
      :active-block-id="activeBlockId"
      :locked-block-id="lockedBlockId"
      @block-hover="emit('blockHover', $event)"
      @block-leave="emit('blockLeave')"
      @block-select="emit('blockSelect', $event)"
    />

    <PdfPreview
      v-else-if="preview.kind === 'pdf'"
      :preview="preview"
      :source="previewSource"
      :blocks="blocks"
      :active-block-id="activeBlockId"
      :locked-block-id="lockedBlockId"
      @block-hover="emit('blockHover', $event)"
      @block-leave="emit('blockLeave')"
      @block-select="emit('blockSelect', $event)"
    />

    <video
      v-else-if="preview.kind === 'video'"
      ref="videoElement"
      class="video-preview"
      controls
      preload="metadata"
      playsinline
    >
      <source
        v-if="preview.video_container !== 'mpegts'"
        :src="previewSource"
        :type="preview.mime_type"
      />
      当前浏览器无法播放此视频。
    </video>

    <div v-else-if="preview.kind === 'table'" class="table-preview">
      <section v-for="sheet in preview.sheets ?? []" :key="sheet.name" class="table-sheet">
        <h3>{{ sheet.name }}</h3>
        <div class="table-scroll">
          <table>
            <tbody>
              <tr v-for="(row, rowIndex) in sheet.rows" :key="rowIndex">
                <td v-for="columnIndex in maxColumns(sheet.rows)" :key="columnIndex">
                  {{ row[columnIndex - 1] ?? '' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <div v-else-if="preview.kind === 'document'" class="document-preview" v-html="safeHtml" @click="handleDocumentClick"></div>

    <div v-else-if="preview.kind === 'presentation'" class="presentation-preview" aria-label="PPTX preview placeholder"></div>

    <pre v-else-if="preview.kind === 'text'" class="text-preview">{{ preview.content }}</pre>

    <div v-else class="preview-message">
      {{ preview.message || '当前文件类型暂不支持预览。' }}
    </div>
  </article>
</template>

<style scoped>
.multimodal-preview {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  border: 0;
  border-radius: 0;
  background: var(--color-canvas);
  font-family: var(--font-ui);
}

.video-preview {
  align-self: center;
  width: 100%;
  max-width: 1200px;
  max-height: 100%;
  margin: auto;
  background: #000;
  object-fit: contain;
}

.table-preview,
.document-preview,
.presentation-preview,
.text-preview,
.preview-message {
  flex: 1;
  min-width: 0;
  padding: var(--space-16);
}

.table-sheet + .table-sheet {
  margin-top: var(--space-16);
}

.table-sheet h3 {
  margin: 0 0 var(--space-8);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
}

.table-scroll {
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.table-scroll table {
  min-width: 100%;
  border-collapse: collapse;
  color: var(--color-text);
  font-family: var(--font-text);
  font-size: calc(12px * var(--text-font-scale));
}

.table-scroll td {
  padding: var(--space-6) var(--space-8);
  border-right: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  white-space: pre-wrap;
}

.document-preview {
  max-width: 880px;
  margin: 0 auto;
  color: var(--color-text);
  font-family: var(--font-text);
  font-size: calc(14px * var(--text-font-scale));
  line-height: 1.7;
}

.document-preview :deep(p) {
  margin: 0 0 var(--space-10);
}

.document-preview :deep(img) {
  max-width: 100%;
  max-height: min(72vh, 960px);
  height: auto;
  object-fit: contain;
  border-radius: 6px;
}

.text-preview {
  margin: 0;
  color: var(--color-text);
  font-family: var(--font-text);
  font-size: calc(13px * var(--text-font-scale));
  line-height: 1.6;
  white-space: pre-wrap;
}

.preview-message {
  display: grid;
  place-items: center;
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
}
</style>
