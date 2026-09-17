/*
 * Obs token aggregation tests.
 *
 * Usage:
 * Locks the dashboard token chart contract to model pools only. Runtime nodes
 * and concrete provider model names must never become chart series.
 */

import { describe, expect, it } from 'vitest'

import {
  buildAllSessionLatencyTurns,
  buildContextAssembly,
  buildExactRequestAssembly,
  buildLatencyTurns,
  buildRagHistory,
  buildRagMetrics,
  buildTokenSeries,
} from '../useObsData'

describe('buildTokenSeries', () => {
  it('aggregates token usage by large/small model pool only', () => {
    const series = buildTokenSeries([
      {
        role: 'assistant',
        created_at: '2026-07-16T15:00:00.000Z',
        trace: [
          {
            node: 'safety_input',
            event: 'passed',
            model_tier: 'runtime',
            model_name: 'safety_input',
            token_usage: { total_tokens: 1 },
          },
          {
            node: 'agent',
            event: 'model_response',
            model_tier: 'large',
            model_name: 'deepseek-v4-flash',
            token_usage: { input_tokens: 400, output_tokens: 53, total_tokens: 453 },
          },
          {
            node: 'planner',
            event: 'strategy_generated',
            model_tier: 'small',
            model_name: 'moonshot-v1-8k',
            token_usage: { total_tokens: 5 },
          },
          {
            node: 'action',
            event: 'tool_call_end',
            model_tier: 'runtime',
            model_name: 'action',
            token_usage: { total_tokens: 4 },
          },
          {
            node: 'safety_output',
            event: 'passed',
            model_tier: 'runtime',
            model_name: 'safety_output',
            token_usage: { total_tokens: 1 },
          },
        ],
      },
    ])

    expect(series).toHaveLength(1)
    expect(series[0]?.modelTokens).toEqual({
      '\u5927\u6a21\u578b': 453,
      '\u5c0f\u6a21\u578b': 5,
    })
    expect(Object.keys(series[0]?.modelTokens || {})).not.toContain('safety_input')
    expect(Object.keys(series[0]?.modelTokens || {})).not.toContain('safety_output')
    expect(Object.keys(series[0]?.modelTokens || {})).not.toContain('action')
    expect(Object.keys(series[0]?.modelTokens || {})).not.toContain('deepseek-v4-flash')
    expect(Object.keys(series[0]?.modelTokens || {})).not.toContain('moonshot-v1-8k')
  })
})

describe('buildRagMetrics', () => {
  it('uses cumulative session metrics instead of the latest system message only', () => {
    const messages = [
      {
        role: 'system',
        metadata: {
          rag_metrics: {
            fill_rate: 50,
            avg_relevance: 80,
            confidence: 70,
            memory_count: 1,
            knowledge_count: 2,
            important_count: 1,
          },
        },
      },
      {
        role: 'system',
        metadata: {
          rag_metrics: {
            fill_rate: 100,
            avg_relevance: 60,
            confidence: 90,
            memory_count: 3,
            knowledge_count: 4,
            important_count: 2,
          },
        },
      },
    ]

    expect(buildRagMetrics(messages)).toEqual({
      fillRate: 75,
      avgRelevance: 70,
      confidence: 80,
      memoryCount: 4,
      knowledgeCount: 6,
      importantCount: 3,
      turnCount: 2,
    })
    expect(buildRagHistory(messages)).toEqual([
      { turn: 1, fillRate: 50, avgRelevance: 80, confidence: 70 },
      { turn: 2, fillRate: 75, avgRelevance: 70, confidence: 80 },
    ])
  })

  it('includes knowledge retrieval tool calls in cumulative RAG metrics', () => {
    const messages = [
      {
        role: 'system',
        metadata: {
          rag_metrics: {
            fill_rate: 50,
            avg_relevance: 80,
            confidence: 70,
            memory_count: 1,
            knowledge_count: 2,
            important_count: 0,
          },
        },
      },
      {
        role: 'assistant',
        trace: [
          {
            node: 'action',
            event: 'tool_call_start',
            tool_call_id: 'call_1',
            tool_name: 'get_knowledge_context',
            tool_args_summary: 'query=test, top_k=4',
          },
          {
            node: 'action',
            event: 'tool_call_end',
            tool_call_id: 'call_1',
            tool_name: 'get_knowledge_context',
            result_count: 2,
            raw_content: '1. [K1] source\\n2. [K2] source',
          },
        ],
      },
    ]

    expect(buildRagMetrics(messages)).toEqual({
      fillRate: 50,
      avgRelevance: 40,
      confidence: 85,
      memoryCount: 1,
      knowledgeCount: 4,
      importantCount: 0,
      turnCount: 2,
    })
    expect(buildRagHistory(messages)).toEqual([
      { turn: 1, fillRate: 50, avgRelevance: 80, confidence: 70 },
      { turn: 2, fillRate: 50, avgRelevance: 40, confidence: 85 },
    ])
  })

  it('counts search and read knowledge tools as RAG samples', () => {
    const messages = [
      {
        role: 'system',
        metadata: {
          rag_metrics: {
            fill_rate: 50,
            avg_relevance: 100,
            confidence: 80,
            memory_count: 1,
            knowledge_count: 1,
            important_count: 0,
          },
        },
      },
      {
        role: 'assistant',
        trace: [
          {
            node: 'action',
            event: 'tool_call_start',
            tool_call_id: 'search_1',
            tool_name: 'search_knowledge',
            tool_args_summary: 'query=崩铁',
          },
          {
            node: 'action',
            event: 'tool_call_end',
            tool_call_id: 'search_1',
            tool_name: 'search_knowledge',
            raw_content: '=== 内容匹配 ===\\n  [K1] 崩铁.md\\n  [K2] docs/区别.md',
          },
          {
            node: 'action',
            event: 'tool_call_end',
            tool_call_id: 'read_1',
            tool_name: 'read_file',
            raw_content: '## 崩铁\\n完整文件内容',
          },
        ],
      },
    ]

    expect(buildRagMetrics(messages)).toEqual({
      fillRate: 72.2,
      avgRelevance: 33.3,
      confidence: 93.3,
      memoryCount: 1,
      knowledgeCount: 4,
      importantCount: 0,
      turnCount: 3,
    })
    expect(buildRagHistory(messages)).toEqual([
      { turn: 1, fillRate: 50, avgRelevance: 100, confidence: 80 },
      { turn: 2, fillRate: 58.4, avgRelevance: 50, confidence: 90 },
      { turn: 3, fillRate: 72.2, avgRelevance: 33.3, confidence: 93.3 },
    ])
  })
})

describe('buildLatencyTurns', () => {
  it('lays every session turn on one global message timeline', () => {
    const turns = buildAllSessionLatencyTurns([
      {
        sessionId: 'sess_b',
        sessionName: '会话 B',
        messages: [
          { role: 'user', content: 'B', created_at: '2026-07-02T00:00:00Z' },
          { role: 'assistant', content: 'B done', created_at: '2026-07-02T00:00:03Z' },
        ],
      },
      {
        sessionId: 'sess_a',
        sessionName: '会话 A',
        messages: [
          { role: 'user', content: 'A', created_at: '2026-07-01T00:00:00Z' },
          { role: 'assistant', content: 'A done', created_at: '2026-07-01T00:00:02Z' },
        ],
      },
    ])

    expect(turns.map((turn) => ({
      index: turn.index,
      sessionId: turn.sessionId,
      seconds: turn.seconds,
    }))).toEqual([
      { index: 1, sessionId: 'sess_a', seconds: 2 },
      { index: 2, sessionId: 'sess_b', seconds: 3 },
    ])
  })

  it('keeps each message node duration breakdown independent', () => {
    const turns = buildLatencyTurns([
      { role: 'user', content: 'first', created_at: '2026-07-16T10:00:00.000Z' },
      {
        role: 'assistant',
        content: 'first answer',
        created_at: '2026-07-16T10:00:01.000Z',
        trace: [
          { node: 'safety_input', duration_ms: 20 },
          { node: 'agent', duration_ms: 80 },
        ],
      },
      { role: 'user', content: 'second', created_at: '2026-07-16T10:00:02.000Z' },
      {
        role: 'assistant',
        content: 'second answer',
        created_at: '2026-07-16T10:00:03.000Z',
        trace: [
          { node: 'planner', duration_ms: 50 },
          { node: 'agent', duration_ms: 50 },
        ],
      },
    ])

    expect(turns).toHaveLength(2)
    expect(turns[1]?.cumulativeSeconds).toBe(0.2)
    expect(Object.fromEntries((turns[1]?.nodeBreakdown || []).map((item) => [item.node, item.durationMs]))).toEqual({
      agent: 50,
      planner: 50,
    })
  })

  it('uses the latest cumulative trace snapshot once per message', () => {
    const turns = buildLatencyTurns([
      { role: 'user', content: 'run', created_at: '2026-07-16T10:00:00.000Z' },
      {
        role: 'assistant',
        content: '',
        node: 'planner',
        trace: [{ node: 'planner', duration_ms: 40 }],
      },
      {
        role: 'assistant',
        content: 'done',
        trace: [
          { node: 'planner', duration_ms: 40 },
          { node: 'agent', duration_ms: 60 },
        ],
      },
    ])

    expect(turns[0]?.seconds).toBe(0.1)
    expect(Object.fromEntries((turns[0]?.nodeBreakdown || []).map((item) => [item.node, item.durationMs]))).toEqual({
      planner: 40,
      agent: 60,
    })
  })
})

describe('buildContextAssembly', () => {
  it('splits skill routing sections into a dedicated context block', () => {
    const assembly = buildContextAssembly([
      {
        role: 'system',
        content: [
          '核心系统提示',
          '[Candidate skills]',
          '- builtin:web-access: web-access (builtin): 联网访问',
          '[Routed skills for this turn]',
          '--- Skill: web-access [builtin:web-access] ---',
          'Use browser tools for web tasks.',
          '--- End Skill ---',
        ].join('\n'),
      },
      { role: 'user', content: '搜索最新资料' },
    ])

    const skillBlock = assembly.blocks.find((block) => block.type === 'skills')

    expect(skillBlock?.title).toBe('Skill 候选与正文')
    expect(skillBlock?.lines).toContain('[Candidate skills]')
    expect(skillBlock?.lines).toContain('[Routed skills for this turn]')
    expect(assembly.blocks.find((block) => block.type === 'system')?.lines).toEqual(['核心系统提示'])
  })
})

describe('buildExactRequestAssembly', () => {
  it('preserves exact message fields and full tool schemas without heuristic regrouping', () => {
    const assembly = buildExactRequestAssembly({
      messages: [
        { role: 'system', content: 'final system\nwith spacing' },
        { role: 'assistant', content: '', tool_calls: [{ id: 'call-1', name: 'search', args: { q: 'x' } }] },
        { role: 'tool', content: 'result', tool_call_id: 'call-1' },
      ],
      tools: [{ type: 'function', function: { name: 'search', parameters: { type: 'object' } } }],
    })

    expect(assembly.blocks.map((block) => block.type)).toEqual([
      'message_system',
      'message_assistant',
      'message_tool',
      'tool_schema',
    ])
    expect(assembly.blocks[0]?.lines[0]).toBe('final system\nwith spacing')
    expect(assembly.blocks[1]?.lines[1]).toContain('call-1')
    expect(assembly.blocks[3]?.lines[0]).toContain('"parameters"')
  })
})
