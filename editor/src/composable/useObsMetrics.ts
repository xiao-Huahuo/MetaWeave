/*
 * Obs RAG metric derivation helpers.
 *
 * Usage:
 * Provides pure RAG metric and history builders for useObsData.
 */

import type { RagHistoryPoint, RagMetrics } from '@/composable/useObsData'

const KNOWLEDGE_RECALL_TOOLS = new Set([
  'get_knowledge_context',
  'search_knowledge',
  'read_file',
  'read_knowledge_file',
  'read_session_attachment',
  'search_knowledge_graph_nodes',
  'find_knowledge_graph_paths',
])

interface RagMetricTotals {
  fillRate: number
  avgRelevance: number
  confidence: number
  memoryCount: number
  knowledgeCount: number
  importantCount: number
}

function safeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : []
}

function roundNumber(value: unknown, digits = 1): number {
  return Number.parseFloat(Number(value || 0).toFixed(digits))
}

function extractTopKFromArgs(summary: unknown, fallback = 3): number {
  const text = String(summary || '')
  const match = text.match(/top_k\s*[:=]\s*(\d+)/i) || text.match(/"top_k"\s*:\s*(\d+)/i)
  const value = match ? Number(match[1]) : fallback
  return Number.isFinite(value) && value > 0 ? value : fallback
}

function extractConfidenceFromText(text: unknown, fallback: number): number {
  const source = String(text || '')
  const match = source.match(/(?:confidence|rerank|score|merged_score|final_score)\D*(\d+(?:\.\d+)?)/i)
  if (!match) return fallback
  const raw = Number(match[1])
  if (!Number.isFinite(raw)) return fallback
  return roundNumber(raw <= 1 ? raw * 100 : Math.min(raw, 100), 1)
}

function isEmptyToolResult(text: unknown): boolean {
  const source = String(text || '').trim().toLowerCase()
  if (!source) return true
  return [
    '未找到',
    '没有找到',
    '无相关',
    'no result',
    'not found',
    '执行失败',
    '失败',
    'error',
  ].some((pattern) => source.includes(pattern))
}

function inferKnowledgeResultCount(trace: Record<string, unknown>, toolName: string): number {
  const explicit = Number(trace.result_count || 0)
  if (explicit > 0) return explicit
  const text = String(trace.raw_content || '')
  if (isEmptyToolResult(text)) return 0

  const citationMatches = text.match(/\[[A-Z]?\d+\]/g)
  if (citationMatches?.length) return citationMatches.length
  const numberedMatches = text.match(/(?:^|\n)\s*\d+\.\s+/g)
  if (numberedMatches?.length) return numberedMatches.length
  const fileMatches = text.match(/(?:^|\n)\s*(?:[-*]\s*)?[\w./\\\-\u4e00-\u9fa5]+\.(?:md|txt|pdf|docx?|xlsx?|csv|png|jpe?g)\b/gi)
  if (fileMatches?.length) return fileMatches.length

  return toolName.startsWith('read_') || toolName === 'search_knowledge' ? 1 : 0
}

function metricSampleFromKnowledgeTool(trace: Record<string, unknown>, startTrace?: Record<string, unknown>): Record<string, unknown> | null {
  const toolName = String(trace.tool_name || '')
  if (trace.event !== 'tool_call_end' || !KNOWLEDGE_RECALL_TOOLS.has(toolName)) return null
  const resultCount = inferKnowledgeResultCount(trace, toolName)
  const topK = toolName.startsWith('read_') ? 1 : extractTopKFromArgs(startTrace?.tool_args_summary, 3)
  const hasResults = resultCount > 0
  const baseConfidence = hasResults ? 100 : 0
  return {
    fill_rate: roundNumber(Math.min((resultCount / topK) * 100, 100), 1),
    avg_relevance: extractConfidenceFromText(trace.raw_content, 0),
    confidence: extractConfidenceFromText(trace.raw_content, baseConfidence),
    memory_count: 0,
    knowledge_count: resultCount,
    important_count: 0,
  }
}

function collectRagMetrics(
  messages: Array<{ role: string; metadata?: unknown; trace?: unknown }>,
): Array<Record<string, unknown>> {
  const metrics: Array<Record<string, unknown>> = []
  for (const message of safeArray<{ role: string; metadata?: unknown; trace?: unknown }>(messages)) {
    if (message.role === 'system') {
      const systemMetrics = (message.metadata as Record<string, unknown> | undefined)?.rag_metrics as Record<string, unknown> | undefined
      if (systemMetrics) metrics.push(systemMetrics)
      continue
    }
    if (message.role !== 'assistant') continue
    const starts = new Map<string, Record<string, unknown>>()
    for (const trace of safeArray<Record<string, unknown>>(message.trace)) {
      const callId = String(trace.tool_call_id || '')
      if (trace.event === 'tool_call_start' && callId) {
        starts.set(callId, trace)
        continue
      }
      const toolMetrics = metricSampleFromKnowledgeTool(trace, starts.get(callId))
      if (toolMetrics) metrics.push(toolMetrics)
    }
  }
  return metrics
}

export function buildRagMetrics(messages: Array<{ role: string; metadata?: unknown; trace?: unknown }>): RagMetrics {
  const metrics = collectRagMetrics(messages)
  if (metrics.length === 0) {
    return {
      fillRate: 0,
      avgRelevance: 0,
      confidence: 0,
      memoryCount: 0,
      knowledgeCount: 0,
      importantCount: 0,
      turnCount: 0,
    }
  }

  const totals = metrics.reduce<RagMetricTotals>((acc, metric) => ({
    fillRate: acc.fillRate + Number(metric.fill_rate || 0),
    avgRelevance: acc.avgRelevance + Number(metric.avg_relevance || 0),
    confidence: acc.confidence + Number(metric.confidence || 0),
    memoryCount: acc.memoryCount + Number(metric.memory_count || 0),
    knowledgeCount: acc.knowledgeCount + Number(metric.knowledge_count || 0),
    importantCount: acc.importantCount + Number(metric.important_count || 0),
  }), {
    fillRate: 0,
    avgRelevance: 0,
    confidence: 0,
    memoryCount: 0,
    knowledgeCount: 0,
    importantCount: 0,
  })

  return {
    fillRate: roundNumber(totals.fillRate / metrics.length, 1),
    avgRelevance: roundNumber(totals.avgRelevance / metrics.length, 1),
    confidence: roundNumber(totals.confidence / metrics.length, 1),
    memoryCount: totals.memoryCount,
    knowledgeCount: totals.knowledgeCount,
    importantCount: totals.importantCount,
    turnCount: metrics.length,
  }
}

export function buildRagHistory(messages: Array<{ role: string; metadata?: unknown; trace?: unknown }>): RagHistoryPoint[] {
  const points: RagHistoryPoint[] = []
  let turnIndex = 0
  let fillRateTotal = 0
  let avgRelevanceTotal = 0
  let confidenceTotal = 0

  for (const metric of collectRagMetrics(messages)) {
    turnIndex += 1
    fillRateTotal += Number(metric.fill_rate || 0)
    avgRelevanceTotal += Number(metric.avg_relevance || 0)
    confidenceTotal += Number(metric.confidence || 0)
    points.push({
      turn: turnIndex,
      fillRate: roundNumber(fillRateTotal / turnIndex, 1),
      avgRelevance: roundNumber(avgRelevanceTotal / turnIndex, 1),
      confidence: roundNumber(confidenceTotal / turnIndex, 1),
    })
  }

  return points
}
