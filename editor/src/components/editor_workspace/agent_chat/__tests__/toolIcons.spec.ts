/*
 * Tool category icon mapping tests.
 *
 * Verifies that each backend tool family resolves to one locally bundled
 * semantic icon and that unknown extensions retain a visible fallback.
 */
import { describe, expect, it } from 'vitest'

import { toolIconName } from '../toolIcons'

describe('toolIconName', () => {
  it.each([
    ['get_current_time', 'build'],
    ['git_status', 'git'],
    ['use_skill', 'auto-awesome'],
    ['get_long_term_memory', 'psychology'],
    ['get_knowledge_context', 'manage-search'],
    ['read_file', 'document'],
    ['list_library_items', 'book'],
    ['create_task_list', 'checklist'],
    ['spawn_child_agent', 'group'],
    ['add_todo', 'todo'],
    ['web_search', 'language'],
  ])('maps %s to the %s local icon', (toolName, iconName) => {
    expect(toolIconName(toolName)).toBe(iconName)
  })

  it('uses the local utility icon for an unknown extension tool', () => {
    expect(toolIconName('custom_extension_tool')).toBe('build')
  })
})
