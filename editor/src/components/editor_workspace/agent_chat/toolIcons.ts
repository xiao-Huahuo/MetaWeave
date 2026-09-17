/*
 * Agent tool category icon mapping.
 *
 * Each backend tool family shares one semantic name from the locally bundled
 * IcIcon asset set. Unknown extension tools use the utility wrench fallback.
 */

/** Groups registered backend tools by the local icon used in Agent rows. */
const TOOL_ICON_GROUPS: ReadonlyArray<readonly [string, readonly string[]]> = [
  ['build', [
    'list_available_tools', 'get_current_time', 'run_terminal_command', 'download_file',
    'list_components', 'get_component', 'create_component', 'update_component',
    'delete_component', 'validate_component',
  ]],
  ['git', [
    'git_status', 'git_diff', 'git_history', 'git_init_repository', 'git_restore_files',
    'git_commit_files', 'git_push_branch', 'git_create_branch', 'git_add_remote',
    'git_switch_branch', 'git_pull_branch',
  ]],
  ['auto-awesome', [
    'list_skills', 'use_skill', 'get_custom_skill', 'create_custom_skill',
    'update_custom_skill', 'delete_custom_skill', 'validate_custom_skill',
    'test_custom_skill', 'set_skill_enabled',
  ]],
  ['psychology', [
    'get_long_term_memory', 'write_long_term_memory', 'write_long_term_rule',
    'delete_long_term_memory', 'delete_long_term_rule',
  ]],
  ['manage-search', [
    'get_knowledge_context', 'search_knowledge', 'search_knowledge_graph_nodes',
    'find_knowledge_graph_paths', 'save_uploaded_attachment_to_knowledge',
    'get_knowledge_file_url',
  ]],
  ['document', [
    'get_current_viewing_document', 'list_knowledge_files', 'read_file',
    'read_knowledge_file', 'read_session_attachment',
    'write_knowledge_file', 'patch_knowledge_file',
    'show_markdown_html', 'delete_knowledge_file', 'rename_knowledge_file',
    'create_knowledge_folder', 'get_selected_knowledge_files',
    'ingest_selected_knowledge_files', 'ingest_all_knowledge_files',
    'get_knowledge_job_status', 'cancel_knowledge_job', 'retry_failed_knowledge_files',
    'get_knowledge_file_status', 'list_knowledge_trash', 'restore_knowledge_file',
    'permanently_delete_knowledge_trash', 'extract_selected_file_graphs',
    'extract_all_file_graphs', 'delete_file_graph', 'retry_failed_graph_extraction',
  ]],
  ['book', [
    'list_library_items', 'list_library_tags', 'add_library_book', 'add_library_collection',
    'update_library_item', 'remove_library_item', 'get_library_item',
    'list_favorites', 'add_favorite', 'remove_favorite',
  ]],
  ['checklist', [
    'get_task_list_status', 'create_task_list', 'complete_task_list_item', 'finish_task_list',
    'list_smart_forms', 'create_smart_form', 'get_smart_form', 'get_smart_form_schema',
    'update_smart_form', 'patch_smart_form_rows', 'get_smart_form_literature',
    'export_smart_form', 'import_smart_form', 'preview_smart_form_fill',
    'fill_smart_form_cells',
  ]],
  ['todo', [
    'list_todos', 'add_todo', 'add_automation', 'toggle_todo', 'edit_todo', 'delete_todo',
    'list_user_feedback', 'get_user_feedback', 'create_user_feedback',
    'update_user_feedback', 'delete_user_feedback',
  ]],
  ['group', ['spawn_child_agent', 'wait_for_child_agents']],
  ['language', ['web_search', 'web_image_search']],
]

/** Provides constant-time icon lookup while keeping the category list readable. */
const TOOL_ICON_BY_NAME = new Map(
  TOOL_ICON_GROUPS.flatMap(([iconName, toolNames]) => toolNames.map((toolName) => [toolName, iconName])),
)

/** Returns a locally bundled IcIcon name for a registered or extension tool. */
export function toolIconName(toolName: string): string {
  return TOOL_ICON_BY_NAME.get(toolName) ?? 'build'
}
