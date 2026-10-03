/** Historical native knowledge cards must retain the original library for their real actions. */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SearchNativeResultCard from '@/components/search_page/SearchNativeResultCard.vue'
import { useFavoritesStore } from '@/stores/favorites'
import { usePrivacyStore } from '@/stores/privacy'
import { useSettingsStore } from '@/stores/settings'
import type { UnifiedSearchResult } from '@/types/unifiedSearch'

describe('native knowledge card library identity', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useSettingsStore().updateProfile({ userId: 'u1', activeLibraryId: 'current' })
  })

  it.each(['library', 'components'] as const)('writes %s favorites to the original library before navigation', async (source) => {
    const favorites = useFavoritesStore()
    const privacy = usePrivacyStore()
    const favorite = vi.spyOn(favorites, 'toggle').mockResolvedValue(undefined)
    const hide = vi.spyOn(privacy, 'toggle').mockResolvedValue(undefined)
    const isPrivate = vi.spyOn(privacy, 'isPrivate').mockReturnValue(false)
    const item = source === 'library'
      ? { item_id: 'book-1', user_id: 'u1', display_title: '知识手册', description: '', item_type: 'book', source_name: '封面.png', source_path: 'covers/shared.png', cover_mode: 'source_image', tags: [] }
      : { component_id: 'cards/shared.vue', title: '查询按钮', source: '', source_format: 'vue', tag: 'button' }
    const result: UnifiedSearchResult = {
      id: 'selected', source, library_id: 'origin', title: 'selected', snippet: '', locator: '', updated_at: '',
      score: 0, matched_modes: [], item,
    }
    const wrapper = mount(SearchNativeResultCard, {
      props: { result },
      global: { stubs: { IcIcon: true, ComponentPreview: true } },
    })
    await wrapper.get('.favorite-button').trigger('click')
    expect(favorite).toHaveBeenCalledWith(source === 'library' ? 'library_item' : 'component', source === 'library' ? 'book-1' : 'cards/shared.vue', 'origin')
    if (source === 'library') {
      const cover = new URL(wrapper.get('.cover-image').attributes('src') ?? '', window.location.href)
      expect(cover.searchParams.get('library_id')).toBe('origin')
      expect(isPrivate).toHaveBeenCalledWith('library_item', 'book-1', 'origin')
      await wrapper.get('.privacy-button').trigger('click')
      expect(hide).toHaveBeenCalledWith('library_item', 'book-1', 'origin')
    }
    expect(useSettingsStore().profile.activeLibraryId).toBe('current')
    wrapper.unmount()
  })
})
