<!--
  安全设置面板：编辑敏感词库。

  Usage:
  读取并编辑 resources/safety/sensitive_words.json，以分类卡片展示，
  每个敏感词和正则模式以 Chip/块 显示，支持行内增删。
  支持一键关闭敏感词库和整个安全审核系统。
-->
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { getVaultDebugMasterPassword, getVaultStatus, resetVaultPassword, type VaultStatusResponse } from '@/api/vault'
import VaultPasswordResetDialog from '@/components/vault_view/VaultPasswordResetDialog.vue'
import { fetchSensitiveWords, saveSensitiveWords } from '@/api/settings'
import { useSettingsStore } from '@/stores/settings'

interface CategoryData {
  name: string
  risk_level: string
  block: boolean
  exact: string[]
  regex: string[]
}

interface WordData {
  _description: string
  _sensitive_words_disabled: boolean
  _safety_disabled: boolean
  categories: Record<string, CategoryData>
}

const data = reactive<WordData>({
  _description: '敏感词库,按类别分组。支持 exact 精确匹配 + regex 正则匹配',
  _sensitive_words_disabled: false,
  _safety_disabled: false,
  categories: {},
})

const settingsStore = useSettingsStore()
const categoryKeys = ref<string[]>([])
const newCategoryKey = ref('')
const newCategoryName = ref('')
const newExactText = ref<Record<string, string>>({})
const newRegexText = ref<Record<string, string>>({})
const saving = ref(false)
const saveMsg = ref('')
const loading = ref(true)
const vaultDebugLoading = ref(false)
const vaultDebug = ref<VaultStatusResponse | null>(null)
const vaultPasswordDebug = ref('')
const vaultDebugPasswordVisible = ref(false)
const vaultResetOpen = ref(false)
const vaultAdminResetOpen = ref(false)
const vaultResetSaving = ref(false)

const categoryEntries = computed(() => categoryKeys.value
  .map((key) => ({ key, category: data.categories[key] }))
  .filter((entry): entry is { key: string; category: CategoryData } => Boolean(entry.category)))
const safetyDisabled = computed(() => data._safety_disabled)
const sensitiveDisabled = computed(() => data._sensitive_words_disabled)

function showMessage(text: string, duration = 2000) {
  saveMsg.value = text
  setTimeout(() => { saveMsg.value = '' }, duration)
}

async function loadData() {
  loading.value = true
  try {
    const raw = await fetchSensitiveWords()
    if (raw && typeof raw === 'object') {
      const r = raw as Record<string, unknown>
      if (typeof r._description === 'string') data._description = r._description
      data._sensitive_words_disabled = r._sensitive_words_disabled === true
      data._safety_disabled = r._safety_disabled === true
      const cats = r.categories
      if (cats && typeof cats === 'object') {
        data.categories = cats as Record<string, CategoryData>
      }
    }
    categoryKeys.value = Object.keys(data.categories)
  } catch {
    showMessage('加载失败')
  } finally {
    loading.value = false
  }
}

function addExact(catKey: string) {
  const text = (newExactText.value[catKey] || '').trim()
  if (!text) return
  const cat = data.categories[catKey]
  if (cat && !cat.exact.includes(text)) {
    cat.exact.push(text)
  }
  newExactText.value[catKey] = ''
}

function removeExact(catKey: string, index: number) {
  const cat = data.categories[catKey]
  if (cat) cat.exact.splice(index, 1)
}

function addRegex(catKey: string) {
  const text = (newRegexText.value[catKey] || '').trim()
  if (!text) return
  const cat = data.categories[catKey]
  if (cat && !cat.regex.includes(text)) {
    cat.regex.push(text)
  }
  newRegexText.value[catKey] = ''
}

function removeRegex(catKey: string, index: number) {
  const cat = data.categories[catKey]
  if (cat) cat.regex.splice(index, 1)
}

function addCategory() {
  const key = newCategoryKey.value.trim()
  const name = newCategoryName.value.trim()
  if (!key || !name) return
  if (data.categories[key]) {
    showMessage('分类键已存在')
    return
  }
  data.categories[key] = {
    name,
    risk_level: 'high',
    block: true,
    exact: [],
    regex: [],
  }
  categoryKeys.value = Object.keys(data.categories)
  newCategoryKey.value = ''
  newCategoryName.value = ''
}

function removeCategory(catKey: string) {
  delete data.categories[catKey]
  categoryKeys.value = Object.keys(data.categories)
}

function handleKeydownInput(e: KeyboardEvent, catKey: string, type: 'exact' | 'regex') {
  if (e.key === 'Enter') {
    e.preventDefault()
    if (type === 'exact') addExact(catKey)
    else addRegex(catKey)
  }
}

async function handleSave() {
  saving.value = true
  saveMsg.value = ''
  try {
    const payload: Record<string, unknown> = {
      _description: data._description,
      _sensitive_words_disabled: data._sensitive_words_disabled,
      _safety_disabled: data._safety_disabled,
      categories: data.categories,
    }
    await saveSensitiveWords(payload)
    showMessage('已保存')
  } catch {
    showMessage('保存失败')
  } finally {
    saving.value = false
  }
}

async function handleFetchVaultPasswordDebug() {
  const userId = settingsStore.profile.userId
  if (!userId) {
    vaultPasswordDebug.value = '当前没有用户 ID'
    return
  }
  vaultDebugLoading.value = true
  vaultPasswordDebug.value = ''
  try {
    const [status, debug] = await Promise.all([
      getVaultStatus(userId),
      getVaultDebugMasterPassword(userId),
    ])
    vaultDebug.value = status
    vaultPasswordDebug.value = debug.available ? debug.master_password : debug.message
    vaultDebugPasswordVisible.value = debug.available
  } catch (error) {
    vaultPasswordDebug.value = error instanceof Error ? error.message : '读取密码库调试信息失败'
    vaultDebugPasswordVisible.value = false
  } finally {
    vaultDebugLoading.value = false
  }
}

async function submitVaultPasswordReset(withOldPassword: boolean, oldPassword: string, nextPassword: string, confirmation: string) {
  const userId = settingsStore.profile.userId
  if (!userId) return showMessage('当前没有用户 ID')
  if (nextPassword.length < 8) return showMessage('新密码至少需要 8 位')
  if (nextPassword !== confirmation) return showMessage('两次新密码不一致')
  vaultResetSaving.value = true
  try {
    await resetVaultPassword(userId, nextPassword, withOldPassword ? oldPassword : '')
    vaultResetOpen.value = false
    vaultAdminResetOpen.value = false
    vaultPasswordDebug.value = ''
    showMessage('密码库密码已重设，请使用新密码重新解锁')
  } catch (error) {
    showMessage(error instanceof Error ? error.message : '重设密码库密码失败')
  } finally {
    vaultResetSaving.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <div class="setting-section">
    <h3>密码库</h3>
    <div class="vault-debug-card">
      <div class="vault-debug-main">
        <strong>密码库调试</strong>
        <span>当前用户: {{ settingsStore.profile.userId || '未设置' }}</span>
        <span v-if="vaultDebug">
          状态: {{ vaultDebug.configured ? '已设置主密码' : '未设置主密码' }} · 条目 {{ vaultDebug.item_count }}
        </span>
      </div>
      <button class="save-model-btn" :disabled="vaultDebugLoading" type="button" @click="handleFetchVaultPasswordDebug">
        {{ vaultDebugLoading ? '获取中...' : '获取密码库主密码' }}
      </button>
      <button class="secondary-model-btn" type="button" @click="vaultAdminResetOpen = !vaultAdminResetOpen">重设密码库密码</button>
      <button class="secondary-model-btn vault-reset-toggle vault-reset-inside" type="button" @click="vaultResetOpen = true">重置密码</button>
      <p v-if="vaultPasswordDebug" class="vault-debug-result" :class="{ secret: vaultDebugPasswordVisible }">
        {{ vaultDebugPasswordVisible ? `主密码: ${vaultPasswordDebug}` : vaultPasswordDebug }}
      </p>
    </div>
    <button class="secondary-model-btn vault-reset-toggle" type="button" @click="vaultResetOpen = true">重置密码</button>
    <VaultPasswordResetDialog :open="vaultResetOpen" :saving="vaultResetSaving" :require-old-password="true" @close="vaultResetOpen = false" @submit="(oldPassword, nextPassword, confirmation) => submitVaultPasswordReset(true, oldPassword, nextPassword, confirmation)" />
    <VaultPasswordResetDialog :open="vaultAdminResetOpen" :saving="vaultResetSaving" :require-old-password="false" @close="vaultAdminResetOpen = false" @submit="(_oldPassword, nextPassword, confirmation) => submitVaultPasswordReset(false, '', nextPassword, confirmation)" />

    <div class="safety-heading-row">
      <h3>安全审核词库</h3>
      <button class="save-model-btn" :disabled="saving" @click="handleSave">
        {{ saving ? '保存中...' : '保存全部' }}
      </button>
      <span v-if="saveMsg" class="feedback">{{ saveMsg }}</span>
    </div>
    <p class="safety-desc">{{ data._description }}</p>

    <!-- 全局开关 -->
    <div class="safety-global-toggles">
      <div class="safety-global-row" :class="{ 'safety-global-risk': sensitiveDisabled }">
        <label class="safety-global-label">敏感词库</label>
        <input
          :checked="sensitiveDisabled"
          type="checkbox"
          class="safety-toggle safety-toggle-danger"
          @change="data._sensitive_words_disabled = ($event.target as HTMLInputElement).checked"
        />
        <span class="safety-global-text">
          {{ sensitiveDisabled ? '已关闭 — 敏感词检查通过,不再拦截' : '开启中' }}
        </span>
      </div>
      <div class="safety-global-row" :class="{ 'safety-global-risk': safetyDisabled }">
        <label class="safety-global-label">安全审核系统</label>
        <input
          :checked="safetyDisabled"
          type="checkbox"
          class="safety-toggle safety-toggle-danger"
          @change="data._safety_disabled = ($event.target as HTMLInputElement).checked"
        />
        <span class="safety-global-text">
          {{ safetyDisabled ? '已关闭 — 三大审核层全部绕过' : '开启中' }}
        </span>
      </div>
      <div v-if="safetyDisabled" class="safety-global-warning">
        ⚠ 安全审核系统已关闭，敏感词库、意图审核、输出审核全部绕过
      </div>
    </div>

    <!-- Save bar -->
    <div class="safety-actions">
      <button class="save-model-btn" :disabled="saving" @click="handleSave">
        {{ saving ? '保存中...' : '保存全部' }}
      </button>
      <span v-if="saveMsg" class="feedback">{{ saveMsg }}</span>
    </div>

    <!-- Loading -->
    <p v-if="loading" class="safety-loading">加载中...</p>

    <!-- Category list -->
    <div v-for="entry in categoryEntries" :key="entry.key" class="safety-category-card">
      <div class="safety-cat-header">
        <strong class="safety-cat-key">{{ entry.key }}</strong>
        <input
          v-model="entry.category.name"
          class="safety-cat-name-input"
          placeholder="分类名称"
          spellcheck="false"
        />
        <button class="entry-del" title="删除此分类" @click="removeCategory(entry.key)">&times;</button>
      </div>

      <div class="safety-cat-meta">
        <label class="safety-label">风险等级</label>
        <select v-model="entry.category.risk_level" class="safety-select">
          <option value="high">高</option>
          <option value="medium">中</option>
          <option value="low">低</option>
        </select>
        <label class="safety-label" style="margin-left: 16px">拦截</label>
        <input
          :checked="entry.category.block"
          type="checkbox"
          class="safety-toggle"
          @change="entry.category.block = ($event.target as HTMLInputElement).checked"
        />
      </div>

      <!-- Exact words -->
      <div class="safety-subsection">
        <span class="safety-subtitle">精确匹配</span>
        <div v-if="entry.category.exact.length" class="safety-chip-row">
          <span
            v-for="(word, i) in entry.category.exact"
            :key="i"
            class="safety-chip"
          >
            <span class="safety-chip-text">{{ word }}</span>
            <button class="safety-chip-del" @click="removeExact(entry.key, i)">&times;</button>
          </span>
        </div>
        <div class="safety-chip-input-row">
          <input
            v-model="newExactText[entry.key]"
            class="safety-chip-input safety-chip-input-exact"
            placeholder="添加精确匹配词"
            spellcheck="false"
            @keydown="handleKeydownInput($event, entry.key, 'exact')"
          />
          <button class="add-btn" :disabled="!(newExactText[entry.key] || '').trim()" @click="addExact(entry.key)">添加</button>
        </div>
      </div>

      <!-- Regex patterns -->
      <div class="safety-subsection">
        <span class="safety-subtitle">正则匹配</span>
        <div v-if="entry.category.regex.length" class="safety-chip-row">
          <span
            v-for="(pattern, i) in entry.category.regex"
            :key="i"
            class="safety-chip safety-chip-regex"
          >
            <span class="safety-chip-text safety-chip-code">{{ pattern }}</span>
            <button class="safety-chip-del" @click="removeRegex(entry.key, i)">&times;</button>
          </span>
        </div>
        <div class="safety-chip-input-row">
          <input
            v-model="newRegexText[entry.key]"
            class="safety-chip-input safety-chip-input-code"
            placeholder="添加正则模式"
            spellcheck="false"
            @keydown="handleKeydownInput($event, entry.key, 'regex')"
          />
          <button class="add-btn" :disabled="!(newRegexText[entry.key] || '').trim()" @click="addRegex(entry.key)">添加</button>
        </div>
      </div>
    </div>

    <!-- Add new category -->
    <div class="safety-add-cat">
      <h3 style="margin-top: 20px">添加分类</h3>
      <div class="safety-add-cat-row">
        <input
          v-model="newCategoryKey"
          class="safety-chip-input"
          placeholder="分类键（英文，如 violence）"
          spellcheck="false"
          style="width: 200px"
        />
        <input
          v-model="newCategoryName"
          class="safety-chip-input"
          placeholder="分类名称（如 暴力）"
          spellcheck="false"
          style="width: 200px"
        />
        <button class="add-btn" :disabled="!newCategoryKey.trim() || !newCategoryName.trim()" @click="addCategory">
          添加分类
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.vault-debug-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: var(--space-8);
  align-items: center;
  margin-bottom: var(--space-16);
  padding: var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-canvas);
}

.secondary-model-btn {
  height: 28px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  padding: 0 var(--space-10);
  font: inherit;
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
}

.secondary-model-btn:hover { border-color: var(--color-primary); color: var(--color-primary); }
.vault-reset-toggle { margin: 0 0 var(--space-8); }


.vault-debug-main {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.vault-debug-main strong {
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
}

.vault-debug-main span,
.vault-debug-result {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.45;
}

.vault-debug-result {
  grid-column: 1 / -1;
  margin: 0;
}

.vault-debug-result.secret {
  color: var(--color-danger);
  font-family: var(--font-code);
  user-select: text;
}

.safety-desc {
  margin: -4px 0 var(--space-10);
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
  line-height: 1.45;
}

.safety-loading {
  color: var(--color-text-muted);
  font-size: calc(12px * var(--font-scale));
}

.safety-actions {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-14);
}

/* ---- 全局开关 ---- */

.safety-global-toggles {
  margin-bottom: var(--space-10);
  padding: var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-canvas);
}

.safety-global-row {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-6) 0;
}

.safety-global-row + .safety-global-row {
  border-top: 1px solid var(--color-border);
}

.safety-global-label {
  flex-shrink: 0;
  width: 110px;
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
  font-weight: 600;
}

.safety-global-text {
  color: var(--color-text-muted);
  font-size: calc(11px * var(--font-scale));
}

.safety-global-risk .safety-global-text {
  color: var(--color-danger);
}

.safety-global-warning {
  margin-top: var(--space-6);
  padding: var(--space-6) var(--space-8);
  border-radius: var(--radius-sm);
  background: rgba(255, 95, 95, 0.1);
  color: var(--color-danger);
  font-size: calc(12px * var(--font-scale));
  line-height: 1.4;
}

/* ---- 分类卡片 ---- */

.safety-category-card {
  margin-bottom: var(--space-12);
  padding: var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-canvas);
}

.safety-cat-header {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-bottom: var(--space-8);
}

.safety-cat-key {
  flex-shrink: 0;
  font-size: calc(11px * var(--font-scale));
  color: var(--color-text-muted);
  font-family: var(--font-code);
  text-transform: lowercase;
}

.safety-cat-name-input {
  flex: 1;
  height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text);
  font-size: calc(13px * var(--font-scale));
  outline: none;
}

.safety-cat-name-input:focus {
  border-color: var(--color-primary);
}

.safety-cat-meta {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  margin-bottom: var(--space-10);
}

.safety-label {
  flex-shrink: 0;
  color: var(--color-text-secondary);
  font-size: calc(12px * var(--font-scale));
}

.safety-select {
  height: 26px;
  padding: 0 var(--space-8);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: calc(12px * var(--font-scale));
  outline: none;
}

.safety-toggle {
  position: relative;
  width: 32px;
  height: 20px;
  margin: 0;
  flex: none;
  appearance: none;
  -webkit-appearance: none;
  outline: none;
  cursor: pointer;
  background: transparent;
  border: none;
  z-index: 0;
  padding: 0;
}

.safety-toggle::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 2px;
  right: 2px;
  height: 6px;
  transform: translateY(-50%);
  border-radius: 999px;
  background: var(--color-text-muted);
  opacity: 0.3;
  transition: opacity 0.3s, background 0.3s;
  pointer-events: none;
}

.safety-toggle::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--color-text-tertiary);
  box-shadow: inset 0 0 0 3px var(--color-canvas);
  transition: left 0.3s, background 0.3s, box-shadow 0.2s;
  pointer-events: none;
}

.safety-toggle:checked::before {
  opacity: 1;
  background: var(--color-primary);
}

.safety-toggle:checked::after {
  left: 14px;
  background: var(--color-primary);
  box-shadow: none;
}

.safety-toggle-danger:checked::before {
  background: var(--color-danger) !important;
}

.safety-toggle-danger:checked::after {
  background: var(--color-danger) !important;
  left: 14px;
  box-shadow: none !important;
}

.safety-subsection {
  margin-bottom: var(--space-8);
}

.safety-subtitle {
  display: block;
  margin-bottom: var(--space-4);
  color: var(--color-text-secondary);
  font-size: calc(11px * var(--font-scale));
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.safety-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.safety-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  height: 26px;
  padding: 0 var(--space-8);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  font-size: calc(12px * var(--font-scale));
}

.safety-chip-regex {
  border-color: var(--color-primary-soft);
  background: var(--color-primary-softer);
}

.safety-chip-text {
  color: var(--color-text);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.safety-chip-code {
  font-family: var(--font-code);
  font-size: calc(11px * var(--font-scale));
}

.safety-chip-del {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted);
  font-size: calc(13px * var(--font-scale));
  cursor: pointer;
}

.safety-chip-del:hover {
  color: var(--color-danger);
  background: rgba(255, 95, 95, 0.08);
}

.safety-chip-input-row {
  display: flex;
  gap: var(--space-4);
}

.safety-chip-input {
  flex: 1;
  height: 28px;
  padding: 0 var(--space-10);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  color: var(--color-text);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  outline: none;
}

.safety-chip-input:focus {
  border-color: var(--color-primary);
}

.safety-chip-input-code {
  font-family: var(--font-code);
  font-size: calc(11px * var(--font-scale));
}

.safety-add-cat {
  margin-top: var(--space-4);
}

.safety-add-cat-row {
  display: flex;
  gap: var(--space-6);
  align-items: center;
  flex-wrap: wrap;
}
</style>

<style scoped>
.vault-debug-card,
.safety-global-toggles,
.safety-category-card {
  border: 0;
  outline: 2px solid var(--workspace-panel-outline);
  outline-offset: 2px;
  border-radius: 28px;
  box-shadow: 0 0 0 2px var(--library-form-ring);
}

.vault-debug-card {
  position: relative;
  padding-bottom: var(--space-16);
}

.vault-reset-inside {
  grid-column: 1 / -1;
  justify-self: end;
  margin-top: var(--space-4);
}

.setting-section > .vault-reset-toggle {
  display: none;
}

.safety-heading-row {
  display: flex;
  align-items: center;
  gap: var(--space-8);
}

.safety-heading-row h3 {
  margin-bottom: 0;
}

.safety-heading-row .save-model-btn {
  margin-left: auto;
}

.safety-actions {
  display: none;
}

.safety-global-row + .safety-global-row {
  border-top: 0;
}

.secondary-model-btn {
  border: 0;
  box-shadow: 0 0 0 3px var(--library-form-ring);
}

.safety-chip {
  border: 0;
  box-shadow: 0 0 0 2px var(--library-form-ring);
}

.safety-chip-input-exact {
  flex: 0 0 66.666%;
  width: 66.666%;
}
</style>
