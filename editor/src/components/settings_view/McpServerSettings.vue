<!-- Server lifecycle, domain exposure, scoped credentials, real verification and access records. -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import IcIcon from '@/components/common/IcIcon.vue'
import FormHeightTransition from '@/components/common/FormHeightTransition.vue'
import SettingsDisclosure from '@/components/common/SettingsDisclosure.vue'
import McpToolList from './McpToolList.vue'
import { createMcpCredential, fetchMcpRecords, revokeMcpCredential, rotateMcpCredential, saveMcpServer, verifyMcpServer } from '@/api/mcp'
import type { McpAccessRecord, McpCredential, McpSecret, McpServerConfig, McpServerState } from '@/api/mcp'
const props = defineProps<{ userId: string; state: McpServerState; libraries: Array<{ libraryId: string; name: string }> }>()
const emit = defineEmits<{ refresh: []; dirty: [value: boolean]; busy: [value: boolean] }>()
const draft = ref<McpServerConfig>({ ...props.state.config, tools: [...props.state.config.tools] })
const baseline = ref(JSON.stringify(draft.value))
const busy = ref(false), error = ref(''), feedback = ref(''), credentialOpen = ref(false)
const credentialDraft = ref({ name: '', library_id: props.libraries[0]?.libraryId || '', tools: [] as string[] })
const secret = ref<McpSecret | null>(null), verificationToken = ref('')
const records = ref<McpAccessRecord[]>([])
const serverDirty = computed(() => JSON.stringify(draft.value) !== baseline.value)
const dirty = computed(() => serverDirty.value || Boolean(secret.value) || Boolean(credentialOpen.value && credentialDraft.value.name))
const connectionConfig = computed(() => JSON.stringify({ mcpServers: { MetaWeave: { url: props.state.url, headers: { Authorization: `Bearer ${secret.value?.token || '<访问令牌>'}` } } } }, null, 2))
const domains = [{ key: 'knowledge', label: '知识库与文件' }, { key: 'library', label: '图书馆与文献' }, { key: 'memory', label: '长期记忆' }]
const stateNames: Record<string, string> = { running: '运行中', stopped: '已停止', failed: '启动失败' }
watch(() => props.state.config, value => { if (!serverDirty.value) { draft.value = { ...value, tools: [...value.tools] }; baseline.value = JSON.stringify(draft.value) } })
watch(dirty, value => emit('dirty', value), { immediate: true })
watch(busy, value => emit('busy', value))
/** Retain drafts and show local actionable errors for every operation. */
async function perform(action: () => Promise<void>) {
  busy.value = true; error.value = ''; feedback.value = ''
  try { await action() } catch (reason) { error.value = reason instanceof Error ? reason.message : '操作失败' }
  finally { busy.value = false }
}
/** Apply explicitly instead of restarting on input blur. */
async function save() {
  if (props.state.state === 'running' && !draft.value.enabled && !window.confirm('停止服务器？进行中的调用将等待完成，新调用会被拒绝。')) return
  await perform(async () => {
    const saved = await saveMcpServer(props.userId, draft.value)
    draft.value = { ...saved.config, tools: [...saved.config.tools] }; baseline.value = JSON.stringify(draft.value)
    if (saved.error) error.value = saved.error
    else feedback.value = saved.state === 'running' ? '配置已保存，服务器正在运行' : '配置已保存，服务器已停止'
    emit('refresh')
  })
}
function reset() { draft.value = { ...props.state.config, tools: [...props.state.config.tools] }; baseline.value = JSON.stringify(draft.value) }
async function create() {
  if (secret.value && !window.confirm('确认已保存当前新令牌？继续将覆盖显示。')) return
  await perform(async () => { secret.value = await createMcpCredential(props.userId, credentialDraft.value); credentialOpen.value = false; credentialDraft.value.name = ''; verificationToken.value = secret.value.token; emit('refresh') })
}
async function revoke(credential: McpCredential) {
  if (!window.confirm(`撤销 ${credential.name}？该凭据将无法继续访问。`)) return
  await perform(async () => { await revokeMcpCredential(props.userId, credential.credential_id); if (secret.value?.credential_id === credential.credential_id) clearSecret(); emit('refresh') })
}
async function rotate(credential: McpCredential) {
  if (secret.value && !window.confirm('确认已保存当前新令牌？继续将覆盖显示。')) return
  if (!window.confirm(`轮换 ${credential.name}？旧令牌立即失效。`)) return
  await perform(async () => { secret.value = await rotateMcpCredential(props.userId, credential.credential_id); verificationToken.value = secret.value.token; emit('refresh') })
}
/** Credentials live only in this temporary form and are cleared together. */
function clearSecret() { secret.value = null; verificationToken.value = '' }
async function copy(text: string) {
  try { await navigator.clipboard.writeText(text); feedback.value = '已复制' }
  catch { error.value = '剪贴板不可用，请选中文本手动复制' }
}
async function verify() { await perform(async () => { feedback.value = (await verifyMcpServer(props.userId, verificationToken.value)).message; emit('refresh') }) }
async function loadRecords() { await perform(async () => { records.value = (await fetchMcpRecords(props.userId)).records }) }
function selectReadOnly() { draft.value.tools = props.state.catalog.filter(t => !t.write).map(t => t.name) }
function startCredential() {
  credentialDraft.value = { name: '', library_id: props.libraries[0]?.libraryId || '', tools: props.state.config.tools.filter(name => props.state.catalog.some(t => t.name === name && !t.write)) }
  credentialOpen.value = true
}
defineExpose({ dirty })
</script>
<template>
  <section aria-label="MCP 服务器" class="setting-section mcp-server-settings">
    <form class="settings-model-form" @submit.prevent="save"><fieldset :disabled="busy">
      <section class="settings-module settings-block-surface" aria-label="服务器配置">
        <div class="mcp-toolbar"><h3>服务器配置</h3><span class="mcp-status" :class="state.state"><i aria-hidden="true"></i>{{ stateNames[state.state] || state.state }}</span></div>
        <div class="setting-row toggle-row"><label for="mcp-server-enabled">启用服务器</label><input id="mcp-server-enabled" v-model="draft.enabled" type="checkbox" /></div>
        <div class="setting-row"><label for="mcp-listen-host">监听地址</label><input id="mcp-listen-host" v-model="draft.host" required spellcheck="false" /></div>
        <div class="setting-row"><label for="mcp-listen-port">端口</label><input id="mcp-listen-port" v-model.number="draft.port" type="number" min="1024" max="65535" required /></div>
        <p v-if="state.error" class="mcp-inline-error" role="alert">{{ state.error }}</p>
      </section>
      <section class="settings-module settings-block-surface" aria-label="开放能力">
        <div class="mcp-toolbar"><h3>开放能力</h3><button class="mcp-text-button" type="button" @click="selectReadOnly"><IcIcon name="check" :size="16" /><span>选择只读工具</span></button></div>
        <SettingsDisclosure v-for="domain in domains" :key="domain.key" class="mcp-domain" :default-open="true" :label="domain.label"><McpToolList checkbox-style="todo" v-model="draft.tools" :tools="state.catalog.filter(t => t.domain === domain.key)" :label="`${domain.label}开放工具`" :disabled="busy" /></SettingsDisclosure>
        <div class="mcp-actions mcp-bottom-actions"><button class="mcp-outline-button" type="submit">保存并应用</button><button class="mcp-outline-button mcp-cancel-button" type="button" :disabled="!serverDirty" @click="reset">取消修改</button><span v-if="serverDirty" class="mcp-status">未保存</span></div>
      </section>
    </fieldset></form>
    <section class="settings-module settings-block-surface" aria-label="访问凭据">
      <div class="mcp-toolbar"><h3>访问凭据</h3><button class="mcp-text-button" type="button" :disabled="busy" @click="startCredential"><IcIcon name="add" :size="16" /><span>创建凭据</span></button></div>
      <p v-if="!state.credentials.length" class="mcp-empty">尚未创建凭据。外部客户端需持凭据访问。</p>
      <div v-for="credential in state.credentials" :key="credential.credential_id" class="mcp-credential-row"><div><strong>{{ credential.name }}</strong><code>{{ credential.token_prefix }}…</code><span>{{ libraries.find(l => l.libraryId === credential.grants.library_id)?.name || '知识库已移除' }}</span><span v-if="credential.revoked">已撤销</span></div><div class="mcp-actions"><button class="mcp-text-button" type="button" :disabled="busy || credential.revoked" @click="rotate(credential)"><IcIcon name="refresh" :size="16" /><span>轮换</span></button><button class="mcp-text-button danger" type="button" :disabled="busy || credential.revoked" @click="revoke(credential)"><IcIcon name="trash" :size="16" /><span>撤销</span></button></div><SettingsDisclosure label="授权工具"><ul><li v-for="name in credential.grants.tools" :key="name">{{ state.catalog.find(t => t.name === name)?.title || name }}</li></ul></SettingsDisclosure></div>
      <FormHeightTransition :watch-key="`${credentialOpen}-${Boolean(secret)}`">
        <form v-if="credentialOpen" class="mcp-editor" @submit.prevent="create"><fieldset :disabled="busy"><h3>创建凭据</h3><div class="setting-row"><label for="mcp-credential-name">名称</label><input id="mcp-credential-name" v-model="credentialDraft.name" required maxlength="128" /></div><div class="setting-row"><label for="mcp-credential-library">知识库范围</label><select id="mcp-credential-library" v-model="credentialDraft.library_id" required><option v-for="library in libraries" :key="library.libraryId" :value="library.libraryId">{{ library.name }}</option></select></div><McpToolList checkbox-style="todo" v-model="credentialDraft.tools" :tools="state.catalog" label="凭据授权工具" :disabled="busy" /><div class="mcp-actions mcp-bottom-actions"><button class="mcp-outline-button" type="submit" :disabled="!credentialDraft.tools.length">创建</button><button class="mcp-outline-button mcp-cancel-button" type="button" @click="credentialOpen = false">取消</button></div></fieldset></form>
        <div v-if="secret" class="mcp-secret"><h4>新访问令牌</h4><p>仅显示本次。请保存到外部客户端，关闭后无法再次查看。</p><textarea :value="secret.token" readonly aria-label="新访问令牌" rows="2" spellcheck="false"></textarea><div class="mcp-actions mcp-bottom-actions"><button class="mcp-outline-button" type="button" @click="copy(secret.token)">复制令牌</button><button class="mcp-outline-button mcp-cancel-button" type="button" @click="clearSecret">已保存，关闭</button></div></div>
      </FormHeightTransition>
    </section>
    <SettingsDisclosure class="mcp-connection-config settings-module settings-block-surface" :default-open="true" label="接入配置"><div class="mcp-address"><code>{{ state.url }}</code><button class="mcp-text-button" type="button" @click="copy(state.url)"><IcIcon name="copy" :size="16" /><span>复制地址</span></button></div><textarea :value="connectionConfig" readonly aria-label="客户端接入配置" class="mcp-code" rows="8" spellcheck="false"></textarea><button class="mcp-outline-button" type="button" @click="copy(connectionConfig)">复制配置</button><p v-if="state.config.host === '0.0.0.0' || state.config.host === '::'" class="mcp-note">其他设备接入时，将回环地址替换为本机可达地址。</p></SettingsDisclosure>
    <div class="mcp-editor settings-module settings-block-surface"><h3>验证服务</h3><div class="setting-row"><label for="mcp-verify-token">访问令牌</label><input id="mcp-verify-token" v-model="verificationToken" type="password" autocomplete="off" /></div><button class="mcp-outline-button" type="button" aria-label="验证初始化与只读调用" :disabled="busy || state.state !== 'running' || !verificationToken" @click="verify">验证服务</button></div>
    <SettingsDisclosure class="mcp-records settings-module settings-block-surface" @toggle="$event && loadRecords()" label="最近访问"><template #actions><button class="mcp-text-button" type="button" :disabled="busy" @click="loadRecords"><IcIcon name="refresh" :size="16" /><span>刷新记录</span></button></template><p v-if="!records.length" class="mcp-empty">暂无调用记录。</p><div v-for="record in records" :key="record.record_id" class="mcp-record-row"><time>{{ new Date(record.created_at).toLocaleString() }}</time><code>{{ record.tool_name }}</code><span>{{ record.status === 'success' ? '成功' : record.status === 'denied' ? '拒绝' : '失败' }} · {{ record.duration_ms }} ms</span><span v-if="record.message">{{ record.message }}</span></div></SettingsDisclosure>
    <p v-if="busy" class="feedback" role="status">正在处理…</p><p v-if="feedback" class="feedback" role="status">{{ feedback }}</p><p v-if="error" class="feedback error" role="alert">{{ error }}</p>
  </section>
</template>
