<!--
  Right-side Agent panel.

  Usage:
  Hosts the editor Agent chat. It reuses the console chat/session backend and
  keeps observability and settings outside of the editor side panel.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'

import IcIcon from '@/components/common/IcIcon.vue'
import darkTitle from '@/assets/images/暗色标题.png'
import lightTitle from '@/assets/images/亮色标题.png'
import lightLogo from '@/assets/images/亮色无底图标.png'
import darkLogo from '@/assets/images/暗色无底图标.png'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import ChatInput from '@/components/editor_workspace/agent_chat/ChatInput.vue'
import ContextCompressionStatus from '@/components/editor_workspace/agent_chat/ContextCompressionStatus.vue'
import AgentPanelTitlebar from '@/components/editor_workspace/agent_chat/AgentPanelTitlebar.vue'
import LoaderCube from '@/components/editor_workspace/agent_chat/LoaderCube.vue'
import MessageList from '@/components/editor_workspace/agent_chat/MessageList.vue'
import SessionDrawer from '@/components/editor_workspace/agent_chat/SessionDrawer.vue'
import StreamingIndicator from '@/components/editor_workspace/agent_chat/StreamingIndicator.vue'
import TaskListDrawer from '@/components/editor_workspace/agent_chat/TaskListDrawer.vue'
import ChildAgentPanel from '@/components/editor_workspace/agent_chat/ChildAgentPanel.vue'
import ChildAgentConversationDrawer from '@/components/editor_workspace/agent_chat/ChildAgentConversationDrawer.vue'
import EnvironmentChangeCard from '@/components/editor_workspace/agent_chat/EnvironmentChangeCard.vue'
import ChangeDetailDrawer from '@/components/editor_workspace/agent_chat/ChangeDetailDrawer.vue'
import { cancelSessionChatAcrossWindows, useChatStore, useSessionChatStore } from '@/stores/chat'
import type { AgentUploadedAttachment } from '@/stores/chat'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { useSkillsStore } from '@/stores/skills'
import { useFavoritesStore } from '@/stores/favorites'
import { useTaskListStore } from '@/stores/taskList'
import { useWorkspaceStore } from '@/stores/workspace'
import type { AgentAccessMode, AgentLoopMode, ChildAgentRecord } from '@/api/agent'
import { fetchSessionState, type SessionRecord } from '@/api/session'
import { fetchAgentAttachment, uploadAgentAttachment } from '@/api/agent'
import { DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS, fetchLLMConfig, fetchSensitiveWords, saveSensitiveWords } from '@/api/settings'
import type { AgentChangeSnapshot } from '@/api/agentChanges'

type MessageListApi = {
  scrollToBottom: (options?: ScrollToOptions) => void
}

const settingsStore = useSettingsStore()
const sessionStore = useSessionStore()
const skillsStore = useSkillsStore()
const favoritesStore = useFavoritesStore()
const taskListStore = useTaskListStore()
const workspaceStore = useWorkspaceStore()
const props = withDefaults(defineProps<{
  mode?: 'panel' | 'page'
  /** 在嵌入式场景中打开指定的持久化任务会话。 */
  sessionId?: string
  /** Silently follow messages persisted by an external queue worker. */
  liveSync?: boolean
  /** Let Electron use the shared panel titlebar as a native drag region. */
  panelDraggable?: boolean
  /** Use panel density as the mobile Agent main view rather than as a docked sidebar. */
  mobileMain?: boolean
}>(), {
  mode: 'panel',
  sessionId: '',
  liveSync: false,
  panelDraggable: false,
  mobileMain: false,
})
// Queue dialogs mount a complete Agent panel for a fixed task session.  Give
// it its own stream state so opening it cannot replace or cancel the page chat.
const initialSessionId = props.sessionId || sessionStore.currentSessionId || ''
const chatStore = shallowRef(initialSessionId ? useSessionChatStore(initialSessionId) : useChatStore())
const emit = defineEmits<{
  expand: []
}>()
const sessionDrawerOpen = ref(false)
// 融合侧边栏(任务列表 + 子 Agent)统一开关
const agentSidebarOpen = ref(false)
// 两张卡片独立可见:各自可叉掉,不影响另一张;仅剩一张时再叉掉则收起整个侧边栏
const taskListCardOpen = ref(false)
const childAgentCardOpen = ref(false)
const environmentCardOpen = ref(false)
const changeDetailOpen = ref(false)
const environmentWorkspaceOpen = computed(() => (
  environmentCardOpen.value || taskListCardOpen.value || childAgentCardOpen.value
))
const selectedChangeSnapshot = ref<AgentChangeSnapshot | null>(null)
const selectedChildAgent = ref<ChildAgentRecord | null>(null)
const isBootstrapping = ref(false)
const referenceText = ref('')
const messageListRef = ref<MessageListApi | null>(null)
const isMessageListAtBottom = ref(true)
const sessionLoading = ref(false)
let taskHistoryPollTimer: number | null = null
const loadingSessionId = ref('')
const remoteSessionPending = ref('')
const contextWindowTokens = ref(DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS)
const displayedMaxContextTokens = computed(() => (
  chatStore.value.contextUsage?.capacity_source === 'conservative_fallback'
    ? contextWindowTokens.value
    : chatStore.value.contextUsage?.max_context_tokens ?? contextWindowTokens.value
))
const safetyDisabled = ref(false)
const safetyLoading = ref(false)
const dragDepth = ref(0)
const attachmentPollTimers = new Map<string, number>()
const modeSwitchRef = ref<HTMLElement | null>(null)
const loopModeMenuOpen = ref(false)
const skillMenuOpen = ref(false)
const modeIndicatorStyle = computed(() => {
  if (settingsStore.chatMode === 'tool') {
    return { width: 'calc(50% - 2px)', transform: 'translateX(0)' }
  }
  return { width: 'calc(50% - 2px)', transform: 'translateX(100%) translateX(2px)' }
})

const userId = computed(() => settingsStore.profile.userId)
const activeSessionId = computed(() => props.sessionId || sessionStore.currentSessionId)
/** Switches only this panel's chat state; existing session streams keep running. */
function useActiveSessionChat(sessionId: string) {
  if (!props.sessionId && sessionId) chatStore.value = useSessionChatStore(sessionId)
}
const isDark = computed(() => settingsStore.isDark)
const welcomeTitleSrc = computed(() => isDark.value ? darkTitle : lightTitle)
const logoSrc = computed(() => isDark.value ? darkLogo : lightLogo)
const hasMessages = computed(() => chatStore.value.messages.filter((m) => m.role !== 'system').length > 0)
const hasStreamingContent = computed(() => !!chatStore.value.lastMessage?.content)
const isAttachmentDropActive = computed(() => dragDepth.value > 0)

/** Start or stop silent history synchronization for an externally-run task. */
function syncTaskHistoryPolling(enabled: boolean) {
  if (taskHistoryPollTimer !== null) {
    window.clearInterval(taskHistoryPollTimer)
    taskHistoryPollTimer = null
  }
  if (!enabled || !props.sessionId) return
  taskHistoryPollTimer = window.setInterval(() => {
    if (userId.value) void chatStore.value.syncHistory(props.sessionId!, userId.value)
  }, 1500)
}
const sessionTitle = computed(() => {
  const name = sessionStore.sessions.find((session) => session.session_id === activeSessionId.value)?.session_name || 'new session'
  return name.replace(/^标题:/, '').trim()
})
/** Visible even with the history drawer collapsed, so parallel runs are never hidden. */
const runningSessions = computed(() => sessionStore.streamingSessionIds
  .map((sessionId) => sessionStore.sessions.find((session) => session.session_id === sessionId))
  .filter((session): session is SessionRecord => Boolean(session)))
function runningSessionName(session: SessionRecord) {
  return (session.session_name || session.session_id.slice(0, 8)).replace(/^标题:/, '').trim()
}
const chatModeLabel = computed(() => settingsStore.chatMode === 'chat' ? 'chat' : 'tool')
const currentLargeModelName = ref('')
const sessionSources = computed(() => {
  const unique = new Map<string, import('@/stores/chat').SourceItem>()
  for (const message of chatStore.value.messages) {
    const citationMap = message.metadata?.citation_map
    if (!citationMap || typeof citationMap !== 'object' || Array.isArray(citationMap)) continue
    for (const source of Object.values(citationMap)) {
      if (!source || typeof source !== 'object' || Array.isArray(source)) continue
      const record = source as Record<string, unknown>
      const uri = typeof record.source_uri === 'string' ? record.source_uri : ''
      if (!uri || unique.has(uri)) continue
      unique.set(uri, {
        source_uri: uri,
        content: typeof record.content === 'string' ? record.content : '',
        source: typeof record.source === 'string' ? record.source : undefined,
        title: typeof record.title === 'string' ? record.title : undefined,
      })
    }
  }
  return [...unique.values()]
})
const modelConfigLabel = computed(() => currentLargeModelName.value || '配置模型')
const loopModeOptions: Array<{ value: AgentLoopMode; label: string }> = [
  { value: 'auto', label: 'Auto' },
  { value: 'simple', label: 'Simple' },
  { value: 'react', label: 'ReAct' },
  { value: 'plan', label: 'Plan' },
]
const selectedLoopModeLabel = computed(() => {
  return loopModeOptions.find((option) => option.value === settingsStore.agentLoopMode)?.label || 'Auto'
})
const extractedSkills = computed(() => {
  return [...skillsStore.skills].sort((a, b) => a.name.localeCompare(b.name))
})
const knowledgeTitle = computed(() => {
  const name = settingsStore.activeKnowledgeLibrary?.name?.trim()
  if (name) return name
  const parts = settingsStore.profile.knowledgeDir.replace(/\\/g, '/').split('/').filter(Boolean)
  return parts[parts.length - 1] || '未命名'
})

async function reloadSessions() {
  if (!userId.value) {
    sessionStore.clearSelection()
    chatStore.value.clear()
    return
  }
  isBootstrapping.value = true
  const sessionIdBeforeLoad = activeSessionId.value
  try {
    await sessionStore.load(userId.value)
    // Do not let the mount-time list request erase a conversation created or
    // selected while that request was in flight.
    if (sessionIdBeforeLoad && activeSessionId.value === sessionIdBeforeLoad) {
      await loadSelectedSessionHistory(sessionIdBeforeLoad)
    }
  } finally {
    isBootstrapping.value = false
  }
}

/** Enters an unpersisted blank draft; the first user bubble creates its session. */
function startNewConversationDraft() {
  if (props.sessionId) return
  sessionStore.clearSelection()
  chatStore.value = useChatStore()
  chatStore.value.clear()
  if (props.mode !== 'page') {
    sessionDrawerOpen.value = false
  }
}

async function selectSession(sessionId: string, broadcast = true, loadHistory = true) {
  // A queue detail is pinned to its task thread.  Navigating its session list
  // must not replace the task conversation currently being inspected.
  if (props.sessionId) return
  if (!loadHistory) remoteSessionPending.value = sessionId
  sessionStore.select(sessionId, broadcast)
  useActiveSessionChat(sessionId)
  if (loadHistory) await loadSelectedSessionHistory(sessionId)
}

async function loadSelectedSessionHistory(sessionId: string, force = false) {
  if (!userId.value || loadingSessionId.value === sessionId || (!force && chatStore.value.loadedSessionId === sessionId)) {
    return
  }
  loadingSessionId.value = sessionId
  sessionLoading.value = true
  try {
    await chatStore.value.loadHistory(sessionId, userId.value)
    try {
      const state = await fetchSessionState(sessionId)
      chatStore.value.setContextUsage(state.session_state?.context_usage)
      chatStore.value.setContextSnapshots(state.session_state?.context_snapshots)
    } catch {
      // History remains usable before the session has produced a context-usage snapshot.
    }
  } finally {
    sessionLoading.value = false
    loadingSessionId.value = ''
  }
}

async function sendMessage(text: string, reference = '') {
  if (!userId.value) {
    return
  }
  // ChatStore appends the user bubble before creating a missing session.
  await chatStore.value.send(
    userId.value,
    activeSessionId.value,
    text,
    reference,
    settingsStore.agentLoopMode,
    settingsStore.agentAccessMode,
  )
}

async function createTaskListFromInput(title: string, items: string[]) {
  if (!userId.value || items.length === 0) {
    return
  }
  let targetSessionId = activeSessionId.value
  if (!targetSessionId) {
    targetSessionId = await sessionStore.create(userId.value)
    if (!props.sessionId) sessionStore.select(targetSessionId)
  }
  const taskList = await taskListStore.create(targetSessionId, title || 'Task list', items, { open: props.mode === 'page' })
  if (!taskList) {
    return
  }
  const promptLines = [
    `Task list: ${taskList.title}`,
    ...taskList.items.map((item, index) => `${index + 1}. ${item.title}`),
    '',
    'Please work through this task list. Use complete_task_list_item after each completed item and finish_task_list when the list is done.',
  ]
  await sendMessage(promptLines.join('\n'))
}

function clearReference() {
  referenceText.value = ''
}

function handleToggleWebSearch() {
  settingsStore.toggleWebSearch(!settingsStore.profile.webSearchEnabled)
}

function setAgentLoopMode(mode: AgentLoopMode) {
  settingsStore.setAgentLoopMode(mode)
}

/** Exposes the persisted Agent loop mode to the shared radio menu. */
const agentLoopModeModel = computed<AgentLoopMode>({
  get: () => settingsStore.agentLoopMode,
  set: setAgentLoopMode,
})

async function refreshSkills() {
  await skillsStore.loadSkills()
}

function selectSkillReference(skillName: string) {
  referenceText.value = `用户要求使用Skill： ${skillName}`
  skillMenuOpen.value = false
}

function setAgentAccessMode(mode: AgentAccessMode) {
  settingsStore.setAgentAccessMode(mode)
}

function setChatRenderMode(mode: 'chat' | 'tool') {
  if (settingsStore.chatMode !== mode) {
    settingsStore.toggleChatMode()
  }
}

async function loadCurrentModelConfig() {
  if (!userId.value) {
    currentLargeModelName.value = ''
    return
  }
  try {
    const config = await fetchLLMConfig(userId.value)
    currentLargeModelName.value = config.effective_model_name?.trim() || config.model_name?.trim() || ''
    contextWindowTokens.value = config.context_window_tokens ?? DEFAULT_MODEL_CONTEXT_WINDOW_TOKENS
  } catch {
    currentLargeModelName.value = ''
  }
}

function openModelSettings() {
  localStorage.setItem('agent_editor_settings_active_tab', 'llm')
  window.dispatchEvent(new CustomEvent('agent-settings-tab', { detail: 'llm' }))
  workspaceStore.setMainView('settings')
}

function handleModelConfigUpdated(event: Event) {
  const modelName = (event as CustomEvent<{ modelName?: string }>).detail?.modelName
  currentLargeModelName.value = modelName?.trim() || ''
}

async function loadSafetyState() {
  try {
    const raw = await fetchSensitiveWords()
    const r = raw as Record<string, unknown>
    safetyDisabled.value = r._safety_disabled === true
  } catch { /* 忽略 */ }
}

async function toggleSafety() {
  if (safetyLoading.value) return
  safetyLoading.value = true
  try {
    const raw = await fetchSensitiveWords()
    const r = raw as Record<string, unknown>
    const next = !(r._safety_disabled === true)
    r._safety_disabled = next
    await saveSensitiveWords(r)
    safetyDisabled.value = next
  } catch { /* 忽略 */ }
  finally { safetyLoading.value = false }
}

function closeSessionDrawer() {
  sessionDrawerOpen.value = false
}

function handleMessageBottomChange(isAtBottom: boolean) {
  isMessageListAtBottom.value = isAtBottom
}

function jumpToMessageBottom() {
  messageListRef.value?.scrollToBottom({ behavior: 'smooth' })
  isMessageListAtBottom.value = true
}

function removeAttachment(attachment: AgentUploadedAttachment) {
  void chatStore.value.deleteAttachment(attachment)
}

function sendSuggestion(suggestion: string) {
  void sendMessage(suggestion)
}

/** Cancel the renderer that owns this session's HTTP stream, not only its mirror. */
function cancelActiveStream() {
  if (activeSessionId.value) {
    cancelSessionChatAcrossWindows(activeSessionId.value, chatStore.value)
  }
}

/** Follow session and titlebar settings changed in the floating Agent window. */
function handleWindowSync(payload: { type: string; value: unknown }) {
  if (props.sessionId || !payload) return
  // Every mounted AgentPanel instance must mark this selection as remote.
  // The shared session store may already have been updated by a sibling panel,
  // but this panel still needs to suppress its own history reload watcher.
  if (payload.type === 'session' && typeof payload.value === 'string') {
    void selectSession(payload.value, false, false)
  } else if (payload.type === 'chat-mode' && (payload.value === 'chat' || payload.value === 'tool')) {
    settingsStore.setChatMode(payload.value, false)
  } else if (payload.type === 'agent-loop-mode' && typeof payload.value === 'string') {
    settingsStore.setAgentLoopMode(payload.value as AgentLoopMode, false)
  } else if (payload.type === 'agent-access-mode' && typeof payload.value === 'string') {
    settingsStore.setAgentAccessMode(payload.value as AgentAccessMode, false)
  }
}

function containsFiles(event: DragEvent) {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files')
}

function handleDragEnter(event: DragEvent) {
  if (!containsFiles(event)) return
  event.preventDefault()
  dragDepth.value += 1
}

function handleDragOver(event: DragEvent) {
  if (!containsFiles(event)) return
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'copy'
  }
}

function handleDragLeave(event: DragEvent) {
  if (!containsFiles(event)) return
  event.preventDefault()
  dragDepth.value = Math.max(0, dragDepth.value - 1)
}

async function handleDrop(event: DragEvent) {
  if (!containsFiles(event)) return
  event.preventDefault()
  dragDepth.value = 0
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (!files.length || !userId.value) {
    return
  }
  let targetSessionId = activeSessionId.value
  if (!targetSessionId) {
    targetSessionId = await sessionStore.create(userId.value)
    if (!props.sessionId) sessionStore.select(targetSessionId)
  }
  uploadFiles(files, targetSessionId)
}

async function handleFileSelect(file: File) {
  if (!userId.value) return
  let targetSessionId = activeSessionId.value
  if (!targetSessionId) {
    targetSessionId = await sessionStore.create(userId.value)
    if (!props.sessionId) sessionStore.select(targetSessionId)
  }
  uploadFiles([file], targetSessionId)
}

function uploadFiles(files: File[], sessionId: string) {
  for (const file of files) void uploadFile(file, sessionId)
}

/** Upload one file without blocking the panel and keep progress on its own attachment card. */
async function uploadFile(file: File, sessionId: string) {
  const localId = `local-upload-${crypto.randomUUID()}`
  let placeholder: AgentUploadedAttachment = {
    attachment_id: localId,
    user_id: userId.value!,
    session_id: sessionId,
    library_id: '',
    library_name: '',
    filename: file.name,
    stored_name: file.name,
    uri: '',
    mime_type: file.type,
    size: file.size,
    source_type: 'uploading',
    metadata: {
      processing_status: 'uploading',
      processing_stage: 'uploading',
      processing_progress: 0,
    },
    created_at: new Date().toISOString(),
  }
  chatStore.value.addPendingAttachment(placeholder)
  try {
    const response = await uploadAgentAttachment(userId.value!, sessionId, file, (percent) => {
      placeholder = {
        ...placeholder,
        metadata: { ...placeholder.metadata, processing_progress: percent },
      }
      chatStore.value.updateAttachmentLocal(placeholder)
    })
    chatStore.value.replacePendingAttachment(localId, response.attachment)
    scheduleAttachmentPoll(response.attachment)
  } catch (error) {
    chatStore.value.updateAttachmentLocal({
      ...placeholder,
      metadata: {
        ...placeholder.metadata,
        processing_status: 'failed',
        processing_stage: 'failed',
        processing_progress: 100,
        processing_error: error instanceof Error ? error.message : 'Upload failed',
      },
    })
  }
}

/** Poll only this attachment until its background parser reaches a terminal state. */
function scheduleAttachmentPoll(attachment: AgentUploadedAttachment, attempt = 0) {
  const status = String(attachment.metadata?.processing_status || '')
  if (status === 'completed' || status === 'failed') return
  if (attempt >= 1200) {
    chatStore.value.updateAttachmentLocal({
      ...attachment,
      metadata: {
        ...attachment.metadata,
        processing_status: 'failed',
        processing_stage: 'timeout',
        processing_progress: 100,
        processing_error: '附件解析超时',
      },
    })
    return
  }
  const timer = window.setTimeout(async () => {
    attachmentPollTimers.delete(attachment.attachment_id)
    try {
      const response = await fetchAgentAttachment(
        attachment.user_id,
        attachment.session_id,
        attachment.attachment_id,
      )
      chatStore.value.updateAttachmentLocal(response.attachment)
      scheduleAttachmentPoll(response.attachment, attempt + 1)
    } catch {
      scheduleAttachmentPoll(attachment, attempt + 1)
    }
  }, 500)
  attachmentPollTimers.set(attachment.attachment_id, timer)
}

watch(userId, () => {
  void reloadSessions().then(() => {
    if (!props.sessionId) return
    void selectSession(props.sessionId)
  })
  if (userId.value) {
    void favoritesStore.load(userId.value, 'session', '')
  }
  void loadCurrentModelConfig()
})

watch(
  () => props.mode,
  (mode) => {
    taskListStore.setAutoOpenOnUpdate(mode === 'page')
  },
  { immediate: true },
)

watch(() => workspaceStore.pendingAgentPrompt, (prompt) => {
  if (prompt) {
    void sendMessage(prompt)
    workspaceStore.pendingAgentPrompt = ''
  }
})

watch(() => workspaceStore.pendingAgentReference, (refText) => {
  if (refText) {
    referenceText.value = refText
    workspaceStore.agentSidebarOpen = true
    workspaceStore.pendingAgentReference = ''
  }
})

// 顶栏按钮召唤任务列表卡片:可见时收起(与卡片 X 逻辑一致,仅剩它则收整个侧边栏),不可见时打开
function toggleTaskListCard() {
  if (taskListCardOpen.value) {
    closeTaskListCard()
  } else {
    taskListCardOpen.value = true
    agentSidebarOpen.value = true
  }
}

// 顶栏按钮召唤子 Agent 卡片:同上
function toggleChildAgentCard() {
  if (childAgentCardOpen.value) {
    closeChildAgentCard()
  } else {
    childAgentCardOpen.value = true
    agentSidebarOpen.value = true
  }
}

function toggleEnvironmentCard() {
  environmentCardOpen.value = !environmentCardOpen.value
  if (environmentCardOpen.value) {
    agentSidebarOpen.value = true
  } else {
    changeDetailOpen.value = false
    if (!taskListCardOpen.value && !childAgentCardOpen.value) agentSidebarOpen.value = false
  }
}

/** Opens or closes the complete Environment Change stack from the page topbar. */
function toggleEnvironmentWorkspace() {
  const nextOpen = !environmentWorkspaceOpen.value
  environmentCardOpen.value = nextOpen
  taskListCardOpen.value = nextOpen
  childAgentCardOpen.value = nextOpen
  agentSidebarOpen.value = nextOpen
  if (!nextOpen) changeDetailOpen.value = false
}

function closeEnvironmentCard() {
  environmentCardOpen.value = false
  changeDetailOpen.value = false
  if (!taskListCardOpen.value && !childAgentCardOpen.value) agentSidebarOpen.value = false
}

function showChangeDetails(snapshot: AgentChangeSnapshot) {
  selectedChangeSnapshot.value = snapshot
  changeDetailOpen.value = true
}

// 叉掉任务列表卡片:若另一张(子 Agent)卡片也不可见则一并收起整个侧边栏
function closeTaskListCard() {
  taskListCardOpen.value = false
  if (!childAgentCardOpen.value && !environmentCardOpen.value) {
    agentSidebarOpen.value = false
  }
}

// 叉掉子 Agent 卡片:若另一张(任务列表)卡片也不可见则一并收起整个侧边栏
function closeChildAgentCard() {
  childAgentCardOpen.value = false
  if (!taskListCardOpen.value && !environmentCardOpen.value) {
    agentSidebarOpen.value = false
  }
}

function showChildAgentConversation(child: ChildAgentRecord) {
  selectedChildAgent.value = child
}

function syncSelectedChildAgent(children: ChildAgentRecord[]) {
  if (!selectedChildAgent.value) return
  selectedChildAgent.value = children.find((child) => child.run_id === selectedChildAgent.value?.run_id) ?? null
}

// 任务列表创建/更新自动打开时,联动展开融合侧边栏
watch(() => taskListStore.sidebarOpen, (open) => {
  if (open) {
    taskListCardOpen.value = true
    agentSidebarOpen.value = true
  }
})

// 子 Agent 事件由流消息写入 ChatStore；出现时展示对应卡片而非空侧栏。
watch(
  () => chatStore.value.messages.length,
  () => {
    if (chatStore.value.isStreaming && chatStore.value.messages[chatStore.value.messages.length - 1]?.node === 'child_agent') {
      childAgentCardOpen.value = true
      agentSidebarOpen.value = true
    }
  },
)

function syncChildAgentWatcher() {
  const sessionId = activeSessionId.value
  if (userId.value && sessionId) {
    chatStore.value.startChildAgentWatcher(userId.value, sessionId)
  } else {
    chatStore.value.stopChildAgentWatcher()
  }
}

watch([userId, activeSessionId], syncChildAgentWatcher)

watch(
  activeSessionId,
  async (sessionId) => {
    selectedChildAgent.value = null
    // The first send creates and selects its session after inserting the local
    // user bubble. Keep that originating store visible for the whole stream.
    if (sessionId && sessionStore.freshSessionIds.includes(sessionId)) return
    if (sessionId) useActiveSessionChat(sessionId)
    if (sessionId && remoteSessionPending.value === sessionId) {
      remoteSessionPending.value = ''
      return
    }
    await nextTick()
    if (sessionId && !chatStore.value.isStreaming && chatStore.value.messages.length === 0) {
      void loadSelectedSessionHistory(sessionId)
    }
  },
)

let unsubscribeWindowSync: (() => void) | undefined

onMounted(() => {
  window.addEventListener('agent-model-config-updated', handleModelConfigUpdated as EventListener)
  window.addEventListener('agent-change-updated', handleChangeUpdated as EventListener)
  void reloadSessions().then(() => {
    if (props.sessionId) void loadSelectedSessionHistory(props.sessionId)
  })
  if (userId.value) {
    void favoritesStore.load(userId.value, 'session', '')
  }
  void loadCurrentModelConfig()
  void refreshSkills()
  void loadSafetyState()
  void settingsStore.fetchWebSearchSettings()
  syncChildAgentWatcher()
  syncTaskHistoryPolling(props.liveSync)
  unsubscribeWindowSync = window.agentEditorDesktop?.onWindowSync?.(handleWindowSync)
})

/** 嵌入式任务查看器切换到另一任务时，同步加载对应的完整 Agent 会话。 */
watch(() => props.sessionId, (sessionId) => {
  if (sessionId) void loadSelectedSessionHistory(sessionId)
})

watch(() => props.liveSync, syncTaskHistoryPolling)

onBeforeUnmount(() => {
  window.removeEventListener('agent-model-config-updated', handleModelConfigUpdated as EventListener)
  window.removeEventListener('agent-change-updated', handleChangeUpdated as EventListener)
  unsubscribeWindowSync?.()
  taskListStore.setAutoOpenOnUpdate(true)
  chatStore.value.stopChildAgentWatcher()
  if (taskHistoryPollTimer !== null) {
    window.clearInterval(taskHistoryPollTimer)
    taskHistoryPollTimer = null
  }
  for (const timer of attachmentPollTimers.values()) window.clearTimeout(timer)
  attachmentPollTimers.clear()
})

/** Keeps an open detail drawer in sync with a just-completed file patch. */
function handleChangeUpdated(event: CustomEvent<AgentChangeSnapshot>) {
  const snapshot = event.detail
  if (changeDetailOpen.value && snapshot?.session_id === activeSessionId.value) {
    selectedChangeSnapshot.value = snapshot
  }
}
</script>

<template>
  <aside
    class="agent-panel console-chat-skin surface-panel"
    :class="{
      'theme-dark': isDark,
      'theme-light': !isDark,
      'agent-page-mode': props.mode === 'page',
      'agent-drawer-open': props.mode === 'page' && sessionDrawerOpen,
      'attachment-drop-active': isAttachmentDropActive,
    }"
    @dragenter="handleDragEnter"
    @dragover="handleDragOver"
    @dragleave="handleDragLeave"
    @drop="handleDrop"
  >
    <Transition name="attachment-drop-fade">
      <div v-if="isAttachmentDropActive" class="attachment-drop-overlay" aria-live="polite">
        <IcIcon name="cloud-upload" :size="38" />
        <span>Drop files to attach to this session</span>
      </div>
    </Transition>

    <SessionDrawer
      :open="sessionDrawerOpen"
      :mode="props.mode"
      :class="{ 'mobile-floating': props.mobileMain }"
      :user-id="userId"
      :selected-session-id="activeSessionId"
      :streaming-session-ids="sessionStore.streamingSessionIds"
      @close="closeSessionDrawer"
      @create="startNewConversationDraft"
      @select="selectSession"
    />

    <div class="agent-chat-card">
    <header v-if="props.mode === 'page'" class="agent-topbar">
      <div class="topbar-capsule" :class="{ 'drawer-open': sessionDrawerOpen }">
        <button class="capsule-logo-btn" type="button" title="Toggle sidebar" @click="sessionDrawerOpen = !sessionDrawerOpen">
          <img :src="logoSrc" class="capsule-logo" alt="MetaWeave" />
        </button>
        <span class="capsule-divider" data-divider></span>
        <div ref="modeSwitchRef" class="capsule-switch" role="group" aria-label="Chat render mode">
          <span class="mode-indicator" :style="modeIndicatorStyle"></span>
          <button
            class="capsule-switch-btn"
            :class="{ active: settingsStore.chatMode === 'tool' }"
            type="button"
            aria-label="Tool mode"
            :aria-pressed="settingsStore.chatMode === 'tool'"
            @click="setChatRenderMode('tool')"
          >
            Tool
          </button>
          <button
            class="capsule-switch-btn"
            :class="{ active: settingsStore.chatMode === 'chat' }"
            type="button"
            aria-label="Chat mode"
            :aria-pressed="settingsStore.chatMode === 'chat'"
            @click="setChatRenderMode('chat')"
          >
            Chat
          </button>
        </div>
      </div>
      <button
        class="capsule-safety-btn"
        :class="{ disabled: safetyDisabled }"
        type="button"
        :title="safetyDisabled ? '安全审核已关闭' : '安全审核已开启'"
        :disabled="safetyLoading"
        @click="toggleSafety"
      >
        <span v-if="safetyLoading" class="capsule-safety-dot loading"></span>
        <span v-else class="capsule-safety-dot" :class="safetyDisabled ? '' : 'on'"></span>
        <span class="capsule-safety-label">审核</span>
      </button>
      <span class="topbar-title">{{ sessionTitle }}</span>
      <div class="topbar-right">
        <button
          class="topbar-tool-button v1-icon-button"
          :class="{ active: environmentWorkspaceOpen }"
          type="button"
          title="环境变更"
          aria-label="环境变更"
          :aria-pressed="environmentWorkspaceOpen"
          @click="toggleEnvironmentWorkspace"
        >
          <IcIcon name="dns" :size="17" />
        </button>
        <DropdownMenu v-model:open="skillMenuOpen">
          <DropdownMenuTrigger as-child>
            <button class="topbar-skill-trigger" type="button" title="Skill" aria-label="Skill" :disabled="!userId">
              <IcIcon name="auto-awesome" :size="16" />
              <span>Skill</span>
              <IcIcon class="topbar-filter-chevron" name="chevron-down" :size="14" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuPortal>
            <DropdownMenuContent class="topbar-filter-menu" align="end">
              <div class="topbar-skill-menu-head">
                <DropdownMenuLabel>Skills</DropdownMenuLabel>
                <button
                  class="topbar-skill-refresh"
                  type="button"
                  title="刷新 Skill"
                  :disabled="skillsStore.loading"
                  @click.stop="refreshSkills"
                >
                  <IcIcon name="refresh" :size="13" :class="{ spinning: skillsStore.loading }" />
                </button>
              </div>
              <div class="topbar-skill-list">
                <DropdownMenuItem
                  v-for="skill in extractedSkills"
                  :key="skill.skill_id"
                  @select="selectSkillReference(skill.name)"
                >
                  <span class="topbar-skill-name">{{ skill.name }}</span>
                </DropdownMenuItem>
                <div v-if="extractedSkills.length === 0" class="topbar-skill-empty">
                  {{ skillsStore.loading ? '正在读取' : '暂无 Skill' }}
                </div>
              </div>
            </DropdownMenuContent>
          </DropdownMenuPortal>
        </DropdownMenu>
        <DropdownMenu v-model:open="loopModeMenuOpen">
          <DropdownMenuTrigger as-child>
            <button class="topbar-loop-mode-trigger" type="button" title="Agent Loop 模式" aria-label="Agent Loop 模式" :disabled="!userId">
              <IcIcon name="psychology" :size="16" />
              <span>{{ selectedLoopModeLabel }}</span>
              <IcIcon class="topbar-filter-chevron" name="chevron-down" :size="14" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuPortal>
            <DropdownMenuContent class="topbar-filter-menu" align="end">
              <DropdownMenuLabel>思考模式</DropdownMenuLabel>
              <DropdownMenuRadioGroup v-model="agentLoopModeModel">
                <DropdownMenuRadioItem v-for="option in loopModeOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenuPortal>
        </DropdownMenu>
        <button class="panel-new-session" type="button" title="新对话" @click="startNewConversationDraft">
          <IcIcon name="add" :size="17" />
          <span>新对话</span>
        </button>
      </div>
    </header>

    <div class="agent-body">
      <AgentPanelTitlebar
        v-if="props.mode === 'panel'"
        compact
        :history-toggle="props.mobileMain"
        :session-icon-src="props.mobileMain ? logoSrc : ''"
        :draggable="props.panelDraggable"
        :title="sessionTitle"
        :chat-mode="settingsStore.chatMode"
        :environment-open="environmentCardOpen"
        :task-open="taskListCardOpen"
        :child-open="childAgentCardOpen"
        @toggle-sessions="sessionDrawerOpen = !sessionDrawerOpen"
        @toggle-environment="toggleEnvironmentCard"
        @toggle-task="toggleTaskListCard"
        @toggle-child="toggleChildAgentCard"
        @expand="emit('expand')"
        @create="startNewConversationDraft"
        @toggle-chat-mode="settingsStore.toggleChatMode"
      >
        <template #window-controls><slot name="window-controls" /></template>
      </AgentPanelTitlebar>

    <div class="agent-content-row">
    <main class="chat-body" :class="{ dimmed: isBootstrapping }">
      <Transition name="welcome-fade">
        <div v-if="!hasMessages && !chatStore.isStreaming && !sessionLoading" class="welcome-center">
          <img :src="logoSrc" class="welcome-cap-icon" alt="" />
          <img :src="welcomeTitleSrc" class="welcome-logo" alt="MetaWeave" />
          <p class="welcome-subtitle">在知识库 {{ knowledgeTitle }} 中有什么问题?</p>
        </div>
      </Transition>
      <div v-if="sessionLoading" class="history-loading">
        <LoaderCube />
        <span>加载会话历史...</span>
      </div>
      <div v-else class="chat-content">
      <MessageList
        ref="messageListRef"
        :messages="chatStore.messages"
        :is-streaming="chatStore.isStreaming"
        :merge-assistants="settingsStore.chatMode === 'chat'"
        :suggestions="chatStore.taskSuggestions"
        :compact="props.mode === 'panel'"
        @bottom-change="handleMessageBottomChange"
        @select-suggestion="sendSuggestion"
      />
      <StreamingIndicator :is-streaming="chatStore.isStreaming" :has-content="hasStreamingContent" />
      <p v-if="chatStore.streamError" class="stream-error">{{ chatStore.streamError }}</p>
      <button
        v-if="hasMessages && !isMessageListAtBottom"
        class="scroll-bottom-button"
        type="button"
        title="Scroll to bottom"
        aria-label="Scroll to bottom"
        @click="jumpToMessageBottom"
      >
        <svg class="scroll-svg" xmlns="http://www.w3.org/2000/svg" height="20px" viewBox="0 -960 960 960" width="20px" fill="currentColor">
          <path d="M440-800v487L216-537l-56 57 320 320 320-320-56-57-224 224v-487h-80Z"></path>
        </svg>
      </button>
      <div v-if="chatStore.isStreaming" class="thinking-flow" aria-live="polite">
        <span class="thinking-shimmer-text">正在思考</span>
      </div>
      <ContextCompressionStatus
        v-if="chatStore.compressionStatus !== 'idle'"
        :failed="chatStore.compressionStatus === 'failed'"
      />
      <ChatInput
        :disabled="!userId"
        :centered="!hasMessages && !chatStore.isStreaming"
        :compact="props.mode === 'panel'"
        :web-search-enabled="settingsStore.profile.webSearchEnabled"
        :model-label="modelConfigLabel"
        :agent-access-mode="settingsStore.agentAccessMode"
        :reference="referenceText"
        :attachments="chatStore.pendingAttachments"
        :context-tokens="chatStore.contextUsage?.current_tokens ?? 0"
        :max-context-tokens="displayedMaxContextTokens"
        :is-streaming="chatStore.isStreaming"
        @send="sendMessage"
        @toggle-web-search="handleToggleWebSearch"
        @configure-model="openModelSettings"
        @set-agent-access-mode="setAgentAccessMode"
        @clear-reference="clearReference"
        @remove-attachment="removeAttachment"
        @file-select="handleFileSelect"
        @cancel-stream="cancelActiveStream"
        @create-task-list="createTaskListFromInput"
      />
    </div>
    </main>
    <aside class="agent-sidebar" :class="{ open: agentSidebarOpen }" aria-label="任务与子 Agent 侧边栏">
      <section v-show="environmentCardOpen" class="agent-sidebar-card environment-card-shell">
        <EnvironmentChangeCard
          :session-id="activeSessionId || ''"
          :user-id="userId || ''"
          :sources="sessionSources"
          :running-sessions="runningSessions"
          :active-session-id="activeSessionId || ''"
          @close="closeEnvironmentCard"
          @show-changes="showChangeDetails"
          @select-session="selectSession"
        />
      </section>
      <section v-show="taskListCardOpen" class="agent-sidebar-card task-list-card">
        <TaskListDrawer @close="closeTaskListCard" />
      </section>
      <section v-show="childAgentCardOpen" class="agent-sidebar-card child-agent-card">
        <ChildAgentPanel
          :session-id="activeSessionId || ''"
          :user-id="userId || ''"
          @close="closeChildAgentCard"
          @open-conversation="showChildAgentConversation"
          @children-update="syncSelectedChildAgent"
        />
      </section>
    </aside>
    <Transition name="change-detail-slide">
      <ChangeDetailDrawer
        v-if="changeDetailOpen"
        :snapshot="selectedChangeSnapshot"
        @close="changeDetailOpen = false"
      />
    </Transition>
    <Transition name="child-conversation-slide">
      <ChildAgentConversationDrawer
        v-if="selectedChildAgent"
        :child="selectedChildAgent"
        :user-id="userId || ''"
        @close="selectedChildAgent = null"
      />
    </Transition>
    </div>
    </div>
    </div>
  </aside>
</template>

<style scoped>
.agent-panel {
  --font-chat: var(--font-ui);
  --font-mono: var(--font-code);
  --font-size-xs: 11px;
  --font-size-sm: 13px;
  --font-size-md: 15px;
  --font-size-lg: 18px;
  --font-size-xl: 22px;
  --line-height-relaxed: 1.65;
  --line-height-tight: 1.25;
  --font-weight-semibold: 650;
  --color-bg-elevated: var(--color-canvas-soft);
  --color-bg-muted: var(--color-canvas);
  --color-bg-hover: var(--color-primary-soft);
  --color-text-primary: var(--color-text);
  --color-text-tertiary: var(--color-text-muted);
  --color-border-light: rgba(255, 255, 255, 0.08);
  --color-accent: var(--color-primary);
  --color-accent-hover: var(--color-primary-hover);
  --color-accent-muted: var(--color-primary-soft);
  --color-blue: var(--color-primary);
  --color-user-bubble: var(--color-primary-soft);
  --color-user-bubble-border: color-mix(in srgb, var(--color-primary) 46%, transparent);
  --color-user-bubble-highlight: rgba(255, 255, 255, 0.08);
  --color-user-bubble-glow: var(--color-primary-softer);
  --color-agent-bubble: var(--color-primary-soft);
  --color-agent-bubble-border: color-mix(in srgb, var(--color-primary) 38%, transparent);
  --color-agent-bubble-highlight: rgba(255, 255, 255, 0.08);
  --color-agent-bubble-glow: var(--color-primary-softer);
  --input-bg: var(--color-surface-raised);
  --input-border: var(--color-border);
  --input-text: var(--color-text);
  --input-placeholder: var(--color-text-muted);
  --input-btn-bg: var(--color-surface);
  --input-send-disabled: var(--color-text-muted);
  --blur-strength: 10px;
  --radius-xl: 18px;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 0;
  border-radius: 0;
  outline: none;
  background: var(--color-bg-app);
  height: 100%;
}

.agent-panel.agent-page-mode {
  --agent-drawer-width: 280px;
  --agent-content-offset: 0px;
  --agent-chat-max-width: min(85vw, 1100px);
  --agent-input-max-width: min(75vw, 960px);
  --agent-topbar-height: 48px;
  border: 0;
  overflow: visible;
  background: transparent;
  backdrop-filter: none;
}

.agent-panel.agent-page-mode.agent-drawer-open {
  --agent-content-offset: var(--agent-drawer-width);
  --agent-chat-max-width: min(calc(100vw - var(--agent-content-offset) - 48px), 1100px);
  --agent-input-max-width: min(calc(100vw - var(--agent-content-offset) - 96px), 960px);
}

.agent-chat-card {
  display: contents;
}

.agent-panel.agent-page-mode .agent-chat-card {
  position: relative;
  z-index: 2;
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  margin-left: var(--agent-content-offset);
  overflow: hidden;
  border: 0;
  border-radius: 28px;
  background: var(--color-bg-app);
  box-shadow:
    0 10px 15px -3px rgba(0, 0, 0, 0.1),
    0 4px 6px -2px rgba(0, 0, 0, 0.05);
  transition: margin-left 200ms ease;
}

/* The embedded sidebar keeps only the file identity and size; full metadata
   remains available on the Agent page where the card has room to breathe. */
.agent-panel:not(.agent-page-mode) :deep(.agent-mounted-file) {
  width: 100%;
  min-height: 54px;
  height: auto;
  padding: 7px var(--space-8);
  grid-template-rows: 1fr;
  border-radius: var(--radius-xl);
}

.agent-panel:not(.agent-page-mode) :deep(.agent-mounted-file__icon) {
  grid-row: 1;
  width: 34px;
  height: 34px;
}

.agent-panel:not(.agent-page-mode) :deep(.agent-mounted-file__details) {
  grid-row: 1;
  display: block;
}

.agent-panel:not(.agent-page-mode) :deep(.agent-mounted-file__path),
.agent-panel:not(.agent-page-mode) :deep(.agent-mounted-file__created),
.agent-panel:not(.agent-page-mode) :deep(.agent-mounted-file__statuses) {
  display: none;
}

.agent-panel:not(.agent-page-mode) :deep(.agent-mounted-file__size) {
  grid-row: 1;
}

.agent-panel.attachment-drop-active {
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 58%, transparent),
    inset 0 0 80px color-mix(in srgb, var(--color-accent) 18%, transparent);
}

.agent-topbar {
  display: flex;
  align-items: center;
  min-height: var(--agent-topbar-height, 32px);
  padding: 0 var(--space-12);
  gap: var(--space-8);
  background: var(--color-canvas-soft);
  flex-shrink: 0;
  transition: padding-left 200ms ease;
}

.agent-panel.agent-page-mode.agent-drawer-open .agent-topbar {
  padding-left: var(--space-12);
}

.topbar-capsule {
  display: inline-flex;
  align-items: center;
  height: 36px;
  padding: 3px;
  gap: 0;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  transition: gap 200ms ease, padding 200ms ease;
}

.topbar-capsule.drawer-open {
  gap: 0;
  padding: 3px 10px 3px 6px;
}

.capsule-logo-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: auto;
  min-width: 30px;
  height: 30px;
  padding: 0 var(--space-4);
  flex-shrink: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  cursor: pointer;
  overflow: hidden;
  transition:
    width 200ms ease,
    opacity 160ms ease,
    margin 200ms ease,
    padding 200ms ease;
}

.topbar-capsule.drawer-open .capsule-logo-btn {
  width: 0;
  min-width: 0;
  padding: 0;
  opacity: 0;
  margin: 0;
  pointer-events: none;
}

.capsule-logo {
  display: block;
  height: 18px;
  width: auto;
  object-fit: contain;
}

.capsule-divider {
  width: 1px;
  height: 18px;
  flex-shrink: 0;
  background: var(--color-border);
  transition:
    width 200ms ease,
    opacity 160ms ease;
}

.topbar-capsule.drawer-open [data-divider] {
  width: 0;
  opacity: 0;
}

.capsule-switch {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.capsule-switch-btn {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 48px;
  height: 28px;
  padding: 0 var(--space-10);
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: calc(10px * var(--font-scale));
  line-height: 1;
  cursor: pointer;
  transition: color var(--transition-fast);
}

.capsule-switch-btn:hover {
  color: var(--color-text-secondary);
}

.capsule-switch-btn.active {
  color: #ffffff;
}

.topbar-title {
  flex: 1;
  overflow: hidden;
  text-align: center;
  color: var(--color-text-primary);
  font-size: calc(14px * var(--font-scale));
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-4);
}

.topbar-right :deep(.topbar-tool-button),
.topbar-right .topbar-tool-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
}

.topbar-right :deep(.topbar-tool-button:hover:not(:disabled)),
.topbar-right .topbar-tool-button:hover:not(:disabled),
.topbar-right .topbar-tool-button.active {
  border-color: var(--color-primary);
  background: var(--color-primary-softer);
  color: var(--color-primary);
}


.mode-indicator {
  position: absolute;
  top: 2px;
  left: 2px;
  height: calc(100% - 4px);
  border-radius: 999px;
  background: var(--color-primary);
  transition:
    transform 200ms cubic-bezier(0.4, 0, 0.2, 1),
    width 200ms cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}

/* ---- 安全审核开关 ---- */
.capsule-safety-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 30px;
  padding: 0 10px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: calc(12px * var(--font-scale));
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: color 150ms;
}

.capsule-safety-btn:hover:not(:disabled) {
  color: var(--color-text-secondary);
}

.capsule-safety-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.capsule-safety-btn.disabled {
  color: var(--color-danger);
}

.capsule-safety-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--color-border);
  flex-shrink: 0;
  transition: background 200ms;
}

.capsule-safety-dot.on {
  background: #22c55e;
  box-shadow: 0 0 4px rgba(34, 197, 94, 0.5);
}

.capsule-safety-dot.loading {
  background: transparent;
  border: 1.5px solid var(--color-text-muted);
  border-top-color: transparent;
  animation: safety-spin 0.6s linear infinite;
}

.capsule-safety-btn.disabled .capsule-safety-dot {
  background: var(--color-danger);
  box-shadow: 0 0 4px rgba(255, 95, 95, 0.4);
}

.capsule-safety-label {
  line-height: 1;
}

@keyframes safety-spin {
  to { transform: rotate(360deg); }
}

.topbar-loop-mode-trigger,
.topbar-skill-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 28px;
  padding: 0 12px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-canvas);
  color: var(--color-text-secondary);
  font: inherit;
  white-space: nowrap;
  cursor: pointer;
}

.topbar-loop-mode-trigger:hover,
.topbar-skill-trigger:hover {
  border-color: color-mix(in srgb, var(--color-primary) 40%, transparent);
  color: var(--color-primary);
}

.topbar-loop-mode-trigger[data-state='open'],
.topbar-skill-trigger[data-state='open'] {
  border-color: color-mix(in srgb, var(--color-primary) 45%, transparent);
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.topbar-filter-chevron {
  margin-right: -3px;
  opacity: 0.62;
  transition: transform var(--transition-fast);
}

.topbar-loop-mode-trigger[data-state='open'] .topbar-filter-chevron,
.topbar-skill-trigger[data-state='open'] .topbar-filter-chevron {
  transform: rotate(180deg);
}

.topbar-filter-menu {
  width: 260px;
  max-height: min(520px, var(--reka-dropdown-menu-content-available-height));
  overflow-y: auto;
}

.topbar-skill-list {
  width: 100%;
}

.topbar-skill-menu-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-8);
  min-height: 30px;
  padding-right: var(--space-4);
}

.topbar-skill-refresh {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.topbar-skill-refresh:hover:not(:disabled) {
  background: var(--color-primary-softer);
  color: var(--color-text-primary);
}

.topbar-skill-refresh:disabled {
  cursor: default;
  opacity: 0.55;
}

.topbar-skill-refresh .spinning {
  animation: safety-spin 0.8s linear infinite;
}

.topbar-skill-name {
  color: inherit;
}

.topbar-skill-empty {
  padding: var(--space-10) var(--space-8);
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: calc(11px * var(--font-scale));
  text-align: center;
}

.panel-new-session {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-6);
  width: auto;
  height: 28px;
  padding: 0 var(--space-10);
  border: 0;
  border-radius: 999px;
  background: var(--color-primary);
  color: #ffffff;
  font: inherit;
  font-size: calc(13px * var(--font-scale));
  cursor: pointer;
}

.panel-new-session:hover {
  border-color: transparent;
  background: var(--color-primary-hover, var(--color-primary));
  color: #ffffff;
}

.agent-body {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.agent-content-row {
  position: relative;
  display: flex;
  flex-direction: row;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.attachment-drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 80;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-12);
  border: 1px dashed color-mix(in srgb, var(--color-accent) 68%, transparent);
  border-radius: inherit;
  background:
    radial-gradient(circle at 50% 45%, color-mix(in srgb, var(--color-accent) 18%, transparent), transparent 38%),
    color-mix(in srgb, var(--color-surface-raised) 90%, transparent);
  color: var(--color-text-primary);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
  text-align: center;
  pointer-events: none;
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 32%, transparent),
    inset 0 0 120px rgba(0, 0, 0, 0.22),
    0 24px 80px rgba(0, 0, 0, 0.38);
  backdrop-filter: blur(16px);
}

.attachment-drop-overlay svg {
  color: var(--color-accent);
}

.attachment-drop-fade-enter-active,
.attachment-drop-fade-leave-active {
  transition:
    opacity 160ms ease,
    transform 160ms ease;
}

.attachment-drop-fade-enter-from,
.attachment-drop-fade-leave-to {
  opacity: 0;
  transform: scale(0.98);
}

.chat-body {
  position: relative;
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  transition:
    flex-basis 220ms cubic-bezier(0.4, 0, 0.2, 1),
    opacity var(--transition-fast);
}

/* 融合侧边栏:无边框透明容器,内部纵向排列独立圆角卡片,打开时占据宽度挤压对话区 */
.agent-sidebar {
  flex: 0 0 0px;
  display: flex;
  width: min(400px, 38vw);
  min-width: 0;
  flex-direction: column;
  gap: var(--space-10);
  overflow: hidden;
  padding: 0;
  transition: flex-basis 220ms cubic-bezier(0.4, 0, 0.2, 1), padding 220ms cubic-bezier(0.4, 0, 0.2, 1);
}

.agent-sidebar.open {
  flex-basis: min(400px, 38vw);
  overflow: visible;
  padding: var(--space-10);
}

/* 三张环境卡片保持圆角与卡片底色，不叠加阴影。 */
.agent-sidebar-card {
  box-sizing: border-box;
  display: flex;
  min-height: 0;
  flex-direction: column;
  border: 4px solid var(--library-form-ring);
  border-radius: var(--workspace-card-radius);
  background: var(--color-bg-card);
  box-shadow: none;
}

/* 任务列表卡片:按内容弹性展示全部任务(不滚动),任务过多超高时才封顶内部滚动 */
.task-list-card {
  flex: 0 0 auto;
  max-height: min(60vh, 520px);
  overflow: hidden;
}

/* 子 Agent 卡片:按内容弹性适配高度(内容少时收缩不顶到底),超高时被压缩到任务列表以下
   剩余空间内内部滚动。flex-basis auto + grow 0:不拉伸填满剩余;shrink 1 + min-height 0
   允许卡片压缩到可用空间配合内部滚动。顶部始终锚定任务列表底部 */
.child-agent-card {
  flex: 0 1 auto;
  min-height: 0;
  overflow: hidden;
}

.agent-page-mode :deep(.message-list) {
  box-sizing: border-box;
  width: 100%;
  align-self: stretch;
  padding-right: max(var(--space-16), calc((100% - var(--agent-chat-max-width)) / 2));
  padding-left: max(var(--space-16), calc((100% - var(--agent-chat-max-width)) / 2));
  transition:
    padding-right 200ms ease,
    padding-left 200ms ease;
}

.agent-page-mode :deep(.bubble-row) {
  max-width: min(100%, 760px);
}

.agent-page-mode :deep(.tool-assistant-row) {
  width: 100%;
  max-width: 100%;
}

.agent-page-mode :deep(.chat-input-wrap) {
  left: 50%;
  max-width: var(--agent-input-max-width);
  transition:
    left 200ms ease,
    bottom 350ms cubic-bezier(0.4, 0, 0.2, 1),
    width 350ms cubic-bezier(0.4, 0, 0.2, 1);
}

.agent-page-mode .stream-error {
  width: min(100%, var(--agent-chat-max-width));
  margin-right: max(var(--space-16), calc((100% - var(--agent-chat-max-width)) / 2));
  margin-left: max(var(--space-16), calc((100% - var(--agent-chat-max-width)) / 2));
}

.scroll-bottom-button {
  position: absolute;
  left: 50%;
  bottom: 132px;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  padding: 10px;
  border: 0;
  border-radius: 50%;
  background-color: white;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.24);
  transform: translateX(-50%);
  cursor: pointer;
  transition: all 0.5s;
  color: #0c0c0c;
}

.scroll-bottom-button::after {
  content: "Down";
  position: absolute;
  width: auto;
  background-color: white;
  font-size: calc(12px * var(--font-scale));
  box-sizing: border-box;
  padding: 8px 14px;
  border-radius: 25px;
  top: -44px;
  box-shadow: 0 0 5px rgba(0, 0, 0, 0.1);
  transition: all 0.5s;
  transform: scale(0);
  white-space: nowrap;
  font-family: var(--font-ui);
  font-weight: 600;
  color: #0c0c0c;
}

.scroll-svg {
  transition: all 0.5s;
}

.scroll-bottom-button:hover {
  transform: translateX(-50%) translateY(-3px);
  background-color: #0c0c0c;
  border-color: #0c0c0c;
  color: white;
}

.scroll-bottom-button:hover .scroll-svg {
  fill: white;
  transform: scale(1.2);
}

.scroll-bottom-button:hover::after {
  transform: scale(1);
}

.scroll-bottom-button:active {
  transform: translateX(-50%) translateY(2px);
}

.agent-page-mode .scroll-bottom-button {
  left: 50%;
}



.thinking-flow {
  position: absolute;
  left: var(--space-16);
  bottom: 112px;
  z-index: 3;
  display: inline-flex;
  align-items: center;
  height: 24px;
  pointer-events: none;
  color: var(--color-text-tertiary);
  font-family: var(--font-ui);
  font-size: calc(13px * var(--font-scale));
  letter-spacing: 0;
}

.agent-page-mode .thinking-flow {
  left: max(var(--space-16), calc((100% - var(--agent-input-max-width)) / 2));
}

.welcome-center {
  position: absolute;
  bottom: calc(50% + 60px);
  left: 0;
  right: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  pointer-events: none;
  z-index: 1;
}

.agent-page-mode .welcome-center {
  right: auto;
  left: 50%;
  width: min(100%, var(--agent-chat-max-width));
  transform: translateX(-50%);
  transition: right 200ms ease;
}

.welcome-cap-icon {
  display: block;
  width: 120px;
  height: auto;
  object-fit: contain;
  margin-bottom: 8px;
  pointer-events: auto;
  animation: welcome-cap-in 1.2s ease-out forwards;
}

.welcome-logo {
  display: block;
  width: 200px;
  height: auto;
  object-fit: contain;
  pointer-events: auto;
}

@keyframes welcome-cap-in {
  from {
    opacity: 0;
    transform: scale(0.92);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.welcome-subtitle {
  margin: var(--space-10) 0 0;
  color: var(--color-text-muted);
  font-size: calc(14px * var(--font-scale));
  line-height: 1.5;
}

.welcome-fade-leave-active {
  transition:
    opacity 250ms ease,
    transform 250ms ease;
}

.welcome-fade-leave-to {
  opacity: 0;
  transform: translateY(-16px);
}

@media (max-width: 820px) {
  .agent-panel.agent-page-mode {
    --agent-content-offset: 0px;
    --agent-chat-max-width: min(92vw, 560px);
    --agent-input-max-width: min(92vw, 560px);
  }

  .agent-panel.agent-page-mode.agent-drawer-open {
    --agent-content-offset: 0px;
    --agent-chat-max-width: min(92vw, 560px);
    --agent-input-max-width: min(92vw, 560px);
  }

}

.history-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-16);
  flex: 1;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.agent-page-mode .history-loading {
  margin-left: 0;
  width: 100%;
  transition:
    margin-left 200ms ease,
    width 200ms ease;
}

.chat-content {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.chat-content :deep(.message-list) {
  position: relative;
  z-index: 2;
}

/* Once a conversation starts, the composer participates in the flex layout so
   the message viewport ends at its top edge, including when the input grows. */
.chat-content :deep(.chat-input-wrap:not(.centered)) {
  position: relative;
  left: auto;
  bottom: auto;
  flex: 0 0 auto;
  margin: 0 auto var(--space-16);
  transform: none;
}
</style>
