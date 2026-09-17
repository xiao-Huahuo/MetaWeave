# Agent 动态上下文预算与超长工具结果治理设计

## 文档状态

- 类型：技术设计 / RFC
- 实施状态：已落地（预算策略 `dynamic-v1`）
- 目标读者：Agent Core、模型调度、工具运行时、记忆与知识服务的维护者
- 关联审计：`docs/acceptance/context_tool_truncation_inventory.md`
- 核心决策：停止用互不相关的字符常数裁剪模型可见内容；所有模型请求统一由实际模型上下文窗口推导 token 预算，超长内容通过结构化摘要、分页、范围读取、引用句柄和显式降级处理，禁止静默保留前缀。

## 1. 摘要

迁移前的系统把上下文容量拆散成大量相互独立的“字符上限”：工具可能先截断一次，`ToolMessage` 进入主模型前再截断一次，Planner 和 Observation 又各自截断一次。即使服务配置了 `context_window_tokens=1_000_000`，普通工具结果仍可能只以 900 字或 240 字进入主模型。上游容量与下游容量没有共同基准，导致以下结果：

- Agent 看不到工具结论、错误尾部或文件后半段，误以为工具未完成并重复调用；
- Planner 和 Observation 根据残缺预览做决策，推动 Agent 进入无效循环；
- Skill、附件、OCR、网页和知识文件被从中间静默切断，系统却仍表现为“读取成功”；
- 修改某一个常数通常无效，因为后续层还存在更小的二次截断；
- 固定写死 100 万 token 又可能超过实际模型窗口，使压缩触发晚于模型服务拒绝请求。

本设计将 `context_window_tokens=1_000_000` 保留为服务允许使用的最大上下文容量，并引入模型能力解析。每次请求先得到有效窗口 `W`，再从 `W` 推导输出预留、安全边际和输入预算。所有消息、工具定义、工具结果、附件和检索内容都使用与当前模型一致的 tokenizer 计量，在一个统一装配器中竞争预算。

这里的目标不是把 900 改成 9000，也不是把所有结果无条件塞满 100 万 token。目标是让任何内容缩减都满足三个条件：

1. 缩减依据来自本次请求的真实 token 预算；
2. 缩减不会破坏工具调用配对、关键结论和错误信息；
3. 被省略的内容始终可定位、可继续读取，并明确告知模型，而不是静默消失。

## 2. 背景与根因

### 2.1 迁移前的四层截断链

当前模型可见内容依次经过：

1. `ContextBuilder` 根据 `context_window_tokens` 和固定输出预留选择历史消息；
2. `ModelDecisionNode._prepare_messages_for_llm` 按工具类型、结果新旧程度把 `ToolMessage` 截成 12,000、6,000、900 或 240 字；
3. Observation 把每条工具结果截成 2,000 字，Planner 把历史截成最多 6 项、每项 200 字；
4. Terminal、Web、Skill、附件、知识文件、OCR 和图谱抽取在结果产生时各自按字符数预截断。

这四层各自只知道自己的常数，不知道最终模型窗口，也不知道其他层已经删掉了什么。实际可见内容由所有上限中的最小值决定。

### 2.2 当前 token 窗口也存在结构性问题

迁移前的 `select_recent_messages_within_budget` 从后向前装入消息，第一条消息放不下时直接停止。若最近存在一条超大的工具结果，该结果之前仍然有价值的历史也不会再参与选择。

当前实现已经分离服务 ceiling 与模型能力：调度器在每次真实调用前分别解析主模型、小模型和视觉模型的上下文窗口与最大输出；未填写模型窗口时直接使用 100 万服务默认值，用户仍可通过正式设置收紧模型能力。旧问题保留在本节作为迁移动机。

## 3. 目标与非目标

### 3.1 目标

- 以有效模型窗口 `W` 作为所有模型可见内容预算的唯一容量基准；
- 模型输入只使用 token 计量，不再使用字符数近似决定保留或删除；
- 主 Agent、Simple、Planner、Observation、摘要、图谱和结构化生成走同一套容量解析与预算对象；
- 保留完整工具结果作为事实源，模型请求只生成适合本轮预算的表示；
- 超长内容支持分页、章节、行范围、continuation cursor 或引用句柄；
- 不再因一条超大消息丢弃其之前的全部历史；
- 任何省略都通过结构化元数据显式呈现，模型能知道省略了什么以及如何继续读取；
- 让上下文压缩、工具装配和可观测快照使用同一份最终请求，预算统计与真实提交完全一致。

### 3.2 非目标

- 不取消 Terminal 输出、网络响应体、上传文件和数据库查询的资源安全上限；这些限制保护内存、磁盘、网络和数据库，不等同于模型上下文预算；
- 不保证任意大文件一次性完整进入模型；生产级方案必须支持分块与继续读取；
- 不用上下文窗口推导密码长度、API 分页、并发数、工具调用次数等无关业务限制；
- 不通过无限增大上下文替代检索、摘要和任务状态管理。

## 4. 设计原则

### 4.1 单一容量基准

所有模型可见内容都从本次请求的 `effective_context_window_tokens` 推导。业务模块不得自行写 `text[:N]` 来控制模型上下文。

### 4.2 完整事实与请求表示分离

持久化消息、工具执行记录和源文件保存完整事实；模型请求中的内容只是该事实针对当前预算生成的表示。装配器不得覆盖、回写或破坏完整事实。

### 4.3 不静默截断

任何非完整表示必须包含：原始 token 数、当前表示 token 数、表示类型、内容引用和继续读取方法。仅保留前缀且不告知模型的行为禁止进入生产路径。

### 4.4 结构优先于文本裁剪

优先传递状态、结论、错误、引用、下一步和可恢复句柄；最后才对不可结构化文本生成 head-tail 表示。工具成功与否不得依赖模型从残缺 stdout 中猜测。

### 4.5 软分配、可借用

历史、工具结果、附件和检索内容不设置互相独立的固定字符配额。它们共享可变预算池，按优先级装配。某一类别没有内容时，预算自动供其他类别使用。

### 4.6 原子消息组

带 `tool_calls` 的 AssistantMessage 与对应 ToolMessage 是不可拆分原子组。装配器要么放入完整合法表示，要么放入经过缩减但仍配对的合法表示，禁止产生孤立工具消息。

## 5. 有效模型窗口解析

### 5.1 三类容量

- `service_context_ceiling`：服务允许使用的最大窗口，默认沿用 1,000,000 tokens；这是运维上限。
- `model_context_window`：当前实际模型声明或人工登记的上下文窗口；这是模型能力。
- `model_max_output_tokens`：当前实际模型允许的最大输出；与上下文窗口一起解析。
- `request_context_override`：特定调用显式要求的更小窗口，仅允许收紧，不允许突破前两者。

有效窗口定义为：

```text
W = min(service_context_ceiling, model_context_window, request_context_override?)
```

若没有 request override，则忽略该项。

### 5.2 模型能力来源及优先级

按可信度从高到低解析：

1. 用户或管理员为具体 `provider + base_url + model_name` 显式登记的能力；
2. 内置版本化模型能力表；
3. 提供商模型元数据接口返回且通过校验的能力；
4. 未登记或未填写窗口的 OpenAI-compatible 模型直接使用服务 ceiling，当前默认 1,000,000 tokens；最大输出未填写时仍使用 8,192 tokens 的输出能力默认值。

服务默认窗口只在没有显式覆盖或模型能力记录时生效，不覆盖已确认的较小窗口。能力来源通过 Debug 请求快照展示为 `service_ceiling_default`。若模型服务返回上下文超限错误，运行时应收紧该模型实例的会话级观测上限并触发一次重新装配，而不是原样重试。

### 5.3 大模型、小模型分别解析

Planner、Observation、摘要和图谱通常使用 small tier；小模型未独立配置时继承主模型窗口，独立配置但未填写窗口时同样使用 100 万服务默认值。每个 `SerializedChatRequest` 都要携带解析后的模型标识和预算策略版本，worker 与前台进程计算结果必须一致。

## 6. 动态预算公式

### 6.1 基础公式

设：

- `W`：本次请求有效上下文窗口；
- `M_out`：模型最大输出 token；
- `r_out`：输出预留比例；
- `r_safe`：序列化误差、tokenizer 差异和提供商隐藏开销的安全比例；
- `O_req`：调用方显式请求的输出 token，可为空。

```text
O_default = ceil(W × r_out)
O = min(M_out, O_req if provided else O_default)
S = ceil(W × r_safe)
B_input = W - O - S
```

初始建议：

- `r_out = 0.065`，使百万窗口默认预留约 65K 输出，与当前行为接近；
- `r_safe = 0.02`，吸收序列化与 tokenizer 误差；
- 保留现有压缩触发比例 `0.8` 和目标比例 `0.45`，但它们作用于 `B_input`，不再作用于一个未经模型校验的固定窗口。

这些比例是集中式策略参数，不允许业务模块复制计算或另写字符常数。

### 6.2 固定成本与弹性池

装配前先计算不可静默删除的固定成本：

```text
F = system_prompt
  + current_user_request
  + protocol_overhead
  + selected_tool_schemas
  + mandatory_skill_bodies
  + active_safety_instructions

P = max(B_input - F, 0)
```

`P` 是历史、当前 cycle 工具结果、压缩状态、记忆、附件和检索内容共享的弹性池。

如果 `F > B_input`，不得通过切掉当前用户问题或半份 Skill 来伪造成功。处理顺序为：

1. 减少非必要工具 schema，只保留本轮相关工具和工具发现入口；
2. 移除非必要检索提示和重复系统文本；
3. 对可外置的用户引用或附件建立引用句柄；
4. 若仍超限，返回明确的 `context_capacity_exceeded`，说明哪个强制块超过模型能力并建议切换更大模型或拆分输入。

### 6.3 不设置刚性类别配额

系统不规定“工具结果固定占 20%”“附件固定占 10%”一类不可借用配额。候选内容按优先级和表示质量装入 `P`。为了防止单一结果垄断窗口，可以设置一个集中式 `max_single_block_ratio`，但超出后不是截前缀，而是切换到下一表示层级并保留引用。

## 7. 统一上下文装配算法

### 7.1 候选原子组

`ContextBuilder` 把输入转换为候选组：

- 当前用户消息；
- 普通 user/assistant 对话轮次；
- assistant tool call + 对应一个或多个 tool results；
- 压缩状态；
- 长期记忆或检索片段；
- 附件目录和附件内容片段；
- 选中的 Skill 正文；
- 系统与安全指令。

每个候选组携带：

- `source_id` 与来源类型；
- 原始 token 数；
- 优先级与时间；
- 是否强制；
- 是否仍属于当前未完成 cycle；
- 可用表示层级；
- 引用与继续读取方法。

### 7.2 表示层级

同一内容允许按预算选择以下表示，顺序从高到低：

1. `full`：完整原文；
2. `structured`：工具提供的结构化状态、结论、错误、关键字段和引用；
3. `head_tail`：在分配到的 token 预算内保留开头与结尾，中间插入明确省略元数据；
4. `reference`：只保留摘要、内容句柄、原始长度、目录/章节信息和继续读取指令。

不是每类内容都允许所有层级。例如选中的主 `SKILL.md` 必须是 `full`；工具 stdout 可以使用 `structured` 或 `head_tail`；已完成的旧工具结果可以退化为 `reference`。

### 7.3 优先级顺序

推荐优先级：

1. 当前用户请求、系统约束和强制 Skill；
2. 当前未完成 cycle 的工具调用、工具结果和错误；
3. 当前计划、未完成动作与压缩状态；
4. 与当前问题直接相关的近期对话；
5. 高相关长期记忆、附件与知识检索片段；
6. 已完成旧轮次和低相关背景。

同一优先级内综合相关性、时间和表示质量排序。排序规则集中在装配器中，不允许工具名分支散落到 `ModelDecisionNode`。

### 7.4 装配过程

```text
1. 解析模型能力并生成 ContextBudget。
2. 序列化强制块并计算真实 token 成本。
3. 将历史、工具结果、检索和附件转换为原子候选组。
4. 按优先级遍历候选组：
   a. full 能放入则放入；
   b. 否则尝试 structured；
   c. 否则尝试 head_tail；
   d. 否则放入 reference；
   e. 当前候选无法放入时继续检查后续候选，不得 break。
5. 过滤并校验工具调用配对。
6. 对最终序列化请求重新计数；超过 B_input 时从最低优先级开始逐级降级。
7. 生成与真实提交相同的 observability snapshot 后调用模型。
```

最终校验必须使用序列化后的 messages 和 tool schemas，而不是装配前的对象估算。

## 8. 工具结果协议

### 8.1 ToolResultEnvelope

工具执行仍保留人类可读正文，但同时产生统一结构化信封：

```json
{
  "tool_call_id": "call_123",
  "tool_name": "run_terminal_command",
  "status": "success|error|partial|cancelled",
  "summary": "pytest: 21 passed",
  "key_facts": ["exit_code=0", "duration_ms=8310"],
  "error": null,
  "content_ref": "tool-result://session/message-or-call-id",
  "content_type": "text/plain",
  "original_tokens": 48321,
  "representation": "full",
  "continuation": {
    "supported": true,
    "method": "read_tool_result",
    "cursor": null
  },
  "citations": []
}
```

`summary` 由工具根据确定性结构生成，不能用通用字符串前缀冒充摘要。对于无法结构化的 MCP 文本，运行时至少提供状态、原始长度、content ref 和 head-tail 表示。

### 8.2 完整结果的事实源

当前 `ToolMessage` 和正式会话消息已经能够保存完整结果，主模型装配时不应修改它们。对于 Terminal 等生产端为了内存安全不得把无限输出放入消息的工具，超出执行安全上限的部分进入正式受管结果文件或 blob：

- 由服务层创建并记录所有者、session、tool call、大小和校验值；
- 生命周期至少覆盖当前会话，删除会话时统一回收；
- API 和工具读取必须执行 user/session 权限校验；
- 日志不得打印结果正文；
- 不使用随手临时文件或前端存储冒充持久化。

### 8.3 继续读取工具

新增或统一以下能力：

- `read_tool_result(content_ref, start_line?, end_line?, cursor?)`；
- 返回本次片段、总行数/token 数、下一 cursor 和是否结束；
- 对 JSON 支持 JSON Pointer/字段选择，对表格支持行范围，对文本支持行/章节范围；
- 每次返回仍由本轮动态 token 预算决定，不再接受任意字符上限。

模型看到 `reference` 或 `partial` 表示时，能够明确调用该工具继续读取，而不是重复执行原工具。

## 9. 特定实现优化

### 9.1 主 Agent 的 ToolMessage

删除 `agent_tool_recent_result_chars`、`agent_tool_old_result_chars`、按工具名选择 6K/12K 的分支和 `_compact_tool_message` 前缀裁剪。

替代方式：所有 ToolMessage 先转换为候选原子组；当前 cycle 的结果优先使用 full 或 structured，旧结果根据预算降级为 structured/reference。结果新旧只影响优先级，不再直接映射到固定字符数。

### 9.2 Planner

Planner 不再读取“最多 6 项、每项 200 字”的工具文本。它读取结构化执行账本：

- 调用了什么工具；
- 状态和关键结论；
- 是否满足当前子问题；
- 错误类别和可恢复动作；
- `content_ref`；
- 与计划事项的关联。

账本按 Planner 小模型的 `W_small` 动态装配。旧事项可合并为已完成状态，但未完成事项和最近失败必须保留。

### 9.3 Observation

Observation 优先使用 ToolResultEnvelope，而不是每条结果前 2,000 字。对于 success，通常只需状态、关键事实和引用；对于 error，必须包含异常类型、退出码、stderr 尾部和恢复建议。只有判断确实依赖原文时才从弹性池分配 raw excerpt。

### 9.4 Terminal

- 返回 exit code、cwd、每段命令状态、stdout/stderr 行数和确定性摘要；
- 短输出直接 full；长输出返回 head-tail 和受管 `content_ref`；
- stderr 尾部优先级高于 stdout 开头，测试汇总和最终错误不得被中间日志挤掉；
- 通过 `read_tool_result` 按行继续读取，禁止要求 Agent 重跑命令只为查看尾部；
- `terminal_sandbox.max_output_chars` 保留为进程内存安全阈值，但不再被当作模型上下文预算。

### 9.5 知识文件与普通文件

- `read_file` 接受知识库相对路径或 `attachment://` 引用，模型不再选择不同的读取工具；
- 知识库路径返回规范 Markdown 投影并登记 citation；工具结果过长时由统一结果信封和 `read_tool_result` 继续读取；
- 会话附件首次读取时生成缓存，支持 `start_line/end_line` 和 cursor；
- 小文件在预算允许时完整进入本轮，大结果不得静默只保留固定 6,000 字前缀；
- 当前知识库路径尚未暴露 `section_id` 参数；按章节读取属于后续增强，不在本设计中冒充已落地能力。

### 9.6 Web 搜索与网页

- 搜索工具返回标题、URL、摘要、发布日期和 citation id，不把每页全文直接串联；
- 抓取正文按标题、段落和正文块建立来源记录；
- 主 Agent根据问题选择相关块，必要时按 citation id 继续读取；
- 3,000 字符网页前缀限制改为抓取资源安全上限 + 动态模型表示，正文尾部不会静默丢失；
- citation map 指向完整来源记录，模型表示缩减不影响最终引用追踪。

### 9.7 Skill

- 选中的主 `SKILL.md` 必须完整进入本轮强制块，禁止 `[:8000]`；
- Skill 的 references、scripts、assets 和 templates 按 Skill 指令需要读取，不自动全部注入；
- 若单份主 Skill 本身超过 `B_input`，返回明确错误并指出所需 token，不得加载半份；
- Skill 候选数量和最大选中数量属于路由策略，可保留独立数量限制，因为它们不是字符预算；
- 多个 Skill 同时命中且强制块超限时，路由器必须减少选择或请求用户决策，不能分别截断。

### 9.8 附件

- 上传只保存原文件并登记 `attachment://` 引用；未解析附件进入上下文的只有目录信息；
- Agent 调用 `read_file` 后才使用 OCR/VLM 配置生成正文缓存，重复读取复用同一缓存；
- 小型附件正文由工具结果参与动态 token 预算，长正文通过 `start_line/end_line` 或 cursor 继续读取；
- 不再使用单附件 8K、总计 16K 的上传后前缀注入，也不会为了建立上下文而自动解析附件；
- citation map 保存原文件引用；已解析且与当前问题相关的缓存正文才可能进入后续上下文。

### 9.9 OCR 与视觉理解

- OCR 仅在 `read_file` 确实需要读取图片文字或扫描文档时执行，结果作为附件派生缓存保存；
- `understand_image` 直接发送原图，不以前置 OCR 为条件；已有 OCR 缓存时可作为辅助证据；
- 视觉请求的文本部分由统一调度器按当前视觉模型窗口计量，超限时明确失败而不是静默截取前缀；
- 当前实现一次处理一张会话图片；长图、多页分区理解属于后续能力，不在现有行为中宣称已完成。

### 9.10 图谱抽取

- 6K 单章节值可以作为抽取块的目标大小，但不能作为前缀截断点；
- 超长章节按 token 切为带重叠和原始 offset 的子块；
- 每个子块独立抽取，关系 evidence 必须带原文 offset；
- 子块结果按规范实体、关系和证据去重合并；
- 批次仍受小模型 `W_small` 动态预算约束，章节数只是并发/批处理安全参数。

### 9.11 长期记忆与检索

- 自动注入和显式工具查询不再共用 `rerank_top_k=3`；
- 自动注入按相关性和可用 token 预算选择，达到边际收益阈值后停止；
- 显式查询支持 cursor 与调用方意图，可返回更多结果摘要；
- 删除记忆使用数据库精确查询或有序候选选择，不扫描前 200 条后谎报不存在；
- 记忆正文进入模型时同样使用 full/structured/reference 表示。

### 9.12 工具 Schema

工具定义的 token 成本已经可以估算，应正式纳入固定成本 `F`。当全部工具 schema 过大时：

1. 始终保留当前任务高相关工具、工具发现工具和继续读取工具；
2. 使用现有工具分类/路由选择其余 schema；
3. 路由置信度不足且预算允许时绑定全部；
4. 不允许为了保留工具 schema 而静默删除当前用户请求。

## 10. 配置模型

### 10.1 保留和新增

建议保留或新增以下集中配置：

```text
memory.context_window_tokens                 # 服务级上限，默认 1_000_000
memory.context_unknown_output_fallback_tokens # 未知模型最大输出，默认 8_192
memory.context_output_reserve_ratio          # 输出预留比例
memory.context_safety_margin_ratio            # tokenizer/协议安全边际
memory.context_compression_trigger_ratio      # 触发比例
memory.context_compression_target_ratio       # 压缩目标比例
memory.context_max_single_block_ratio         # 单候选组软上限
memory.context_budget_policy_version          # 预算策略版本
```

模型能力按 `provider/base_url/model_name` 登记在正式模型配置中，不应散落在节点代码。

### 10.2 删除或弃用

以下模型上下文字符配置已经删除或停止作为模型可见内容限制使用：

- `agent_tool_registry_result_chars`；
- `agent_tool_large_result_chars`；
- `agent_tool_recent_result_chars`；
- `agent_tool_old_result_chars`；
- `agent_observation_tool_result_chars`；
- `agent_planner_history_preview_chars`；
- `attachment_context_max_chars`；
- `attachment_single_max_chars`；
- `skill_body_max_chars`；
- `web_fetch_max_chars` 作为模型可见正文限制的含义；
- `tool_markdown_projection_max_chars`；
- `local_vision_ocr_context_chars`；
- `graph_single_section_max_chars` 作为截断含义的用法。

工具执行、网络和存储仍可保留 byte/line/record 安全上限，但字段命名和文档必须明确其保护的是资源，而不是模型上下文。

### 10.3 不应由 W 推导的限制

以下限制保持独立：密码长度、文件名长度、API 分页、数据库扫描、并发数、超时、重试次数、工具调用次数、日志预览和 UI 摘要。把它们乘以窗口比例没有语义基础，只会制造新的数字游戏。

## 11. 模块落点

| 模块 | 变更责任 |
|---|---|
| `services/scheduler` | 解析实际模型能力；为每次请求生成模型容量信息；确保本地与 Redis worker 一致。 |
| `core/agent_config.py` | 管理服务 ceiling、fallback、集中比例和模型能力覆盖；弃用字符上下文字段。 |
| `services/memory/context_builder.py` | 生成 ContextBudget、候选原子组和最终模型请求；统一 token 计量与降级。 |
| `agent_core/nodes/model_decision.py` | 删除按工具名/新旧字符裁剪，只提交 ContextBuilder 的最终消息。 |
| `agent_core/nodes/planner.py` | 使用结构化执行账本并按 `W_small` 装配。 |
| `agent_core/nodes/observation.py` | 使用 ToolResultEnvelope，按状态选择必要证据。 |
| `agent_core/nodes/compress.py` | 使用同一预算对象；压缩失败时继续选择后续候选，不因一条大消息停止。 |
| `tools` 与各业务 service | 返回结构化结果、完整引用和 continuation；移除静默前缀截断。 |
| `services/session` | 为完整工具结果和受管大结果提供权限、生命周期与继续读取能力。 |
| Debug/Obs | 展示 W 来源、各预算项、表示层级、省略原因、content ref 和最终真实请求。 |

避免在每个节点各写一套预算器。`ContextBuilder` 是现有统一上下文入口，应扩展它而不是创建多个平行装配框架。

## 12. 兼容与迁移

### 阶段 A：观测与影子预算

- 增加模型能力解析和 ContextBudget，但暂不改变实际请求；
- 对当前请求同时计算旧策略与新策略的 token、丢弃内容和潜在超限；
- Debug 展示差异，日志只记录计数和标识，不记录敏感正文；
- 建立不同模型窗口的回归基线。

### 阶段 B：结构化工具结果

- 为内置工具和 MCP 适配层生成 ToolResultEnvelope；
- 完整 ToolMessage 继续作为事实源；
- 增加 `read_tool_result` 和受管大结果生命周期；
- 前端保持消费现有人类可读内容，不因协议扩展中断。

### 阶段 C：统一主模型装配

- 用候选组装配替换 `_compact_tool_message`；
- 保证 tool call 配对、当前用户消息和强制 Skill；
- 当新策略失败时允许按请求级开关回退旧策略，并记录回退原因；
- 不同时运行两次真实模型请求。

### 阶段 D：Planner、Observation 与专项工具

- Planner/Observation 切换到结构化账本；
- 依次迁移 Terminal、文件、Web、Skill、附件/OCR、图谱和记忆；
- 每迁移一类即删除该类字符截断调用点并增加 AST/行为门禁。

### 阶段 E：配置清理

- 宣告旧字符字段弃用，读取旧值时只记录 warning，不再影响新策略；
- 完成一个兼容周期后删除字段、环境变量映射和旧测试；
- 更新设置说明、示例配置和 Debug 文案。

## 13. 可观测性

每次真实模型请求记录以下非敏感指标：

- `model_context_window_tokens`、`service_context_ceiling`、`effective_window_tokens` 和容量来源；
- 输出预留、安全边际、固定成本、弹性池和最终输入 token；
- 各来源候选组数量与 token 数；
- full/structured/head_tail/reference 的数量；
- 被降级或未选中的 source id、原因和可恢复性；
- 压缩前后 token、压缩耗时和是否回退；
- 模型上下文超限错误与重新装配次数；
- 同一工具因“内容不足”在单轮内被重复调用的次数。

Debug“上下文拼装”必须展示最终真实请求及预算账本。任何页面预览可折叠，但 Raw 数据不得再次做 UI 字符截断。

## 14. 失败模式与处理

| 失败模式 | 处理 |
|---|---|
| 未填写模型窗口 | 使用 100 万服务默认值，Debug 标出 `service_ceiling_default`；显式较小窗口仍优先。 |
| tokenizer 不认识模型 | 使用统一 fallback tokenizer并保留安全边际；记录 tokenizer 来源。 |
| 强制块超过输入预算 | 先缩减工具 schema和外置引用；仍超限则明确失败，不切用户问题或 Skill。 |
| 单个工具结果巨大 | 使用 structured/head-tail/reference，并提供 cursor。 |
| 工具没有结构化摘要 | 运行时生成状态和引用；必要时使用确定性 head-tail，不让 LLM摘要阻塞主流程。 |
| 摘要模型失败 | 保留原始事实，按候选组继续装配；不得清空上下文。 |
| 模型服务仍报超限 | 收紧会话级能力、重新装配一次；再次失败则报告容量错误，禁止无限重试。 |
| content ref 已过期 | 返回明确 `content_expired`，说明原工具和恢复方式；会话活跃期内不得提前回收。 |
| 工具调用配对被破坏 | 最终校验失败，阻止请求并重新装配原子组。 |
| 受管结果包含敏感信息 | 继承会话权限、禁止日志正文、按会话删除并进行路径边界校验。 |

## 15. 测试与验收

### 15.1 单元测试

- 对 32K、128K 和 1M 窗口验算 `W/O/S/B_input`；
- 分别验证主模型和小模型容量；
- 未填写模型窗口使用 1M 服务默认值，显式覆盖可收紧；
- 最终序列化 token 永不超过 `B_input`；
- 单个超大最近消息不会导致更早的小消息全部消失；
- tool call 与 tool result 原子组在所有表示层级保持合法；
- full 放不下时按 structured → head-tail → reference 降级；
- 所有非 full 表示都包含原始长度、content ref 和 continuation；
- 强制 Skill 不会被部分加载；
- tokenizer fallback 与安全边际生效。

### 15.2 工具专项测试

- Terminal 长 stdout + 末尾失败：Agent 必须看到 exit code、stderr 尾部和继续读取句柄；
- 文件关键结论在末尾：首次目录/相关章节或后续范围读取能够到达结论；
- 网页正文超过旧 3K：citation id 能继续读取中后部；
- Skill 超过旧 8K：完整加载或明确容量失败，不能半份成功；
- 多附件总文本超过旧 16K：上传不自动解析，Agent 能按引用选择目标附件并通过 cursor 读取后部；
- OCR 关键文本在后半部分：`read_file` 的完整缓存和范围读取能够到达目标内容；
- 图谱长章节：全部子块参与抽取且 evidence offset 可回原文；
- 记忆超过 200 条：精确删除仍能找到目标。

### 15.3 Agent 行为回归

- 工具返回成功但关键结论在尾部时，Agent 不重复调用同一工具；
- 复杂任务连续 12 次工具结果后，Planner 仍能说明已完成、未完成和最近失败；
- 压缩发生后，当前用户约束、未完成动作和最近工具结论仍保留；
- 请求取消、工具失败、摘要失败和模型超限都进入明确终态；
- 相同输入在旧策略与新策略下比较重复工具调用数、有效结论保留率和模型超限率。

### 15.4 静态门禁

在以下路径增加 AST 检查，禁止新增用于模型可见内容的数字切片或字符比较：

- `agent_service/agent_core/**`；
- `agent_service/services/memory/context_builder.py`；
- `agent_service/tools/**`；
- 发送给模型的各业务 service。

允许的资源安全限制必须引用 `AgentConfig`，并在字段文档中明确标注“资源安全”而非“上下文预算”。

### 15.5 通过标准

- 所有真实模型请求都携带并展示有效窗口与预算账本；
- 模型可见内容路径不再出现 900/240/200/6000 等字符前缀裁剪；
- 任一非完整工具结果都可通过 content ref 继续读取；
- 主模型、Planner、Observation 和摘要请求均不超过各自模型预算；
- 超长 Skill、附件、文件、网页、OCR 和图谱章节无静默丢尾；
- tool call 配对回归、串行后端测试和实际长工具链界面冒烟全部通过；
- 与旧策略相比，因未读到结果而重复调用同一工具的比例显著下降，且没有增加上下文超限错误。

## 16. 示例

### 16.1 百万窗口模型

假设模型真实支持 1,000,000 tokens，最大输出至少 65,000 tokens，服务 ceiling 也是 1,000,000：

```text
W = 1,000,000
O ≈ 65,000
S = 20,000
B_input ≈ 915,000
```

若系统提示、工具 schema、当前问题和强制 Skill 共 45,000 tokens，则弹性池约 870,000 tokens。此时把普通工具结果固定压成 900 字没有任何容量依据；当前 cycle 的结果通常应完整进入。

### 16.2 128K 模型

假设服务 ceiling 为 1,000,000，但模型只支持 131,072 tokens，且最大输出至少覆盖比例预留：

```text
W = 131,072
O ≈ 8,520（同时受模型最大输出约束）
S ≈ 2,622
B_input ≈ 119,930
```

所有后续预算自动收紧。系统不会因为全局写了 100 万而在约 80 万 token 才触发压缩。

### 16.3 超长 Terminal 结果

一个测试命令产生 80K tokens 输出，结尾为失败汇总：

- 完整结果进入受管结果存储并获得 `content_ref`；
- ToolResultEnvelope明确 `status=error`、exit code、失败测试名和 stderr 尾部；
- 当前预算充足时可附带较大的 head-tail；预算紧张时退化为 structured/reference；
- Agent 若需要具体中间日志，调用 `read_tool_result`，不会重跑测试。

## 17. 决策记录

### 已采纳

- 100 万 token 是服务 ceiling，实际预算取服务 ceiling 与模型能力的较小值；
- 模型上下文容量统一使用 token，不使用字符数；
- 使用一个共享弹性池和优先级装配，不建立互不借用的类别硬配额；
- 完整事实与模型表示分离；
- 超长内容用结构化表示、head-tail、引用和继续读取解决；
- Planner 与 Observation 使用结构化工具账本；
- 资源安全上限与模型上下文预算在配置和命名上明确分离。
- 未填写模型窗口时使用 100 万服务默认值，不再要求用户先填写才能获得服务容量。

### 已拒绝

- 仅把 900/240 放大十倍：仍然是与模型窗口无关的数字游戏；
- 所有工具结果无条件完整注入：会让小模型和复杂工具链不可控；
- 每个业务模块自行按 `W` 乘一个比例：会把散落常数变成散落比例，根因不变；
- 只依赖摘要模型：摘要可能失败或遗漏，必须保留完整事实和可继续读取引用；
- 未知模型固定回退 128K：与 100 万服务默认值脱节，并制造无意义的用户配置负担。

## 18. 实施完成后的最终状态

实施完成后，系统中仍然会存在数字配置，但数字只分三类：

1. 以实际模型窗口为基准的少量集中比例；
2. 与模型容量无关的资源安全和业务约束；
3. 模型能力表中的明确上下文与输出能力。

不再存在第四类——散落在业务代码里、无法解释为何是 900、240、200 或 6000 的模型可见字符截断。
