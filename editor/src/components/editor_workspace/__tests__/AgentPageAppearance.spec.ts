/**
 * Agent page workspace appearance regression tests.
 *
 * Usage:
 * Verifies the full-page Agent uses the shared workspace card frame and keeps
 * a native draggable scrollbar on the message list.
 */
import { describe, expect, it } from 'vitest'

import agentPanelSource from '@/components/editor_workspace/AgentPanel.vue?raw'
import childConversationDrawerSource from '@/components/editor_workspace/agent_chat/ChildAgentConversationDrawer.vue?raw'
import changeDetailDrawerSource from '@/components/editor_workspace/agent_chat/ChangeDetailDrawer.vue?raw'
import messageListSource from '@/components/editor_workspace/agent_chat/MessageList.vue?raw'
import sessionDrawerSource from '@/components/editor_workspace/agent_chat/SessionDrawer.vue?raw'
import editorWorkspaceSource from '@/views/EditorWorkspace.vue?raw'
import settingsViewSource from '@/views/SettingsView.vue?raw'

describe('Agent page workspace appearance', () => {
  it('shows a draggable vertical scrollbar for the chat history', () => {
    expect(messageListSource).toMatch(/\.message-list \{[^}]*overflow-y: auto;[^}]*scrollbar-width: thin;/s)
    expect(messageListSource).toMatch(/\.message-list::-webkit-scrollbar \{[^}]*width: 10px;/s)
    expect(messageListSource).not.toContain('scrollbar-width: none')
    expect(messageListSource).not.toMatch(/\.message-list::-webkit-scrollbar \{[^}]*display: none;/s)
  })

  it('uses a two-pixel theme outline around the two-pixel Agent workspace ring', () => {
    expect(editorWorkspaceSource).toMatch(
      /\.main-shell\.ide-panel \{[^}]*border: 1px solid var\(--workspace-panel-border\);[^}]*outline: 2px solid var\(--workspace-panel-outline\);[^}]*outline-offset: 2px;[^}]*box-shadow: 0 0 0 2px var\(--workspace-panel-ring\);/s,
    )
    expect(editorWorkspaceSource).not.toMatch(
      /\.main-shell\.ide-panel\.agent-page-main-shell \{[^}]*(?:border: 0|box-shadow: none);/s,
    )
  })

  it('uses the workspace card radius on the Agent session sidebar', () => {
    expect(sessionDrawerSource).toMatch(
      /\.session-drawer\.page-mode \{[^}]*border-radius: var\(--workspace-card-radius\);/s,
    )
    expect(sessionDrawerSource).not.toMatch(
      /\.session-drawer\.page-mode(?:\.open)? \{[^}]*border-radius: 0;/s,
    )
  })

  it('uses one Environment Change control for all three stacked cards', () => {
    expect(agentPanelSource).toContain('aria-label="环境变更"')
    expect(agentPanelSource).toContain('@click="toggleEnvironmentWorkspace"')
    expect(agentPanelSource).toMatch(/environmentCardOpen\.value = nextOpen[\s\S]*taskListCardOpen\.value = nextOpen[\s\S]*childAgentCardOpen\.value = nextOpen/)
    expect(agentPanelSource).not.toContain('aria-label="环境与变更"')
    expect(agentPanelSource).not.toContain('aria-label="任务列表"')
    expect(agentPanelSource).not.toContain('aria-label="子 Agent"')
  })

  it('uses the shared two-by-two frame for child conversation and environment cards', () => {
    expect(childConversationDrawerSource).not.toContain('child-conversation-header')
    expect(childConversationDrawerSource).not.toContain('border-left:')
    expect(childConversationDrawerSource).not.toContain('border-bottom:')
    expect(childConversationDrawerSource).toMatch(
      /\.child-conversation \{[^}]*margin: var\(--space-10\);[^}]*border: 0;[^}]*outline: 2px solid var\(--workspace-panel-outline\);[^}]*outline-offset: 2px;[^}]*border-radius: var\(--workspace-card-radius\);[^}]*box-shadow: 0 0 0 2px var\(--library-form-ring\);/s,
    )
    expect(agentPanelSource).toMatch(
      /\.agent-sidebar-card \{[^}]*border: 0;[^}]*outline: 2px solid var\(--workspace-panel-outline\);[^}]*outline-offset: 2px;[^}]*border-radius: var\(--workspace-card-radius\);[^}]*box-shadow: 0 0 0 2px var\(--library-form-ring\);/s,
    )
  })

  it('matches the Library toolbar and filter-menu controls', () => {
    expect(agentPanelSource).toMatch(/class="topbar-tool-button"[\s\S]*:class="\{ active: environmentWorkspaceOpen \}"[\s\S]*aria-label="环境变更"[\s\S]*<IcIcon name="dns"/)
    expect(agentPanelSource).not.toContain('<span>环境变更</span>')
    expect(agentPanelSource).toMatch(/class="topbar-skill-trigger"[\s\S]*<IcIcon name="auto-awesome"/)
    expect(agentPanelSource).toMatch(/class="topbar-loop-mode-trigger"[\s\S]*<IcIcon name="psychology"/)
    expect(agentPanelSource.match(/class="topbar-filter-menu"/g)).toHaveLength(2)
    expect(agentPanelSource).toMatch(/\.topbar-loop-mode-trigger,[\s\S]*height: 28px;[\s\S]*border-radius: 999px;[\s\S]*background: var\(--color-canvas\);/)
  })

  it('slides the change detail drawer horizontally during enter and leave', () => {
    expect(agentPanelSource).toContain('<Transition name="change-detail-slide">')
    expect(changeDetailDrawerSource).toContain('.change-detail-slide-enter-from')
    expect(changeDetailDrawerSource).toContain('.change-detail-slide-leave-to')
    expect(changeDetailDrawerSource).toMatch(/transform:\s*translateX\(28px\)/)
  })

  it('shows the effective local fallback model in the input control', () => {
    expect(agentPanelSource).toContain("config.effective_model_name?.trim() || config.model_name?.trim() || ''")
    expect(settingsViewSource).toContain("modelName: saved.effective_model_name || saved.model_name")
  })
})
