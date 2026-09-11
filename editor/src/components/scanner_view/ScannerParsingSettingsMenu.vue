<!--
  Shared scanner parsing menu.

  Used by both the scanner upload surface and batch queue toolbar. It owns no
  persisted preference: models are provided by the parent and snapshotted when
  a task is created.
-->
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { checkVlmConnection, ensureLocalOcr } from '@/api/settings'
import IcIcon from '@/components/common/IcIcon.vue'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuPortal, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useSettingsStore } from '@/stores/settings'

defineOptions({ name: 'ScannerParsingSettingsMenu' })

const ocrEnabled = defineModel<boolean>('ocrEnabled', { required: true })
const onlineEnabled = defineModel<boolean>('onlineEnabled', { required: true })
const props = withDefaults(defineProps<{ placement?: 'overlay' | 'toolbar' }>(), { placement: 'overlay' })
const emit = defineEmits<{ error: [message: string] }>()
const settingsStore = useSettingsStore()
const checking = ref(false)

async function validateOnline(): Promise<boolean> {
  if (!settingsStore.profile.vlmEnabled) {
    onlineEnabled.value = false
    emit('error', '请先在 OCR/VLM 设置中开启 VLM')
    return false
  }
  checking.value = true
  try {
    const status = await checkVlmConnection(settingsStore.profile.userId)
    if (!status.online || !status.authorized) throw new Error(status.message)
    onlineEnabled.value = true
    return true
  } catch (reason) {
    onlineEnabled.value = false
    emit('error', reason instanceof Error ? reason.message : '当前无法连接 MinerU')
    return false
  } finally {
    checking.value = false
  }
}

async function toggleOnline(): Promise<void> {
  if (checking.value) return
  if (onlineEnabled.value) {
    if (ocrEnabled.value) {
      checking.value = true
      try {
        await ensureLocalOcr(settingsStore.profile.userId)
      } catch (reason) {
        emit('error', reason instanceof Error ? reason.message : '本地 OCR 模型下载或加载失败')
        return
      } finally {
        checking.value = false
      }
    }
    onlineEnabled.value = false
    return
  }
  await validateOnline()
}

async function toggleOcr(): Promise<void> {
  if (checking.value) return
  if (ocrEnabled.value) {
    ocrEnabled.value = false
    return
  }
  if (!onlineEnabled.value) {
    checking.value = true
    try {
      await ensureLocalOcr(settingsStore.profile.userId)
    } catch (reason) {
      ocrEnabled.value = false
      emit('error', reason instanceof Error ? reason.message : '本地 OCR 模型下载或加载失败')
      return
    } finally {
      checking.value = false
    }
  }
  ocrEnabled.value = true
}

watch(() => settingsStore.profile.vlmEnabled, enabled => {
  if (!enabled) onlineEnabled.value = false
})
watch(onlineEnabled, enabled => { if (enabled && !checking.value) void validateOnline() })
onMounted(() => { if (onlineEnabled.value) void validateOnline() })
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <button class="scanner-settings" :class="props.placement" type="button" title="解析设置" aria-label="解析设置" @click.stop>
        <IcIcon name="settings" :size="16" />
      </button>
    </DropdownMenuTrigger>
    <DropdownMenuPortal>
      <DropdownMenuContent align="end">
        <DropdownMenuItem :disabled="checking" @select="toggleOcr">
          <IcIcon :name="ocrEnabled ? 'check' : 'radio-unchecked'" :size="15" />
          <span>OCR</span><span class="setting-value">{{ ocrEnabled ? '已开启' : '已关闭' }}</span>
        </DropdownMenuItem>
        <DropdownMenuItem :disabled="checking || !settingsStore.profile.vlmEnabled" @select="toggleOnline">
          <IcIcon :name="onlineEnabled ? 'check' : 'radio-unchecked'" :size="15" />
          <span>联网</span><span class="setting-value">{{ onlineEnabled ? 'MinerU' : '本地' }}</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenuPortal>
  </DropdownMenu>
</template>

<style scoped>
.scanner-settings { display:grid; place-items:center; width:30px; height:30px; padding:0; border:0; border-radius:50%; background:transparent; color:var(--color-text-secondary); }
.scanner-settings.overlay { position:absolute; top:14px; right:14px; }
.scanner-settings:hover { background:var(--color-primary-softer); color:var(--color-primary); }
.scanner-settings:active { transform:scale(.94); }
.setting-value { margin-left:auto; color:var(--color-text-muted); font-size:11px; }
@media (max-width:480px) { .scanner-settings.overlay { top:9px; right:9px; } }
</style>
