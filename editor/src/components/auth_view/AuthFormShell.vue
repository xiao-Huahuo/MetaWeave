<!-- Global entry shell: supplied white-form surface, question-box slide motion and fixed navigation. -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import IcIcon from '@/components/common/IcIcon.vue'
import lightLogo from '@/assets/images/亮色无底图标.png'
const props = defineProps<{ page: number; message: string; registering?: boolean; busy?: boolean; onboarding?: boolean; credentialsChanged?: boolean }>()
const emit = defineEmits<{ navigate: [offset: number]; confirm: [] }>()
const sliding = ref(false)
const form = ref<HTMLFormElement | null>(null)
const track = ref<HTMLDivElement | null>(null)
const header = ref<HTMLElement | null>(null)
const footer = ref<HTMLElement | null>(null)
const height = ref<string>()
/** Login and library selection share the login height; registration keeps its natural height. */
const compact = computed(() => props.page === 1 || (props.page === 0 && !props.registering))
let resizeObserver: ResizeObserver | undefined
/** Measure intrinsic content, not the constrained viewport, so long pages retain scrolling. */
function updateHeight() {
  if (!form.value || !track.value || !header.value || !footer.value) return
  const style = getComputedStyle(form.value)
  const naturalHeight = track.value.offsetHeight + header.value.offsetHeight + footer.value.offsetHeight
    + Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom)
    + Number.parseFloat(style.rowGap) * 2
  const targetHeight = compact.value ? 480 : naturalHeight
  height.value = `${Math.min(targetHeight, Number.parseFloat(style.maxHeight) || targetHeight)}px`
}
onMounted(() => {
  updateHeight()
  // One shell-owned observer covers page changes, disclosures, messages and viewport resizing.
  resizeObserver = new ResizeObserver(updateHeight)
  for (const element of [track.value, header.value, footer.value, form.value?.parentElement]) {
    if (element) resizeObserver.observe(element)
  }
})
let fallback: ReturnType<typeof setTimeout> | undefined
const pageNumber = computed(() => String(props.page + 1).padStart(2, '0'))
/** Ignore repeated navigation during the same bounded transition, including reduced-motion mode. */
function navigate(offset: number) {
  if (props.busy || !props.onboarding || sliding.value || props.page + offset < 0 || props.page + offset > 4) return
  sliding.value = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  emit('navigate', offset)
  if (sliding.value) fallback = setTimeout(finish, 700)
}
/** Release the transition owner on completion or disposal. */
function finish() {
  sliding.value = false
  if (fallback) clearTimeout(fallback)
  fallback = undefined
}
/** Focus may scroll to an off-screen transformed page; keep X at origin and preserve normal Y scrolling. */
function keepHorizontalOrigin(event: Event) {
  const viewport = event.currentTarget as HTMLElement
  if (viewport.scrollLeft !== 0) viewport.scrollLeft = 0
}
onBeforeUnmount(() => { finish(); resizeObserver?.disconnect() })
</script>
<template>
  <form ref="form" class="auth-form" :class="{ 'auth-form-compact': compact }" :style="{ height }" data-theme="light" aria-label="登录与首次配置" @submit.prevent="emit('confirm')">
    <header ref="header" class="auth-header">
      <img :src="lightLogo" alt="MetaWeave" />
      <div class="auth-navigation">
        <button
          type="button"
          aria-label="上一页"
          :disabled="!onboarding || page === 0 || sliding || busy"
          @click="navigate(-1)"
        >
          <IcIcon name="arrow-left" :size="18" /></button
        ><button
          type="button"
          aria-label="下一页"
          :disabled="!onboarding || page === 4 || sliding || busy || (page === 0 && credentialsChanged)"
          @click="navigate(1)"
        >
          <IcIcon name="arrow-right" :size="18" /></button
        ><span class="auth-page-number" aria-live="polite">{{ pageNumber }}</span>
      </div>
    </header>
    <div class="auth-viewport" @scroll="keepHorizontalOrigin">
      <div
        ref="track"
        class="auth-track"
        :style="{ transform: 'translateX(-' + page * 100 + '%)' }"
        @transitionend.self="finish"
        @transitioncancel.self="finish"
      >
        <fieldset
          v-for="index in 5"
          :key="index"
          class="auth-page"
          :class="{ active: page === index - 1 }"
          :disabled="page !== index - 1 || sliding || busy"
          :inert="page !== index - 1"
          :aria-hidden="page !== index - 1"
        >
          <slot :name="'step-' + (index - 1)" />
        </fieldset>
      </div>
    </div>
    <footer ref="footer" class="auth-footer">
      <p v-if="message" role="status" :title="message">{{ message }}</p>
      <span v-if="busy" class="auth-confirm-loader" role="status" aria-label="正在验证或保存" />
      <button v-if="page < 4" class="auth-button" type="submit" :disabled="busy">确定</button>
    </footer>
  </form>
</template>
