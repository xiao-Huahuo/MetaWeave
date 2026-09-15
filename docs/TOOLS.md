# Agent工具明细

## 工具系统设计
采用 **Function Calling** 模式，对接 **MCP 协议** 接入外部工具。系统自带默认工具,包括记忆召回,知识库检索,规则创建,文件操作,联网搜索等。
   * 注册与执行架构：工具注册器`ToolRegistry` 维护 `工具名 → 工具功能` 映射，支持 JSON Schema 参数校验并自动转换为工具体；工具执行器`ToolExecutor` 负责运行时调度，通过 `get_tool_runtime()` 注入当前用户/会话上下文，确保跨用户隔离与工具函数无状态复用。
   * 工具可开关: 用户可在设置中对Agent可使用的工具进行开关,或者直接在Agent观测页面的工具注册表进行工具开关.
   * 工具全量绑定: 每轮决策直接绑定当前已启用的全部工具(已剔除用户禁用工具),任意工具随时可直接调用,无需在正文中点名或等待下一轮放开,避免多轮长任务因工具缺失或等待绑定导致可用性下降.
   * 工具自发现: 常驻"查看可用工具"工具(`list_available_tools`),任何时候都可查询全部工具的中文名、确切工具名与一句话用途(含 MCP 工具),便于模型快速掌握当前可用工具的完整面貌.
   * 可观测性执行流程：每步工具调用逐一执行，产生 start 与 end 双向 trace（含工具名、参数摘要、结果摘要与条目数），通过异步回调实时推送前端观测面板, 工具调用结果则写回消息历史供后续观察节点 `observation`/`agent` 审视，形成完整的可追溯闭合回路。
    Agent可操作用户本地知识库文件.Agent既可以通过AgenticRAG获取用户指代的最相关文件,又可以通过通过文件管理系统API具体调查和操作任何所需的具体文档,实现了"中枢智能体"的理念.
![工具](assets/工具.png)
### 工具明细

下表列出当前默认注册的全部内置工具；MCP 等外部工具由运行时配置动态追加，不在此固定清单中。

| 工具名 | 简要说明 |
|---|---|
| `add_automation` | 创建定时或循环执行的自动化任务。 |
| `add_favorite` | 收藏知识库路径、图书馆条目或会话。 |
| `add_library_book` | 将知识文件、网页或外部文件加入图书馆。 |
| `add_library_collection` | 创建可嵌套的图书馆集锦。 |
| `add_todo` | 新增带可选截止日期的待办事项。 |
| `cancel_knowledge_job` | 取消正在执行的灌库或图谱任务。 |
| `complete_task_list_item` | 完成当前会话任务列表中的一项。 |
| `create_component` | 创建 Vue SFC 或独立 HTML 组件。 |
| `create_custom_skill` | 创建用户定制 Skill。 |
| `create_knowledge_folder` | 在知识库中创建文件夹。 |
| `create_smart_form` | 创建智能文献表或普通表。 |
| `create_task_list` | 为当前多步骤任务创建执行清单。 |
| `create_user_feedback` | 以当前用户身份新增反馈。 |
| `delete_component` | 经确认后删除用户组件。 |
| `delete_custom_skill` | 经确认后删除用户 Skill。 |
| `delete_file_graph` | 删除指定文件的图谱节点、关系和状态。 |
| `delete_knowledge_file` | 将知识库文件或文件夹移入最近删除。 |
| `delete_long_term_memory` | 删除匹配的长期记忆。 |
| `delete_long_term_rule` | 删除匹配的长期系统规则。 |
| `delete_todo` | 删除指定待办事项。 |
| `delete_user_feedback` | 删除当前用户的一条反馈。 |
| `download_file` | 下载并可选保存文件到知识库。 |
| `edit_todo` | 修改待办文本或截止日期。 |
| `export_smart_form` | 将表格导出为 CSV、Markdown 或 JSON。 |
| `extract_all_file_graphs` | 后台抽取当前知识库的全量语义图谱。 |
| `extract_selected_file_graphs` | 灌库并抽取多个选定文件的图谱。 |
| `fill_smart_form_cells` | 根据文献内容生成并保存智能单元格。 |
| `find_knowledge_graph_paths` | 查找两个图谱节点间的最短关系路径。 |
| `finish_task_list` | 完成并关闭当前会话任务列表。 |
| `get_component` | 读取组件源码和元数据。 |
| `get_current_time` | 获取指定 IANA 时区的当前时间。 |
| `get_current_viewing_document` | 获取编辑器当前查看的文档信息。 |
| `get_custom_skill` | 读取用户 Skill 的完整内容。 |
| `get_knowledge_context` | 按语义召回可用于回答的知识片段。 |
| `get_knowledge_file_status` | 查询文件投影、索引和图谱状态。 |
| `get_knowledge_file_url` | 获取知识库文件的浏览器访问地址。 |
| `get_knowledge_job_status` | 查询灌库或图谱后台任务状态。 |
| `get_library_item` | 读取单个图书或集锦的完整信息。 |
| `get_long_term_memory` | 检索当前用户的相关长期记忆。 |
| `get_selected_knowledge_files` | 获取文件管理器当前选中的知识文件。 |
| `get_smart_form` | 读取表格的完整列、行和单元格。 |
| `get_smart_form_literature` | 读取表项关联的文献与抽取内容。 |
| `get_smart_form_schema` | 读取表格列定义和基本信息。 |
| `get_task_list_status` | 查询当前会话任务列表状态。 |
| `get_user_feedback` | 读取当前用户的一条反馈。 |
| `git_add_remote` | 为知识库 Git 仓库添加远程。 |
| `git_commit_files` | 暂存选定文件并创建本地提交。 |
| `git_create_branch` | 创建并可选切换 Git 分支。 |
| `git_diff` | 查看工作区或暂存区差异。 |
| `git_history` | 查看提交历史和未推送变更。 |
| `git_init_repository` | 在知识库根目录初始化 Git 仓库。 |
| `git_pull_branch` | 获取并快进合并远程分支。 |
| `git_push_branch` | 经确认后推送本地分支。 |
| `git_restore_files` | 将选定文件恢复到 HEAD 状态。 |
| `git_status` | 查看仓库、分支和文件变更状态。 |
| `git_switch_branch` | 切换本地分支并更新索引状态。 |
| `import_smart_form` | 从 JSON 或 CSV 内容导入表格。 |
| `ingest_all_knowledge_files` | 后台灌入当前知识库全部支持文件。 |
| `ingest_selected_knowledge_files` | 后台灌入多个指定源文件。 |
| `list_available_tools` | 列出当前运行时可用的全部工具。 |
| `list_components` | 按组件类型筛选并列出组件。 |
| `list_favorites` | 按类型和知识库范围列出收藏。 |
| `list_knowledge_files` | 列出当前知识库的完整文件树。 |
| `list_knowledge_trash` | 列出知识库最近删除条目。 |
| `list_library_items` | 查询并筛选图书馆图书和集锦。 |
| `list_library_tags` | 列出当前图书馆标签。 |
| `list_skills` | 列出可见 Skill 及其启用状态。 |
| `list_smart_forms` | 按标题关键词列出智能表格。 |
| `list_todos` | 列出当前用户的待办事项。 |
| `list_user_feedback` | 列出当前用户提交的反馈。 |
| `patch_knowledge_file` | 按唯一原文片段局部修改文本文件。 |
| `patch_smart_form_rows` | 增量增删改表格行和单元格。 |
| `permanently_delete_knowledge_trash` | 经确认后永久删除最近删除条目。 |
| `preview_smart_form_fill` | 预览智能填充目标而不写入数据。 |
| `read_knowledge_file` | 读取文件的 Markdown 投影并按需自动灌库。 |
| `remove_favorite` | 取消知识库、图书馆或会话收藏。 |
| `remove_library_item` | 将条目移出图书馆而不删除源文件。 |
| `rename_knowledge_file` | 重命名或移动知识库文件。 |
| `restore_knowledge_file` | 从最近删除恢复文件或文件夹。 |
| `retry_failed_graph_extraction` | 重试图谱任务中的失败文件。 |
| `retry_failed_knowledge_files` | 重试灌库任务中的失败文件。 |
| `run_terminal_command` | 在权限约束下执行结构化终端指令。 |
| `save_uploaded_attachment_to_knowledge` | 将会话附件保存并可选灌入知识库。 |
| `understand_image` | 使用 CPU 本地 Qwen 结合先行 OCR 文本重新理解当前会话中的指定图片。 |
| `search_knowledge` | 复用统一搜索框的四库服务；最终回答引用 `[K#]` 时挂载对应原生结果块。 |
| `search_knowledge_graph_nodes` | 搜索图谱节点并返回邻接节点和边。 |
| `set_skill_enabled` | 启用或停用内置或用户 Skill。 |
| `show_markdown_html` | 在编辑器中展示 Markdown 的 HTML 可视化。 |
| `spawn_child_agent` | 创建前台或后台子 Agent 执行子任务。 |
| `test_custom_skill` | 测试用户 Skill 对提示词的匹配。 |
| `toggle_todo` | 切换待办事项的完成状态。 |
| `update_component` | 修改组件源码、类型或标题。 |
| `update_custom_skill` | 修改用户 Skill 名称、说明或正文。 |
| `update_library_item` | 修改图书馆条目的虚拟元数据。 |
| `update_smart_form` | 使用完整结构覆盖更新表格。 |
| `update_user_feedback` | 修改当前用户的反馈正文。 |
| `use_skill` | 将指定 Skill 的说明载入当前轮次。 |
| `validate_component` | 校验组件源码及 Vue 或 HTML 结构。 |
| `validate_custom_skill` | 校验 Skill frontmatter 和正文。 |
| `wait_for_child_agents` | 等待并收取后台子 Agent 结果。 |
| `web_image_search` | 通过 DuckDuckGo 搜索图片。 |
| `web_search` | 通过 DuckDuckGo 搜索网页信息。 |
| `write_knowledge_file` | 新建或完整覆写知识库文本文件。 |
| `write_long_term_memory` | 写入可跨会话召回的长期记忆。 |
| `write_long_term_rule` | 写入每轮生效的长期系统规则。 |
