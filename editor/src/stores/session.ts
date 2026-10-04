/*
 * Agent chat session store.
 *
 * Usage:
 * Keeps editor Agent panel sessions synchronized with the backend session API.
 * The same user_id sees the same sessions in console and editor.
 */

import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { useSettingsStore } from '@/stores/settings'

import {
  clearAllSessions,
  createSession,
  deleteSession,
  listSessions,
  pruneEmptySessions,
  updateSessionName,
  type SessionRecord,
} from '@/api/session'

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<SessionRecord[]>([])
  const currentSessionId = ref<string | null>(null)
  const isLoading = ref(false)
  /** Persisted session IDs with a live browser Agent stream. */
  const streamingSessionIds = ref<string[]>([])
  /** Newly-created sessions whose first local turn must not be replaced by history. */
  const freshSessionIds = ref<string[]>([])
  /** User whose session list is already represented by `sessions`, including an empty list. */
  let loadedUserId = ''
  /** Prevent an older list response from erasing a session created meanwhile. */
  let localMutationVersion = 0
  /** Shared request used when several mounted components load the same user concurrently. */
  let pendingLoad: Promise<void> | null = null
  let pendingLoadUserId = ''
  /** Account revision prevents old list/create results from crossing a logout or user switch. */
  let accountRevision = 0

  /** Cross-window signal: mirrors the session id for the floating Agent window. */
  const ACTIVE_SESSION_KEY = 'agent_editor_active_session_id'

  const currentSession = computed(
    () => sessions.value.find((session) => session.session_id === currentSessionId.value) ?? null,
  )

  const hasSessions = computed(() => sessions.value.length > 0)

  /** Load once per user unless a data-changing workflow explicitly requests a refresh. */
  async function load(userId: string, force = false): Promise<void> {
    if (!userId) {
      return
    }

    if (!force && loadedUserId === userId) {
      return
    }
    if (pendingLoad) {
      if (pendingLoadUserId === userId) {
        return pendingLoad
      }
      await pendingLoad
      return load(userId, force)
    }

    const request = (async () => {
      const requestAccountRevision = accountRevision
      const requestMutationVersion = localMutationVersion
      isLoading.value = true
      try {
        const nextSessions = await listSessions(userId)
        if (requestAccountRevision !== accountRevision) return
        loadedUserId = userId
        sessions.value = requestMutationVersion === localMutationVersion
          ? nextSessions
          : [
              ...sessions.value,
              ...nextSessions.filter((incoming) => !sessions.value.some((local) => local.session_id === incoming.session_id)),
            ]
        if (requestMutationVersion === localMutationVersion
          && currentSessionId.value && !sessions.value.some((session) => session.session_id === currentSessionId.value)) {
          currentSessionId.value = null
        }
      } finally {
        if (requestAccountRevision === accountRevision) isLoading.value = false
      }
    })()
    pendingLoad = request
    pendingLoadUserId = userId
    try {
      await request
    } finally {
      if (pendingLoad === request) {
        pendingLoad = null
        pendingLoadUserId = ''
      }
    }
  }

  async function create(userId: string, sessionName?: string): Promise<string> {
    const requestAccountRevision = accountRevision
    const session = await createSession(userId, sessionName)
    if (requestAccountRevision !== accountRevision) throw new DOMException('Account changed', 'AbortError')
    localMutationVersion += 1
    sessions.value = [session, ...sessions.value.filter((item) => item.session_id !== session.session_id)]
    freshSessionIds.value = [...new Set([...freshSessionIds.value, session.session_id])]
    currentSessionId.value = session.session_id
    localStorage.setItem(ACTIVE_SESSION_KEY, session.session_id)
    window.agentEditorDesktop?.windowSync?.('session', session.session_id)
    return session.session_id
  }

  /** Select locally and optionally notify the other Electron Agent window. */
  function select(sessionId: string, broadcast = true) {
    currentSessionId.value = sessionId
    localStorage.setItem(ACTIVE_SESSION_KEY, sessionId)
    if (broadcast) window.agentEditorDesktop?.windowSync?.('session', sessionId)
  }

  function clearSelection() {
    currentSessionId.value = null
    localStorage.removeItem(ACTIVE_SESSION_KEY)
    window.agentEditorDesktop?.windowSync?.('session', null)
  }

  /** Registers stream activity without changing the user's selected session. */
  function setSessionStreaming(sessionId: string, streaming: boolean) {
    if (!sessionId) return
    streamingSessionIds.value = streaming
      ? [...new Set([...streamingSessionIds.value, sessionId])]
      : streamingSessionIds.value.filter((id) => id !== sessionId)
  }

  function settleFreshSession(sessionId: string) {
    freshSessionIds.value = freshSessionIds.value.filter((id) => id !== sessionId)
  }

  async function remove(sessionId: string) {
    await deleteSession(sessionId)
    localMutationVersion += 1
    sessions.value = sessions.value.filter((session) => session.session_id !== sessionId)
    settleFreshSession(sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
    }
  }

  async function clearAll(userId: string) {
    await clearAllSessions(userId)
    localMutationVersion += 1
    sessions.value = []
    currentSessionId.value = null
  }

  async function rename(sessionId: string, sessionName: string) {
    await updateSessionName(sessionId, sessionName)
    const session = sessions.value.find((item) => item.session_id === sessionId)
    if (session) {
      session.session_name = sessionName
    }
  }

  function renameLocal(sessionId: string, sessionName: string) {
    const session = sessions.value.find((item) => item.session_id === sessionId)
    if (session) {
      session.session_name = sessionName
    }
  }

  async function pruneEmpty(userId: string) {
    try {
      await pruneEmptySessions(userId)
      await load(userId, true)
    } catch {
      // non-critical
    }
  }

  /** Clear renderer selection/history only; persistent conversations remain in the database. */
  function resetForAccount(): void {
    accountRevision += 1
    localMutationVersion += 1
    sessions.value = []; currentSessionId.value = null
    streamingSessionIds.value = []; freshSessionIds.value = []; isLoading.value = false
    loadedUserId = ''; pendingLoad = null; pendingLoadUserId = ''
    localStorage.removeItem(ACTIVE_SESSION_KEY)
  }
  watch(() => useSettingsStore().profile.userId, resetForAccount, { flush: 'sync' })

  return {
    resetForAccount,
    sessions,
    currentSessionId,
    isLoading,
    streamingSessionIds,
    freshSessionIds,
    currentSession,
    hasSessions,
    load,
    create,
    select,
    clearSelection,
    setSessionStreaming,
    settleFreshSession,
    remove,
    clearAll,
    rename,
    renameLocal,
    pruneEmpty,
  }
})
