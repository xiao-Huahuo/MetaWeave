/** A late profile refresh must never restore identity after the user logs out. */
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useSettingsStore } from '@/stores/settings'

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
})
afterEach(() => vi.unstubAllGlobals())

it('ignores a profile refresh that completes after logout', async () => {
  let finish!: (response: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve
        }),
    ),
  )
  const store = useSettingsStore()
  store.setUserId('old-user')
  const refresh = store.refreshUserProfile()
  store.clearUserId()
  finish(
    new Response(
      JSON.stringify({ user_id: 'old-user', knowledge_dir: 'knowledge', knowledge_libraries: [] }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ),
  )
  await refresh
  expect(store.hasUserId).toBe(false)
  expect(store.profile.userId).toBe('')
})
