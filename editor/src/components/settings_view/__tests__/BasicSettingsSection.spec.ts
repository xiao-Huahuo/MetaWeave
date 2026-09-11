/*
 * Basic settings blocked-file-type selector contract.
 *
 * Usage:
 * Verifies that supported suffix capsules append gitignore rules once and use
 * the section's existing save event instead of introducing separate storage.
 */
import { mount, type VueWrapper } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import BasicSettingsSection from '@/components/settings_view/BasicSettingsSection.vue'

function mountSection(ignorePatterns = '*.md') {
  return mount(BasicSettingsSection, {
    props: {
      libraryNameDraft: 'Knowledge',
      knowledgeDirDraft: 'D:/Knowledge',
      editorImageAssetsDirDraft: './assets/',
      watchEnabledDraft: true,
      autoIngestOnUploadDraft: false,
      visionUnderstandingEnabledDraft: false,
      dshCodingAgentEnabledDraft: false,
      knowledgeIgnorePatternsDraft: ignorePatterns,
      supportedFileTypes: ['.md', '.pdf'],
      hasChanges: false,
      saving: false,
      saveMessage: '',
      saveError: '',
      switchingKnowledgeRoot: false,
      'onUpdate:knowledgeIgnorePatternsDraft': (value: string) => wrapper.setProps({ knowledgeIgnorePatternsDraft: value }),
    },
  })
}

let wrapper: VueWrapper

describe('BasicSettingsSection blocked file types', () => {
  it('moves OCR out of basic settings while preserving image understanding and DSH', () => {
    wrapper = mountSection()
    const labels = wrapper.findAll('.toggle-row label').map((item) => item.text())

    expect(labels).not.toContain('OCR')
    expect(labels).toContain('识图')
    expect(wrapper.props('visionUnderstandingEnabledDraft')).toBe(false)
    expect(labels.indexOf('启用 DSH coding agent')).toBe(labels.indexOf('识图') + 1)
    expect(wrapper.props('dshCodingAgentEnabledDraft')).toBe(false)
  })

  it('renders below the ignore area and appends each supported extension only once', async () => {
    wrapper = mountSection()
    const ignoreArea = wrapper.get('.ignore-row')
    const typeArea = wrapper.get('.blocked-file-types-row')
    const chips = wrapper.findAll('.file-type-chip')

    expect(ignoreArea.element.compareDocumentPosition(typeArea.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(typeArea.text()).toContain('屏蔽的文件类型')
    expect(chips.map((chip) => chip.text())).toEqual(['.md', '.pdf'])
    expect(chips[0]?.attributes('aria-pressed')).toBe('true')

    await chips[1]?.trigger('click')
    expect(wrapper.props('knowledgeIgnorePatternsDraft')).toBe('*.md\n*.pdf')
    expect(wrapper.emitted('save')).toHaveLength(1)

    await wrapper.findAll('.file-type-chip')[1]?.trigger('click')
    expect(wrapper.props('knowledgeIgnorePatternsDraft')).toBe('*.md\n*.pdf')
    expect(wrapper.emitted('save')).toHaveLength(1)
  })
})
