/** Request-level acceptance for every model, MinerU, directory and preference control on the five-page entry. */
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { saveOnboardingModel, saveOnboardingPage } from '@/components/auth_view/onboarding'
import { useSettingsStore } from '@/stores/settings'
import type { AuthDraft } from '@/components/auth_view/authTypes'

const draft: AuthDraft = {
  username: '雾松', password: '', confirmation: '', libraryName: '文献', knowledgeDir: 'D:/文献',
  large: { modelName: 'deepseek-chat', baseUrl: 'https://api.deepseek.com/v1', apiKey: 'large-key' },
  small: { modelName: 'small-model', baseUrl: 'https://small.test/v1', apiKey: 'small-key' },
  vision: { modelName: 'vision-model', baseUrl: 'https://vision.test/v1', apiKey: 'vision-key' },
  mineruKey: 'mineru-key', mineruModel: 'pipeline', vlmEnabled: true, ocrEnabled: true, visionEnabled: true,
  proxyUrl: 'http://127.0.0.1:7890', webSearchEnabled: false, memoryEnabled: false,
  sensitiveWordsEnabled: false, safetyEnabled: true, dshEnabled: true, primaryColor: '#476bf7', softColor: '#123456',
}
let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>
beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  useSettingsStore().setUserId('82631459')
  fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => new Response(JSON.stringify({ user_id: '82631459', knowledge_dir: 'D:/文献' }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())
function requests() { return fetchMock.mock.calls.map(([url, init]) => ({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined })) }

it('saves knowledge name and absolute directory together', async () => {
  await saveOnboardingPage('82631459', draft, 1, 'light')
  expect(requests()[0]).toEqual({ url: '/settings/profile/knowledge-dir', body: { user_id: '82631459', knowledge_dir: 'D:/文献', name: '文献' } })
})
it.each(['large', 'small', 'vision'] as const)('saves the %s model individually without clearing other roles', async (section) => {
  await saveOnboardingModel('82631459', draft, section)
  const prefix = section === 'large' ? '' : `${section}_`
  expect(requests()[0]).toEqual({ url: '/settings/llm/config', body: { user_id: '82631459', [`${prefix}model_name`]: draft[section].modelName, [`${prefix}base_url`]: draft[section].baseUrl, [`${prefix}api_key`]: draft[section].apiKey } })
})
it('saves all three models and MinerU with VLM, OCR and image-understanding controls', async () => {
  await saveOnboardingPage('82631459', draft, 2, 'light')
  expect(requests().map((request) => request.url)).toEqual(['/settings/llm/config', '/settings/llm/config', '/settings/llm/config', '/settings/vlm/config', '/settings/profile/ingestion'])
  expect(requests()[3]?.body).toMatchObject({ enabled: true, api_key: 'mineru-key', model: 'pipeline' })
  expect(requests()[4]?.body).toMatchObject({ ocr_enabled: true, vision_understanding_enabled: true })
})
it('persists theme mode/colors, search/proxy, memory, user safety and eligible DSH before completion', async () => {
  await saveOnboardingPage('82631459', draft, 3, 'system')
  expect(requests().slice(0, 5).map((request) => request.body)).toEqual([
    { user_id: '82631459', theme_mode: 'system', theme_primary_color: '#476bf7', theme_soft_color: '#123456' },
    { user_id: '82631459', proxy_url: 'http://127.0.0.1:7890', web_search_enabled: false },
    { user_id: '82631459', long_term_memory_enabled: false },
    { user_id: '82631459', sensitive_words_enabled: false, safety_enabled: true },
    { user_id: '82631459', dsh_coding_agent_enabled: true },
  ])
})
