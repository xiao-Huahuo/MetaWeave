/** Real Agent messages/session choices must not survive a switch to another authenticated account. */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { useSettingsStore } from '@/stores/settings'
import { useChatStore } from '@/stores/chat'
import { useSessionStore } from '@/stores/session'

const { listSessions } = vi.hoisted(() => ({ listSessions: vi.fn() }))
vi.mock('@/api/session', async (original) => ({ ...await original<typeof import('@/api/session')>(), listSessions }))
beforeEach(() => { localStorage.clear(); vi.clearAllMocks(); setActivePinia(createPinia()); useSettingsStore().setUserId('82631459') })

it('clears real Agent messages and session selection on logout', () => {
  const chat = useChatStore()
  const session = useSessionStore()
  chat.messages = [{ role: 'assistant', content: '私有会话' }]
  session.sessions = [{ session_id: 'private-session', user_id: '82631459', session_name: '私有标题', created_at: '', updated_at: '' }]
  session.select('private-session')
  useSettingsStore().clearUserId()
  expect(chat.messages).toEqual([])
  expect(session.sessions).toEqual([])
  expect(session.currentSessionId).toBeNull()
  expect(localStorage.getItem('agent_editor_active_session_id')).toBeNull()
})
it('ignores a session list response from the previous account', async () => {
  let finish!: (result: unknown) => void
  listSessions.mockReturnValue(new Promise((resolve) => { finish = resolve }))
  const session = useSessionStore()
  const pending = session.load('82631459')
  useSettingsStore().setUserId('39578612')
  finish([{ session_id: 'private-session', user_id: '82631459', session_name: '私有标题', message_count: 1, created_at: '', updated_at: '' }])
  await pending
  expect(session.sessions).toEqual([])
})
