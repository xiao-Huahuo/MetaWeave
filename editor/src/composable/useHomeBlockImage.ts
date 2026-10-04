/**
 * 主页分块背景图 composable。
 *
 * 用法:
 * 传入块的目录名与容器元素 ref, 返回:
 * - frontUrl: 当前背景图 URL(仅一张, 配合 <Transition> 由上层做交叉淡入淡出),
 *   某块无图时为 null, 调用方保持纯色底。
 * - textTone: 'dark' | 'light' | null, 按当前图片的感知亮度判断文字应使用的色系:
 *   'dark' 表示图片偏暗, 文字/图标应用浅色; 'light' 反之; null 表示无图, 用默认主题色。
 *
 * 行为:
 * - 按容器宽高比自动在方形(block)与矩形(rectangle)图池间选择,
 *   形状变化(如窗口缩放/响应式断点切换)时自动切到对应图池。
 * - 每 5 秒有 30% 概率在当前图池内切换到另一张图, 其余情况保持原图。
 * - 亮度在图片加载完成后用 canvas 采样计算, 先定 tone 再换图, 避免文字颜色闪烁。
 */
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref,
  type ComputedRef,
  type Ref,
} from 'vue'

import { getHomeImageSet, type HomeImageSet } from './homeImages'

/** 宽高比小于该值视为方形(block), 否则为矩形(rectangle)。 */
const SQUARE_RATIO_LIMIT = 1.2
/** 切换检测间隔。 */
const SWITCH_INTERVAL_MS = 5000
/** 每个周期切换的概率。 */
const SWITCH_PROBABILITY = 0.3
/** 亮度达到该值视为"亮图", 文字用深色。 */
const LIGHTNESS_THRESHOLD = 0.5
/** 亮度采样边长(缩到很小再取均值, 足够代表整体明暗)。 */
const SAMPLE_SIZE = 32

type HomeImageShape = 'block' | 'rectangle'

function pickRandom(pool: readonly string[], exclude?: string): string | null {
  if (pool.length === 0) return null
  if (pool.length === 1) return pool[0] ?? null
  const candidates = exclude ? pool.filter((url) => url !== exclude) : [...pool]
  return candidates[Math.floor(Math.random() * candidates.length)] ?? null
}

/** 同一 URL 的亮度只计算一次。 */
const brightnessCache = new Map<string, Promise<number>>()

function computeBrightness(url: string): Promise<number> {
  let cached = brightnessCache.get(url)
  if (!cached) {
    cached = new Promise<number>((resolve) => {
      const img = new Image()
      img.decoding = 'async'
      img.onload = () => {
        try {
          const canvas = document.createElement('canvas')
          canvas.width = SAMPLE_SIZE
          canvas.height = SAMPLE_SIZE
          const ctx = canvas.getContext('2d')
          if (!ctx) return resolve(0.5)
          ctx.drawImage(img, 0, 0, SAMPLE_SIZE, SAMPLE_SIZE)
          const data = ctx.getImageData(0, 0, SAMPLE_SIZE, SAMPLE_SIZE).data
          let sum = 0
          for (let i = 0; i < data.length; i += 4) {
            // Canvas ImageData contains complete RGBA groups, so each pixel has all three channels.
            sum += 0.299 * data[i]! + 0.587 * data[i + 1]! + 0.114 * data[i + 2]!
          }
          resolve(sum / (data.length / 4) / 255)
        } catch {
          resolve(0.5)
        }
      }
      img.onerror = () => resolve(0.5)
      img.src = url
    })
    brightnessCache.set(url, cached)
  }
  return cached
}

export function useHomeBlockImage(
  blockName: string,
  containerRef: Ref<HTMLElement | null>,
): {
  /** 当前背景图 URL, 供 <Transition> 交叉淡入淡出。 */
  frontUrl: Ref<string | null>
  /** 'dark' | 'light' | null: 文字应使用的色系。 */
  textTone: ComputedRef<'dark' | 'light' | null>
} {
  const set: HomeImageSet | undefined = getHomeImageSet(blockName)
  const shape = ref<HomeImageShape | null>(null)
  const frontUrl = ref<string | null>(null)
  const isLight = ref<boolean | null>(null)

  const textTone = computed<'dark' | 'light' | null>(() => {
    if (isLight.value === null) return null
    return isLight.value ? 'light' : 'dark'
  })

  const poolFor = (shapeKey: HomeImageShape | null): readonly string[] => {
    if (!set) return []
    return shapeKey === 'block' ? set.block : set.rectangle
  }

  /** 异步切换: 先算好亮度定 tone, 再换 URL, 避免文字颜色与图片不同步。 */
  let seq = 0
  async function activate(url: string) {
    const my = ++seq
    const brightness = await computeBrightness(url)
    if (my !== seq) return
    isLight.value = brightness >= LIGHTNESS_THRESHOLD
    frontUrl.value = url
  }

  function applyShape(next: HomeImageShape) {
    if (next === shape.value && frontUrl.value !== null) return
    shape.value = next
    const url = pickRandom(poolFor(next))
    if (url) void activate(url)
  }

  let observer: ResizeObserver | null = null
  let timer: ReturnType<typeof setInterval> | null = null

  onMounted(() => {
    const el = containerRef.value
    if (!el || !set) return
    observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0]?.contentRect ?? { width: 0, height: 0 }
      const ratio = width / Math.max(1, height)
      applyShape(ratio < SQUARE_RATIO_LIMIT ? 'block' : 'rectangle')
    })
    observer.observe(el)
    timer = setInterval(() => {
      if (Math.random() < SWITCH_PROBABILITY) {
        const url = pickRandom(poolFor(shape.value), frontUrl.value ?? undefined)
        if (url) void activate(url)
      }
    }, SWITCH_INTERVAL_MS)
  })

  onBeforeUnmount(() => {
    observer?.disconnect()
    if (timer !== null) clearInterval(timer)
  })

  return { frontUrl, textTone }
}
