# Agent 上下文与工具结果硬截断迁移清单

> 状态：`dynamic-v1` 已实施。下方第 1～5 节保留的是迁移前的穷举基线，用于证明旧硬截断来源已经逐项处理，不代表当前运行行为。

## 当前生产配置

当前模型可见内容只使用以下集中容量配置，不再由散落字符数决定：

| 配置字段 | 默认值 | 当前作用 |
|---|---:|---|
| `memory.context_window_tokens` | 1,000,000 tokens | 服务允许使用的上下文 ceiling。 |
| 未填写模型窗口 | 1,000,000 tokens | 直接继承 `memory.context_window_tokens` 服务默认值，不再存在 128K fallback。 |
| `memory.context_unknown_output_fallback_tokens` | 8,192 tokens | 未登记模型的保守最大输出。 |
| `memory.context_output_reserve_ratio` | 0.065 | 从有效窗口动态推导输出预留。 |
| `memory.context_safety_margin_ratio` | 0.02 | tokenizer、消息包装与协议安全边际。 |
| `memory.context_max_single_block_ratio` | 0.20 | 单个弹性候选组的动态软上限。 |
| `memory.context_compression_trigger_ratio` | 0.80 | 动态压缩触发比例。 |
| `memory.context_compression_target_ratio` | 0.45 | 动态压缩目标比例。 |
| `memory.context_budget_policy_version` | `dynamic-v1` | Debug、观测和迁移识别使用的策略版本。 |
| `model.model_context_window_tokens` / `model.model_max_output_tokens` | 0 / 0 | 主模型能力覆盖；0 表示继续解析能力表或 fallback。 |
| `model.small_model_context_window_tokens` / `model.small_model_max_output_tokens` | 0 / 0 | 小模型能力覆盖；0 表示继承或继续解析。 |
| `model.model_capabilities` | `{}` | 按模型名登记明确窗口和最大输出。 |

真实请求统一经过 `ContextBuilder.assemble_request_messages`：固定块先扣除，弹性候选按原子组竞争剩余 token；放不下时按 full、structured、head-tail、reference 降级，最终重新计量并校验 tool call / result 配对。非完整工具结果携带 `content_ref` 与 continuation，可通过 `read_tool_result`、`read_file` 或原资源范围读取继续获取。

当前会话附件上传不产生模型可见正文：只保存原文件和 `attachment://` 引用。Agent 首次调用 `read_file` 时才按 OCR/VLM 设置解析并持久化缓存，长结果通过行范围或 cursor 续读；`understand_image` 直接读取原图，并仅把已经存在的 OCR 缓存作为可选辅助。

## 迁移前审计结论

迁移前 Agent 可见内容的截断由四层叠加产生：

1. `ContextBuilder` 根据 token 窗口只选择能放入预算的最近历史消息。
2. `ModelDecisionNode` 在每次真正请求主模型前，再按工具类型和结果新旧程度压缩每条 `ToolMessage`。
3. Observation 与 Planner 为各自的小模型重新拼装工具结果，并再次做字符/条数预览。
4. Terminal、Web、Skill、附件、知识文件、识图与图谱抽取等生产端在生成工具结果或内部模型请求时先行截断。

因此，上游工具的较大限制并不代表主 Agent 真能看到同样多的内容。普通工具结果曾在第 2 层收敛到最近 900 字、较旧 240 字，导致 Agent 没读到关键尾部后重复调用工具。

本清单只统计会改变 Agent、Planner、Observation 或 Agent 所调用模型实际可见内容的限制。UI 折叠、日志预览、ID/hash 长度、网络流分块和不丢内容的分页不在范围内。

## 1. 迁移前：主 Agent 会话上下文

| 配置字段 | 默认值 | 生效位置 | 实际作用 |
|---|---:|---|---|
| `memory.context_window_tokens` | 1,000,000 tokens | `services/memory/context_builder.py` | 模型上下文总窗口。 |
| `memory.context_output_reserve_tokens` | 65,536 tokens | `ContextBuilder.compression_limits` | 从总窗口中预留本轮输出，默认可用输入窗口为 934,464 tokens。 |
| `memory.context_compression_trigger_ratio` | 0.8 | `ContextBuilder.should_compress` | 默认约 747,571 tokens 触发同步压缩。 |
| `memory.context_compression_target_ratio` | 0.45 | `CompressNode` | 压缩后默认目标约 420,509 tokens。 |
| `memory.rerank_top_k` | 3 条 | `ContextBuilder._build_retrieved_context` | 自动注入上下文的长期记忆最多 3 条；长期记忆/知识上下文工具未显式传参时也复用该值。 |
| `limits.attachment_context_max_chars` | 16,000 字符 | `SessionAttachmentService.build_context` | 一轮注入的全部附件上下文总预算。 |
| `limits.attachment_single_max_chars` | 8,000 字符 | 同上 | 单附件注入预算。 |
| `limits.attachment_preview_chars` | 500 字符 | 同上 | 未注入附件写入 citation map 的文本预览。 |

历史消息不是按固定条数截断，而是由 `select_recent_messages_within_budget` 从末尾逐条装入 token 预算；遇到第一条放不下的消息即停止继续向前选择。

## 2. 迁移前：ToolMessage 进入主模型前的统一二次压缩

生效入口：`agent_service/agent_core/nodes/model_decision.py::_prepare_messages_for_llm`。

| 配置字段 | 默认值 | 适用范围 |
|---|---:|---|
| `limits.agent_tool_recent_full_result_count` | 最近 4 条 | 决定特殊大型工具是否仍享受大型预算。 |
| `limits.agent_tool_recent_result_count` | 最近 8 条 | 普通工具中，前 8 条使用“最近结果”预算，更旧结果使用“旧结果”预算。 |
| `limits.agent_tool_registry_result_chars` | 6,000 字符 | `list_available_tools` 始终使用；最近 4 条 `run_terminal_command` 也使用。 |
| `limits.agent_tool_large_result_chars` | 12,000 字符 | 最近 4 条 `read_file`、图谱查询、智能表单、组件和自定义 Skill 结果。 |
| `limits.agent_tool_recent_result_chars` | 900 字符 | 未命中特殊类型的最近 8 条普通工具结果。 |
| `limits.agent_tool_old_result_chars` | 240 字符 | 第 9 条及更早的普通工具结果，以及超过“最近 4 条”保护范围后的大型工具结果。 |

截断方式均为保留前缀，并追加“原始长度/当前保留长度”的压缩标记，不保留尾部。MCP 工具没有单独的隐藏截断，格式化完整结果后同样进入本层的 900/240 字符通用预算。

## 3. 迁移前：Planner、Observation 与工具调用序列

| 配置字段 | 默认值 | 生效位置 | 实际作用 |
|---|---:|---|---|
| `limits.agent_observation_tool_result_chars` | 2,000 字符/条 | `nodes/observation.py` | Observation 小模型查看当前 cycle 每条工具结果的前 2,000 字。 |
| `limits.agent_planner_history_limit` | 6 项 | `nodes/planner.py` | Planner 重入时最多拼装 6 项工具/Observation 历史。 |
| `limits.agent_planner_history_preview_chars` | 200 字符/条 | 同上 | Planner 的单条工具结果预览。 |
| `limits.agent_planner_covered_limit` | 8 项 | Planner 解析 | 规划状态保留的已覆盖事项。 |
| `limits.agent_planner_suggested_limit` | 8 项 | Planner 解析 | 规划状态保留的建议事项。 |
| `limits.agent_planner_subquestion_limit` | 5 项 | Planner 提示与解析 | 子问题队列上限。 |
| `limits.agent_planner_hint_chars` | 120 字符 | Planner 提示与解析 | 策略提示长度。 |
| `limits.agent_observation_reason_chars` | 80 字符 | Observation 提示与解析 | Observation 原因文本长度。 |
| `limits.agent_observation_next_action_chars` | 120 字符 | Observation 提示与解析 | 下一动作文本长度。 |
| `limits.agent_max_tool_calls_per_turn` | 4 次 | `nodes/tool_call.py` | 单轮工具调用序列上限；超过后延迟到后续循环，不是字符截断，但会切断本轮工具序列。 |

`agent_tool_argument_preview_chars=80`、`agent_tool_summary_chars=200` 和 `agent_event_content_preview_chars=500` 只影响 trace/API 调试展示，不进入模型请求，因此不算 Agent 上下文截断源。

## 4. 迁移前：工具生产端和工具内部模型请求

| 配置字段 | 默认值 | 工具/路径 | 生产端截断 |
|---|---:|---|---|
| `terminal_sandbox.max_output_chars` | 20,000 字符 | Terminal sandbox | stdout/stderr 生产端输出上限；用户覆盖仍受 `limits.terminal_output_max_chars=200,000` 绝对上限约束。 |
| `limits.terminal_read_default_lines` | 40 行 | Terminal 内置读取 | 未指定时读取行数。 |
| `limits.terminal_read_max_lines` | 1,000 行 | Terminal 内置读取 | 允许请求的最大读取行数。 |
| `limits.web_fetch_max_chars` | 3,000 字符/页 | `web_search` | 每个网页正文抽取上限。 |
| `limits.default_web_search_max_results` | 10 条 | `web_search` / 用户设置降级值 | 默认搜索结果数量；用户级设置可覆盖。 |
| `limits.tool_markdown_projection_max_chars` | 6,000 字符 | `read_file` | Markdown 投影返回前缀。 |
| `limits.knowledge_content_search_limit` | 20 条 | 知识文件内容搜索 | 默认匹配条数。 |
| `memory.knowledge_search_semantic_top_k` | 5 条 | 知识搜索 | 默认语义召回条数。 |
| `limits.graph_search_default_limit` | 20 条 | 图谱节点搜索 | 默认返回条数。 |
| `limits.graph_search_max_limit` | 100 条 | 图谱节点搜索 | 调用方可请求的最大返回条数。 |
| `limits.skill_body_max_chars` | 8,000 字符 | `use_skill` / Skill 路由 | 单份 `SKILL.md` 注入上限。 |
| `limits.skill_index_description_max_chars` | 240 字符 | Skill 路由候选索引 | 单个 Skill 描述上限。 |
| `limits.skill_router_candidate_limit` | 20 个 | Skill 路由 | 送入路由排序/小模型的候选上限。 |
| `limits.skill_router_max_skills` | 3 个 | Skill 路由 | 一轮注入主 Agent 的 Skill 数量上限。 |
| `limits.tool_registry_description_chars` | 100 字符 | `list_available_tools` | 单个工具在工具清单中的首行描述；本次从裸数字迁入 Config。 |
| `limits.tool_attachment_match_preview_count` | 8 个 | 附件采用/识图歧义提示 | 最多展示的附件候选；字段原已存在，本次修复四处 `[:8]` 失联调用点。 |
| `limits.tool_memory_mutation_result_chars` | 200 字符 | 删除长期记忆/规则 | 成功回执中的原内容前缀；本次从裸数字迁入 Config。 |
| `limits.memory_delete_scan_limit` | 200 条 | 删除长期记忆工具 | 按内容匹配删除时最多扫描的记录数。 |
| `limits.structured_prompt_source_chars` | 60,000 字符 | 结构化字段生成 | 发送给结构化生成模型的源文本上限。 |
| `limits.local_vision_ocr_context_chars` | 6,000 字符 | 已删除的旧视觉路径 | 迁移前用于裁剪 OCR 辅助文本；当前字段和运行路径均不存在。 |
| `limits.graph_single_section_max_chars` | 6,000 字符 | 单章节图谱抽取 | 发送给图谱抽取小模型的章节正文；本次从裸数字迁入 Config。 |
| `limits.graph_batch_max_chars` | 12,000 字符/批 | 批量图谱抽取 | 合批字符预算。 |
| `limits.graph_batch_max_sections` | 4 章/批 | 批量图谱抽取 | 单批最多章节数。 |

## 5. 迁移前已登记但不生效的兼容字段

| 字段 | 默认值 | 当前状态 |
|---|---:|---|
| `memory.max_context_messages` | 20 | 旧版固定消息窗口兼容字段；当前不消费。 |
| `memory.summary_trigger_tokens` | 800,000 | 旧版固定压缩阈值兼容字段；当前由窗口比例计算。 |
| `memory.context_compression_tail_messages` | 6 | 当前压缩路径按目标 token 预算选择最近消息，没有消费该字段。 |

这些字段不能被当作当前截断根因，也不应通过修改它们来尝试扩大实际上下文。

## 6. 全库数字切片复核的排除项

修复后重新扫描全部 Python AST。剩余数字切片均属于以下类别，不改变 Agent/工具实际可见内容：

- `stream_adapter.py` 的 60 字日志预览、`scripts/run_demo.py` 的 100/120 字控制台预览；
- Smart Form 的 240 字 UI 卡片摘要；
- session/thread 名称、UUID、checksum 和 hash 后缀；
- Git/颜色/Markdown fence 等协议解析切片；
- 图谱实体数、别名数、描述和 evidence 的领域数据清洗。这些会改变图谱数据模型，但不属于上下文或工具结果拼装层，未在本任务中改动。

## 验收对应

- 根本来源：迁移前四层硬截断仍由第 1～5 节完整留档；当前模型可见容量字段全部收敛到 `AgentConfig` 的模型能力与动态预算配置。
- 上下文拼装：主 Agent、Simple、Planner、Observation、压缩、结构化生成、图谱与远程视觉理解均使用实际模型容量派生的 token 预算。
- 工具结果：运行时生成 `ToolResultEnvelope` 并持久化完整事实；非 full 表示包含状态、原始 token 数、引用与继续读取方法。
- 专项迁移：Terminal 改为显式 head-tail 资源保护；Web、Skill、知识文件、附件、OCR、结构化生成和图谱不再静默保留字符前缀；记忆内容删除改为数据库精确/包含查询。
- 静态门禁：`tests/test_dynamic_context_budget.py` 检查旧字段、旧 compactor 和关键生产路径固定数字切片不得回归；`tests/test_context_tool_truncation_config.py` 保留对非上下文业务限制的配置消费验证。
- 界面冒烟：模型能力设置在 [桌面端](dynamic-context-settings-desktop.png)、[平板端](dynamic-context-settings-tablet.png) 与 [移动端](dynamic-context-settings-mobile.png) 均完成真实页面加载、字段回填和响应式布局检查；前端开发代理已对真实后端完成 GET/PUT 验证。
