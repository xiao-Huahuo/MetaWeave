/*
 * Agent tool registry API client.
 *
 * Usage:
 * Debug components call fetchAgentTools() to display the final Agent tool
 * registry exposed by the running backend.
 */

import { apiFetch, apiGet } from '@/api/client'
import { API_ROUTES } from '@/router/api_routes'

export interface AgentToolProperty {
  type?: string
  description?: string
}

export interface AgentToolInfo {
  name: string
  display_name: string
  description: string
  args_schema: {
    properties?: Record<string, AgentToolProperty>
    required?: string[]
  }
  argument_count: number
}

export interface AgentToolListResponse {
  tool_count: number
  tools: AgentToolInfo[]
}

export async function fetchAgentTools(): Promise<AgentToolListResponse> {
  try {
    return await apiGet<AgentToolListResponse>(API_ROUTES.AGENT_TOOLS, undefined, { cache: 'no-store' })
  } catch (error) {
    if (error instanceof SyntaxError) {
      return fetchAgentToolsFromBackendOrigin()
    }
    throw error
  }
}

async function fetchAgentToolsFromBackendOrigin(): Promise<AgentToolListResponse> {
  const response = await apiFetch(`http://127.0.0.1:8002${API_ROUTES.AGENT_TOOLS}`, { cache: 'no-store' })
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<AgentToolListResponse>
}
