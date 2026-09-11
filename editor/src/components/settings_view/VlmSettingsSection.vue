<!-- OCR/VLM settings with the same edit, save, cancel, and preset workflow as LLM settings. -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  checkVlmConnection, deleteVlmConfigPreset, ensureLocalOcr, fetchSavedVlmConfigs,
  fetchVlmConfig, saveVlmConfig, saveVlmConfigPreset,
  type SavedVlmConfig, type VlmConfigResponse,
} from '@/api/settings'
import SavedModelConfigRow from '@/components/settings_view/SavedModelConfigRow.vue'
import { useSettingsStore } from '@/stores/settings'

defineOptions({ name: 'VlmSettingsSection' })
const settingsStore = useSettingsStore()
const draft = ref<VlmConfigResponse | null>(null)
const effective = ref<VlmConfigResponse | null>(null)
const presets = ref<SavedVlmConfig[]>([])
const fileLimitMb = ref(200)
const showKey = ref(false)
const editing = ref(false)
const loading = ref(true)
const saving = ref(false)
const checking = ref(false)
const presetNameOpen = ref(false)
const presetLabel = ref('')
const message = ref('')
const error = ref('')
const effectiveParser = computed(() => effective.value?.enabled ? `MinerU ${effective.value.model}` : '本地流水线')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const config = await fetchVlmConfig(settingsStore.profile.userId)
    effective.value = { ...config }
    draft.value = { ...config }
    fileLimitMb.value = Math.round(config.max_file_bytes / 1024 / 1024)
    editing.value = !config.configured
    try {
      presets.value = (await fetchSavedVlmConfigs(settingsStore.profile.userId)).configs ?? []
    } catch {
      presets.value = []
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '读取 OCR/VLM 设置失败'
  } finally { loading.value = false }
}

async function save(): Promise<void> {
  if (!draft.value || saving.value) return
  saving.value = true
  message.value = ''
  error.value = ''
  let preparingLocal = false
  try {
    if (draft.value.ocr_enabled && !draft.value.enabled) {
      preparingLocal = true
      message.value = '正在准备本地 OCR 模型…'
      await ensureLocalOcr(settingsStore.profile.userId)
    }
    const saved = await saveVlmConfig(settingsStore.profile.userId, {
      enabled: draft.value.enabled, api_key: draft.value.api_key, model: draft.value.model,
      max_concurrency: draft.value.max_concurrency, max_file_bytes: fileLimitMb.value * 1024 * 1024,
      max_pages: draft.value.max_pages, submit_rate_per_minute: draft.value.submit_rate_per_minute,
      result_rate_per_minute: draft.value.result_rate_per_minute, ocr_enabled: draft.value.ocr_enabled,
    })
    effective.value = { ...saved }
    draft.value = { ...saved }
    settingsStore.updateProfile({ vlmEnabled: saved.enabled, ocrEnabled: saved.ocr_enabled })
    editing.value = false
    message.value = 'OCR/VLM 设置已保存'
  } catch (reason) {
    if (preparingLocal && draft.value) draft.value.ocr_enabled = false
    error.value = reason instanceof Error ? reason.message : '保存 OCR/VLM 设置失败'
  } finally { saving.value = false }
}

async function check(): Promise<void> {
  if (!draft.value || checking.value) return
  checking.value = true
  message.value = ''
  error.value = ''
  try {
    const result = await checkVlmConnection(settingsStore.profile.userId, draft.value.api_key)
    if (!result.online || !result.authorized) throw new Error(result.message)
    message.value = result.message
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'MinerU 连接检查失败' }
  finally { checking.value = false }
}

async function savePreset(): Promise<void> {
  if (!draft.value) return
  const label = presetLabel.value.trim()
  if (!label) return
  try {
    const saved = await saveVlmConfigPreset(settingsStore.profile.userId, {
      label, api_key: draft.value.api_key, model: draft.value.model,
      max_concurrency: draft.value.max_concurrency, max_file_bytes: fileLimitMb.value * 1024 * 1024,
      max_pages: draft.value.max_pages, submit_rate_per_minute: draft.value.submit_rate_per_minute,
      result_rate_per_minute: draft.value.result_rate_per_minute,
    })
    presets.value = [saved, ...presets.value]
    presetNameOpen.value = false
    presetLabel.value = ''
    message.value = 'VLM 模型配置已保存'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '保存 VLM 模型配置失败' }
}

/** Reveal an in-page name field; Electron does not reliably support window.prompt. */
function beginSavePreset(): void {
  if (!draft.value) return
  presetLabel.value = `MinerU ${draft.value.model}`
  presetNameOpen.value = true
  message.value = ''
  error.value = ''
}

function importPreset(config: SavedVlmConfig): void {
  if (!draft.value) return
  Object.assign(draft.value, {
    api_key: config.api_key, model: config.model, max_concurrency: config.max_concurrency,
    max_file_bytes: config.max_file_bytes, max_pages: config.max_pages,
    submit_rate_per_minute: config.submit_rate_per_minute, result_rate_per_minute: config.result_rate_per_minute,
  })
  fileLimitMb.value = Math.round(config.max_file_bytes / 1024 / 1024)
  editing.value = true
  message.value = `已加载“${config.label}”，保存后生效`
}

async function removePreset(config: SavedVlmConfig): Promise<void> {
  try {
    await deleteVlmConfigPreset(config.config_id, settingsStore.profile.userId)
    presets.value = presets.value.filter(item => item.config_id !== config.config_id)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '删除 VLM 模型配置失败' }
}
onMounted(load)
</script>

<template>
  <div class="setting-section settings-model-form vlm-settings">
    <section class="effective-model-summary" aria-labelledby="effective-vlm-title">
      <h3 id="effective-vlm-title">当前生效</h3>
      <dl>
        <div><dt>解析器</dt><dd>{{ effectiveParser }}</dd><span>{{ effective?.configured ? '远程配置' : '本地回退' }}</span></div>
        <div><dt>模型</dt><dd>{{ effective?.model || '未配置' }}</dd><span>{{ effective?.configured ? '已配置' : '未配置 API' }}</span></div>
      </dl>
    </section>
    <p v-if="loading" class="setting-hint">正在读取配置…</p>
    <template v-else-if="draft">
      <div class="setting-row toggle-row"><label>开启 VLM</label><input v-model="draft.enabled" type="checkbox" :disabled="!editing" /><span class="hint-text">灌库优先使用 MinerU；断网时回退本地</span></div>
      <div class="setting-row toggle-row"><label>OCR</label><input v-model="draft.ocr_enabled" type="checkbox" :disabled="!editing" /><span class="hint-text">本地模式开启时会立即准备完整 OCR 模型</span></div>
      <div class="model-heading"><h3>MinerU 精准 API</h3></div>
      <div class="model-block vlm-model-block">
        <label for="vlm-key">API Key</label>
        <div class="key-row"><input id="vlm-key" v-model="draft.api_key" :type="showKey ? 'text' : 'password'" placeholder="MinerU API Key" autocomplete="off" spellcheck="false" :readonly="!editing" :class="{ readonly: !editing }" /><button class="toggle-key" type="button" @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button></div>
        <label for="vlm-model">模型</label>
        <select id="vlm-model" v-model="draft.model" :disabled="!editing" :class="{ readonly: !editing }"><option value="vlm">vlm</option><option value="pipeline">pipeline</option></select>
      </div>
      <div class="capacity-row vlm-limits-grid">
        <label>并发<input v-model.number="draft.max_concurrency" type="number" min="1" :max="Math.max(1, Math.floor(draft.result_rate_per_minute * draft.poll_interval_seconds / 60))" :readonly="!editing" :class="{ readonly: !editing }" /></label>
        <label>文件上限（MB）<input v-model.number="fileLimitMb" type="number" min="1" max="200" :readonly="!editing" :class="{ readonly: !editing }" /></label>
        <label>页数上限<input v-model.number="draft.max_pages" type="number" min="1" max="600" :readonly="!editing" :class="{ readonly: !editing }" /></label>
        <label>提交/分钟<input v-model.number="draft.submit_rate_per_minute" type="number" min="1" max="300" :readonly="!editing" :class="{ readonly: !editing }" /></label>
        <label>查询/分钟<input v-model.number="draft.result_rate_per_minute" type="number" min="1" max="1000" :readonly="!editing" :class="{ readonly: !editing }" /></label>
      </div>
      <div class="model-actions">
        <button v-if="!editing" class="edit-model-btn" type="button" @click="editing = true">{{ effective?.configured ? '编辑' : '配置' }}</button>
        <button v-if="editing" class="save-model-btn" type="button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        <button v-if="editing" class="edit-model-btn" type="button" @click="beginSavePreset">保存模型配置</button>
        <button v-if="editing" class="edit-model-btn" type="button" :disabled="checking" @click="check">{{ checking ? '检查中…' : '检查连接' }}</button>
        <button v-if="editing" class="cancel-model-btn" type="button" @click="load">取消</button>
        <span v-if="message" class="feedback">{{ message }}</span><span v-if="error" class="feedback error">{{ error }}</span>
      </div>
      <form v-if="presetNameOpen" class="preset-name-form" @submit.prevent="savePreset">
        <label for="vlm-preset-name">配置名称</label>
        <input id="vlm-preset-name" v-model="presetLabel" type="text" required autofocus placeholder="例如：MinerU 精准解析" />
        <div class="preset-name-actions">
          <button class="save-model-btn" type="submit">保存配置</button>
          <button class="cancel-model-btn" type="button" @click="presetNameOpen = false; presetLabel = ''">取消</button>
        </div>
      </form>
      <section class="saved-model-section">
        <h3>已保存的配置</h3>
        <p v-if="!presets.length" class="empty-hint">暂无已保存的 VLM 模型配置。</p>
        <div v-else class="saved-model-grid">
          <SavedModelConfigRow v-for="config in presets" :key="config.config_id" :title="config.label" :model="config.model" endpoint="MinerU 精准 API" :detail="`${Math.round(config.max_file_bytes / 1024 / 1024)} MB · ${config.max_pages} 页 · 并发 ${config.max_concurrency}`" icon="visibility">
            <template #actions><button type="button" @click="importPreset(config)">加载</button><button class="danger" type="button" @click="removePreset(config)">删除</button></template>
          </SavedModelConfigRow>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.vlm-model-block { display:grid; grid-template-columns:112px minmax(0,1fr); align-items:center; gap:var(--space-8) var(--space-10); }
.vlm-model-block > label { color:var(--color-text); font-size:calc(13px * var(--font-scale)); }
.vlm-model-block > select { min-width:0; height:28px; padding:0 var(--space-12); color:var(--color-text); font:calc(12px * var(--font-scale)) var(--font-mono); }
.vlm-model-block > select.readonly { pointer-events:none; opacity:.72; }
.vlm-limits-grid { grid-template-columns:repeat(2,minmax(0,1fr)); margin-top:var(--space-12); }
.vlm-limits-grid label { display:grid; grid-template-columns:112px minmax(0,1fr); align-items:center; gap:var(--space-10); color:var(--color-text); font-size:calc(13px * var(--font-scale)); }
.vlm-limits-grid input { width:100%; height:28px; padding:0 var(--space-12); color:var(--color-text); font:calc(12px * var(--font-scale)) var(--font-mono); }
.vlm-limits-grid input.readonly { color:var(--color-text-muted); cursor:default; }
.preset-name-form { display:grid; grid-template-columns:112px minmax(0,1fr) auto; align-items:center; gap:var(--space-10); margin-top:var(--space-10); padding-top:var(--space-10); border-top:1px solid var(--color-border); }
.preset-name-form > label { color:var(--color-text); font-size:calc(13px * var(--font-scale)); }
.preset-name-form > input { width:100%; height:28px; }
.preset-name-actions { display:flex; align-items:center; gap:var(--space-6); }
@media (max-width:768px) { .vlm-limits-grid { grid-template-columns:1fr; } }
@media (max-width:480px) { .vlm-model-block,.vlm-limits-grid label,.preset-name-form { grid-template-columns:1fr; gap:var(--space-4); }.preset-name-actions { margin-top:var(--space-4); } }
</style>
