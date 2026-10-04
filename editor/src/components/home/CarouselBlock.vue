<!--
  主页轮播子组件。

  用法:
  GTAOL 风格主视觉轮播,占据主页最大区块。每张幻灯片为可点击入口,
  点击后通过 open 事件上抛跳转目标。默认自动播放,悬停或聚焦时暂停。
  compact 紧凑模式用于右下角工具轮播:标题/图标与导航块一致、不显示胶囊。
  每张幻灯片由 CarouselSlide 子组件独立渲染,自带背景图切换与文字动态对比。
-->
<script lang="ts">
import type { WorkspaceMainView } from '@/types/knowledge'

/** 轮播幻灯片数据。 */
export interface CarouselSlide {
  /** IcIcon 图标名。 */
  icon: string
  /** 幻灯片标题。 */
  title: string
  /** 幻灯片副标题。 */
  subtitle: string
  /** 底部提示文案。 */
  hint: string
  /** 点击后跳转的工作区视图。 */
  target: WorkspaceMainView
  /** 背景图对应的块目录名(assets/images/home/<名>), 缺省则纯色底。 */
  image?: string
  /** 当前入口的全局语义强调色,缺省时沿用全局主色。 */
  accent?: string
}
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import CarouselSlide from './CarouselSlide.vue'

const props = defineProps<{
  slides?: CarouselSlide[]
  /** 紧凑模式: 用于小卡片轮播,标题/图标与导航块一致且不显示胶囊。 */
  compact?: boolean
}>()

const emit = defineEmits<{ open: [view: WorkspaceMainView] }>()

const isCompact = computed(() => props.compact)

const DEFAULT_SLIDES: CarouselSlide[] = [
  {
    icon: 'psychology',
    title: 'Agent 智能体',
    subtitle: '与 AI 对话,让智能体协助你总结、整理与可视化知识库内容',
    hint: '开始对话',
    target: 'agent',
    image: 'agent',
  },
  {
    icon: 'graph',
    title: '知识图谱',
    subtitle: '将文档抽取为实体与关系,一键洞察知识库的整体结构',
    hint: '查看图谱',
    target: 'graph',
    image: 'graph',
  },
  {
    icon: 'book',
    title: '图书馆',
    subtitle: '浏览、收藏与管理你的知识库文档与文件夹',
    hint: '进入图书馆',
    target: 'library',
    image: 'library',
  },
  {
    icon: 'search',
    title: '全库搜索',
    subtitle: '全文检索与语义检索双通道,快速定位目标文档',
    hint: '开始搜索',
    target: 'search',
    image: 'search',
  },
  {
    icon: 'code',
    title: 'MD-HTML 可视化',
    subtitle: '让 AI 将文档重排为更精美的 HTML 可视化页面',
    hint: '去可视化',
    target: 'visualization',
    image: 'md-html',
  },
]

const slides = computed(() => props.slides ?? DEFAULT_SLIDES)
const activeIndex = ref(0)
const paused = ref(false)
/** 让轮播边框、光效、图标、提示和活动圆点共享当前入口颜色。 */
const activeAccentStyle = computed(() => ({
  '--home-carousel-accent': slides.value[activeIndex.value]?.accent ?? 'var(--color-primary)',
}))

const AUTOPLAY_MS = 5000
let timer: ReturnType<typeof setInterval> | null = null

function goTo(index: number) {
  activeIndex.value = (index + slides.value.length) % slides.value.length
}

function stopAutoplay() {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

function startAutoplay() {
  stopAutoplay()
  timer = setInterval(() => {
    if (!paused.value) {
      goTo(activeIndex.value + 1)
    }
  }, AUTOPLAY_MS)
}

onMounted(startAutoplay)
onBeforeUnmount(stopAutoplay)
</script>

<template>
  <div
    class="carousel-block"
    :class="{ compact: isCompact }"
    :style="activeAccentStyle"
    @mouseenter="paused = true"
    @mouseleave="paused = false"
    @focusin="paused = true"
    @focusout="paused = false"
  >
    <div
      class="carousel-track"
      :style="{ transform: `translateX(-${activeIndex * 100}%)` }"
    >
      <CarouselSlide
        v-for="slide in slides"
        :key="slide.target"
        :slide="slide"
        :compact="isCompact"
        @open="(view) => emit('open', view)"
      />
    </div>
    <div class="carousel-dots">
      <button
        v-for="(slide, index) in slides"
        :key="`dot-${slide.target}`"
        class="carousel-dot"
        :class="{ active: index === activeIndex }"
        :style="{ '--home-dot-accent': slide.accent ?? 'var(--color-primary)' }"
        type="button"
        :aria-label="`切换到第 ${index + 1} 张`"
        @click="goTo(index)"
      ></button>
    </div>
  </div>
</template>

<style scoped>
.carousel-block {
  position: relative;
  width: 100%;
  height: 100%;
  border: 1px solid var(--color-border);
  border-radius: 0;
  overflow: hidden;
  /* 小阴影 */
  box-shadow: var(--home-card-shadow);
  background: var(--color-surface);
  transition:
    border-color var(--transition-normal),
    box-shadow var(--transition-normal);
}

/* 悬停光效: 与导航块一致的柔和主题色(亮) / 白色(暗) */
.carousel-block::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 1;
  background: radial-gradient(120% 130% at 50% 0%, color-mix(in srgb, var(--home-carousel-accent) 28%, transparent), transparent 68%);
  opacity: 0;
  transition: opacity var(--transition-normal);
  pointer-events: none;
}

.carousel-block:hover {
  border-color: color-mix(in srgb, var(--home-carousel-accent) 68%, transparent);
  box-shadow: var(--home-card-shadow), 0 0 12px color-mix(in srgb, var(--home-carousel-accent) 24%, transparent);
}

.carousel-block:hover::after {
  opacity: 1;
}

.carousel-track {
  display: flex;
  width: 100%;
  height: 100%;
  transition: transform 600ms cubic-bezier(0.22, 1, 0.36, 1);
}

.carousel-dots {
  position: absolute;
  bottom: var(--space-16);
  left: 50%;
  transform: translateX(-50%);
  z-index: 2;
  display: flex;
  gap: var(--space-8);
  padding: var(--space-6) var(--space-10);
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-surface) 70%, transparent);
  backdrop-filter: blur(6px);
}

.carousel-dot {
  width: 8px;
  height: 8px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: var(--color-border-strong);
  transition: background var(--transition-fast), transform var(--transition-fast);
}

.carousel-dot.active {
  width: 20px;
  border-radius: 999px;
  background: var(--home-dot-accent);
}

.carousel-dot:focus-visible {
  outline: 2px solid var(--home-dot-accent, var(--color-primary));
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .carousel-block::after,
  .carousel-track {
    transition: none;
  }
}
</style>
