"""
内置工具分组定义模块。

功能说明:
本文件只登记内置工具的名称、描述、参数 schema 与函数引用。实际工具函数仍在
`builtin.py` 中实现,工具注册表仍可通过 `agent_service.tools.builtin` 兼容导入。

使用说明:
新增工具时,先在 `builtin.py` 中实现函数,再在本文件对应分组中登记
`BuiltinToolDefinition`。
"""

from __future__ import annotations

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS

from agent_service.tools.builtin import (
    BuiltinToolDefinition,
    add_automation,
    add_library_book,
    add_library_collection,
    add_todo,
    complete_task_list_item,
    continue_child_agent,
    create_task_list,
    create_knowledge_folder,
    delete_knowledge_file,
    delete_long_term_memory,
    delete_long_term_rule,
    delete_todo,
    download_file,
    edit_todo,
    finish_task_list,
    git_commit_files,
    git_add_remote,
    git_create_branch,
    git_diff,
    git_history,
    git_init_repository,
    git_pull_branch,
    git_push_branch,
    git_restore_files,
    git_status,
    git_switch_branch,
    get_task_list_status,
    get_current_viewing_document,
    get_knowledge_context,
    get_knowledge_file_url,
    get_long_term_memory,
    list_available_tools,
    read_tool_result,
    list_library_items,
    list_library_tags,
    list_skills,
    list_knowledge_files,
    list_todos,
    read_file,
    patch_knowledge_file,
    remove_library_item,
    rename_knowledge_file,
    run_terminal_command,
    spawn_child_agent,
    save_uploaded_attachment_to_knowledge,
    understand_image,
    search_knowledge,
    show_markdown_html,
    toggle_todo,
    update_library_item,
    use_skill,
    web_search,
    web_image_search,
    wait_for_child_agents,
    write_knowledge_file,
    write_long_term_memory,
    write_long_term_rule,
)

UTILITY_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = [
    BuiltinToolDefinition(
        name="list_available_tools",
        description=(
            "列出当前用户实际启用的全部工具(中文名、工具名、一句话用途),每行一个。"
            "已被长期记忆总开关或工具设置关闭的工具不会出现在结果中。"
        ),
        args_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        function=list_available_tools,
        display_name="查看可用工具",
    ),
    BuiltinToolDefinition(
        name="read_tool_result",
        description=(
            "按 tool-result:// 引用继续读取当前会话中已经执行过的完整工具结果。"
            "支持 start_line/end_line 或 cursor；不要为查看被省略内容而重新执行原工具。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "content_ref": {"type": "string", "description": "工具结果返回的 tool-result:// 引用。"},
                "start_line": {"type": "integer", "description": "可选起始行，0-based。"},
                "end_line": {"type": "integer", "description": "可选结束行，不包含该行。"},
                "cursor": {"type": "integer", "description": "可选 continuation cursor。"},
            },
            "required": ["content_ref"],
        },
        function=read_tool_result,
        display_name="继续读取工具结果",
    ),
    BuiltinToolDefinition(
        name="run_terminal_command",
        description=(
            "在项目终端沙盒中执行一个或多个结构化指令段。必须传 shell、segments、cwd; "
            "禁止传整条 shell 字符串。\n\n"
            "内部读取指令(internal_command 类型): pwd(当前目录), ls/dir(列出目录,"
            "支持 -a/R/l 和 /s/b 等标志,支持 *.docx 通配符), cat/type(读文件), "
            "head/tail -n N 文件(行窗口), stat(文件状态), wc(统计行/词/字符数,可用 -c/-l/-w 筛选"
            "但始终显示三项;未指定文件则返回总计数)。\n"
            "内部写入指令: write(覆写), append(追加), touch(创建/时间戳), "
            "mkdir(始终 -p 模式), rm/del(目录递归删除), mv/move(移动/重命名)。\n\n"
            "外部程序段(external_program 类型): 在沙盒/只读模式下需在白名单内,"
            "白名单程序包括 python/pytest/pip/git/npm/node/eslint/vitest/go/cargo/find/wc 等;"
            "find 用于搜索文件(如 find . -name '*.docx' -type f), "
            "wc 用于带标志统计(如 wc -l file.txt)。"
            "完全访问模式下所有外部程序都允许(嵌套 shell 仍禁止)。\n\n"
            "权限模式影响:\n"
            "- readonly: 仅内部读取指令(pwd/ls/cat/head/tail/stat/wc),禁止写入和外部程序。\n"
            "- sandbox(默认): 内部读取可穿透工作区根目录;写入和外部程序限制在工作区内。\n"
            "- full_access: 所有内部指令和外部程序放开限制,额外支持 kill/taskkill 杀进程,"
            "rm -rf/mkdir -p/批量 cat/mv 等都允许。\n\n"
            "注意事项:\n"
            "- 读取或解析知识库文件、会话附件正文时, 不要使用本工具; 统一用 read_file。\n"
            "- 文件搜索优先用 ls/dir *.docx /s /b 或 find . -name '*.docx'。\n"
            "- 需要标志的 wc(如 wc -l)用 external_program 类型;仅统计用 internal_command。\n"
            "- 所有 internal_command 都无需 shell 程序支持,在任何环境下可用。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "shell": {"type": "string", "description": "终端策略名: cmd、powershell 或 bash。"},
                "segments": {
                    "type": "array",
                    "description": (
                        "指令段数组。外部程序段格式为 {type:'external_program', program:'python', args:['-m','pytest']};"
                        "内部系统指令段格式为 {type:'internal_command', command:'ls', args:['.']}。"
                    ),
                },
                "cwd": {"type": "string", "description": "相对沙盒工作区的工作目录,默认当前工作区根目录。"},
                "timeout_seconds": {"type": "integer", "description": "可选单段超时时间,受沙盒最大值限制。"},
            },
            "required": ["shell", "segments"],
        },
        function=run_terminal_command,
        display_name="终端命令",
    ),
    BuiltinToolDefinition(
        name="download_file",
        description="下载文件到本地存储。注意: 展示图片时请直接使用 Markdown 热链接嵌入原始图片 URL,不要使用本工具。仅在用户明确要求保存或下载文件时才调用本工具。如果 save_to_knowledge=True,还会将文件拷贝到知识库并灌库。下载后的文件可通过 /downloads/ 路径在 Markdown 中引用。",
        args_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "待下载文件的完整 URL。"},
                "save_to_knowledge": {"type": "boolean", "description": "是否同时保存到当前 active 知识库并灌库。默认 false。"},
                "knowledge_path": {"type": "string", "description": "可选。保存到知识库时的相对路径。"},
            },
            "required": ["url"],
        },
        function=download_file,
        display_name="下载文件",
    ),
]

GIT_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = [
    BuiltinToolDefinition(
        name="git_status",
        description="读取当前知识库仓库状态、分支、远程、更改和未跟踪文件。",
        args_schema={"type": "object", "properties": {}, "required": []},
        function=git_status,
        display_name="Git 状态",
    ),
    BuiltinToolDefinition(
        name="git_diff",
        description="读取当前知识库工作区或暂存区的 Git diff。",
        args_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "可选知识库相对路径。"},
                "staged": {"type": "boolean", "description": "是否读取暂存区差异。"},
            },
            "required": [],
        },
        function=git_diff,
        display_name="Git 差异",
    ),
    BuiltinToolDefinition(
        name="git_history",
        description="读取提交历史、未推送提交和未推送文件。",
        args_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "最大提交数,默认 30。"}},
            "required": [],
        },
        function=git_history,
        display_name="Git 历史",
    ),
    BuiltinToolDefinition(
        name="git_init_repository",
        description="在当前知识库根目录初始化 Git 仓库。",
        args_schema={
            "type": "object",
            "properties": {"initial_branch": {"type": "string", "description": "初始分支名,默认 main。"}},
            "required": [],
        },
        function=git_init_repository,
        display_name="初始化 Git",
    ),
    BuiltinToolDefinition(
        name="git_restore_files",
        description=(
            "回滚选中文件。已跟踪文件恢复到 HEAD 并清理旧知识索引;"
            "未跟踪文件移入 MetaWeave 最近删除,不会永久清除。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "知识库相对路径列表。",
                }
            },
            "required": ["paths"],
        },
        function=git_restore_files,
        display_name="Git 回滚",
    ),
    BuiltinToolDefinition(
        name="git_commit_files",
        description="暂存选中的知识库文件并创建本地提交。",
        args_schema={
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}},
                "message": {"type": "string", "description": "提交概要。"},
            },
            "required": ["paths", "message"],
        },
        function=git_commit_files,
        display_name="Git 提交",
    ),
    BuiltinToolDefinition(
        name="git_push_branch",
        description=(
            "推送本地分支到远程。必须先获得用户明确确认并传 confirm=true;"
            "force-with-lease 还需要独立的 confirm_force=true。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "local_branch": {"type": "string"},
                "remote": {"type": "string"},
                "remote_branch": {"type": "string"},
                "confirm": {"type": "boolean"},
                "force_with_lease": {"type": "boolean"},
                "confirm_force": {"type": "boolean"},
                "all_branches": {
                    "type": "boolean",
                    "description": "为 true 时推送所有本地分支。",
                },
            },
            "required": ["local_branch", "remote", "remote_branch", "confirm"],
        },
        function=git_push_branch,
        display_name="Git 推送",
    ),
    BuiltinToolDefinition(
        name="git_create_branch",
        description="创建本地 Git 分支,可选择立即切换。",
        args_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "checkout": {"type": "boolean"},
            },
            "required": ["name"],
        },
        function=git_create_branch,
        display_name="创建 Git 分支",
    ),
    BuiltinToolDefinition(
        name="git_add_remote",
        description="为当前知识库 Git 仓库新增命名远程。",
        args_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "远程名称,例如 origin。"},
                "url": {"type": "string", "description": "HTTPS、SSH 或本地 Git 仓库地址。"},
            },
            "required": ["name", "url"],
        },
        function=git_add_remote,
        display_name="新增 Git 远程",
    ),
    BuiltinToolDefinition(
        name="git_switch_branch",
        description="切换本地 Git 分支并使实际变化文件的知识索引失效。",
        args_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        function=git_switch_branch,
        display_name="切换 Git 分支",
    ),
    BuiltinToolDefinition(
        name="git_pull_branch",
        description="获取并快进合并远程分支,不会自动创建合并提交。",
        args_schema={
            "type": "object",
            "properties": {
                "remote": {"type": "string"},
                "branch": {"type": "string"},
            },
            "required": ["remote", "branch"],
        },
        function=git_pull_branch,
        display_name="Git 拉取",
    ),
]

SKILL_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = [
    BuiltinToolDefinition(
        name="list_skills",
        description="List all skills visible to the current user, including built-in and user-level skills, their sources, descriptions, and enabled states.",
        args_schema={"type": "object", "properties": {}, "required": []},
        function=list_skills,
        display_name="列出技能",
    ),
]

SKILL_TOOL_DEFINITIONS.append(
    BuiltinToolDefinition(
        name="use_skill",
        description="Load one enabled Skill's SKILL.md body into the current turn when the Agent needs detailed instructions for a specific skill. Use skill_ref from list_skills, such as skill_id, name, or folder name.",
        args_schema={
            "type": "object",
            "properties": {
                "skill_ref": {
                    "type": "string",
                    "description": "Skill id, Skill name, or skill folder name returned by list_skills.",
                }
            },
            "required": ["skill_ref"],
        },
        function=use_skill,
        display_name="使用技能",
    )
)

MEMORY_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = [
    BuiltinToolDefinition(
        name="get_long_term_memory",
        description="检索当前用户在长期记忆中的相关摘要信息,用于跨轮对话回忆项目目标、约束、偏好和历史事实。",
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "需要检索的记忆查询文本。"},
                "top_k": {"type": "integer", "description": "最多返回多少条结果,默认 3。"},
            },
            "required": ["query"],
        },
        function=get_long_term_memory,
        display_name="检索记忆",
    ),
    BuiltinToolDefinition(
        name="write_long_term_memory",
        description="向当前用户的长期记忆中写入一条记录,包含向量化后可被后续对话检索召回。可用于手动存储重要信息、项目代号、用户偏好等需要跨会话持久化的内容。",
        args_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "需要记忆的内容,建议简洁完整,以便后续检索。"},
                "memory_type": {"type": "string", "description": "记忆子类型,默认 important_fact_summary。一般无需修改。"},
                "importance": {"type": "number", "description": "重要性(0~1),默认 0.5。"},
                "authority": {"type": "number", "description": "权威性(0~1),默认 0.5。"},
            },
            "required": ["content"],
        },
        function=write_long_term_memory,
        display_name="写入记忆",
    ),
    BuiltinToolDefinition(
        name="write_long_term_rule",
        description="向当前用户的长期系统规则中追加一条必须遵守的指令,效果等同于用户在设置页手动添加系统提示词。该规则每轮都会注入系统提示词,不依赖 RAG 召回。",
        args_schema={
            "type": "object",
            "properties": {"content": {"type": "string", "description": "需要长期遵守的规则内容。"}},
            "required": ["content"],
        },
        function=write_long_term_rule,
        display_name="写入长期规则",
    ),
    BuiltinToolDefinition(
        name="delete_long_term_memory",
        description="删除当前用户的一条长期记忆。按内容文本匹配后删除,会先尝试精确匹配,再尝试包含匹配。用于清理或修正错误写入的记忆。",
        args_schema={
            "type": "object",
            "properties": {"content": {"type": "string", "description": "需要删除的记忆内容关键词或完整句子。"}},
            "required": ["content"],
        },
        function=delete_long_term_memory,
        display_name="删除记忆",
    ),
    BuiltinToolDefinition(
        name="delete_long_term_rule",
        description="删除当前用户的一条长期系统规则。按内容文本匹配后删除,会先尝试精确匹配,再尝试包含匹配。用于清理或修正不再需要的长期规则。",
        args_schema={
            "type": "object",
            "properties": {"content": {"type": "string", "description": "需要删除的规则内容关键词或完整句子。"}},
            "required": ["content"],
        },
        function=delete_long_term_rule,
        display_name="删除长期规则",
    ),
]

MEMORY_TOOL_NAMES = frozenset(definition.name for definition in MEMORY_TOOL_DEFINITIONS)

KNOWLEDGE_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = [
    BuiltinToolDefinition(
        name="get_knowledge_context",
        description=(
            "按语义召回当前用户知识库中的正文片段,返回可直接用于回答的内容摘录和来源。"
            "适合用户已经在问某个事实、概念或文档内容,需要查正文来回答时使用。"
            "它不是文件名搜索;如果目标是找文件、按文件名关键词定位路径,请使用 search_knowledge 或 list_knowledge_files。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用于语义召回正文片段的问题、主题或事实查询。"},
                "top_k": {"type": "integer", "description": "最多返回多少条结果,默认 3。"},
            },
            "required": ["query"],
        },
        function=get_knowledge_context,
        display_name="检索知识",
    ),
    BuiltinToolDefinition(
        name="search_knowledge",
        description=(
            "四库联合搜索: 与前端统一搜索框相同,可搜索文件库、图书馆、组件库和文献库,并支持全文与语义搜索。"
            "适合用户要跨库定位文件、图书、组件或文献,也可用 sources 严格限定搜索范围。"
            "最终回答引用结果的 [K#] 编号时,前端会把该结果挂载为可点击的原生库块。"
            "如果只需要完整列出目录树和所有文件路径,请使用 list_knowledge_files;如果已经要回答正文内容,请使用 get_knowledge_context。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "文件名、路径关键词、正文关键词或语义描述文本。"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["files", "library", "components", "literature"]},
                    "description": "搜索来源；默认同时搜索文件库、图书馆、组件库和文献库。",
                },
                "fulltext": {"type": "boolean", "description": "是否启用全文内容搜索,默认 true。"},
                "semantic": {"type": "boolean", "description": "是否启用语义搜索,默认 false。"},
            },
            "required": ["query"],
        },
        function=search_knowledge,
        display_name="四库联合搜索",
    ),
    BuiltinToolDefinition(
        name="save_uploaded_attachment_to_knowledge",
        description="把当前会话中用户上传的附件复制到当前 active 知识库,并可立即灌库。仅当用户明确要求长期保存上传附件时使用。",
        args_schema={
            "type": "object",
            "properties": {
                "attachment": {"type": "string", "description": "可选。attachment_id、完整文件名或文件名关键词。"},
                "target_path": {"type": "string", "description": "可选。保存到知识库内的相对路径。"},
                "conflict_strategy": {"type": "string", "description": "同名冲突策略: rename、overwrite 或 skip。默认 rename。"},
                "ingest": {"type": "boolean", "description": "是否保存后立即灌库。默认 true。"},
            },
            "required": [],
        },
        function=save_uploaded_attachment_to_knowledge,
        display_name="附件存入知识库",
    ),
    BuiltinToolDefinition(
        name="understand_image",
        description=(
            "使用用户在 LLM 设置中配置的远程视觉模型理解当前会话中直接上传的图片。"
            "系统会同时提供先行 OCR 文本，适合分析对象、布局、空间关系、图表趋势和图片语义；"
            "需要重新观察图片或回答特定视觉问题时调用。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "attachment": {"type": "string", "description": "可选。attachment_id、完整文件名或文件名关键词。"},
                "prompt": {"type": "string", "description": "可选。希望视觉模型针对图片回答的问题。"},
            },
            "required": [],
        },
        function=understand_image,
        display_name="识图",
    ),
    BuiltinToolDefinition(
        name="get_knowledge_file_url",
        description="获取知识库中本地文件的浏览器可访问 URL。返回的 URL 可用于 Markdown 图片或链接,在回复中直接引用知识库文件。",
        args_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件相对于知识库根目录的路径。例如 images/diagram.png。"},
            },
            "required": ["path"],
        },
        function=get_knowledge_file_url,
        display_name="获取文件URL",
    ),
]

FILE_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = [
    BuiltinToolDefinition(
        name="get_current_viewing_document",
        description="获取当前用户在 editor 前端正在观看的文档基本信息;如需正文请继续调用 read_file。",
        args_schema={"type": "object", "properties": {}, "required": []},
        function=get_current_viewing_document,
        display_name="获取当前文档",
    ),
    BuiltinToolDefinition(
        name="list_knowledge_files",
        description=(
            "列出当前用户知识库的完整文件树,返回所有文件和文件夹的路径、类型和修改时间。"
            "适合需要浏览目录结构、获得可传给 read_file 的准确路径、或全面盘点文件数量时使用。"
            "它不会按关键词过滤;如果用户要按文件名、路径或正文关键词搜索,请使用 search_knowledge。"
        ),
        args_schema={"type": "object", "properties": {}, "required": []},
        function=list_knowledge_files,
        display_name="列出文件",
    ),
    BuiltinToolDefinition(
        name="read_file",
        description=(
            "统一读取知识库文件或当前会话附件。传入知识库相对路径时读取 Markdown 投影；"
            "传入 attachment:// 引用时首次按需解析原文件并缓存，后续直接读取缓存。"
            "图片文字可由本工具按需 OCR；理解对象、布局、图表和空间关系请使用 understand_image。"
            "不要传 `.mw/md` 内部路径，也不要调用 run_terminal_command、get_knowledge_file_url、download_file 或 Python 库自行解析源文件。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "知识库相对路径，或附件目录中的 attachment:// 引用。"},
                "start_line": {"type": "integer", "description": "附件正文可选起始行，0-based。"},
                "end_line": {"type": "integer", "description": "附件正文可选结束行，不包含该行。"},
                "cursor": {"type": "integer", "description": "附件正文可选 continuation cursor。"},
            },
            "required": ["path"],
        },
        function=read_file,
        display_name="阅读文件",
    ),
    BuiltinToolDefinition(
        name="patch_knowledge_file",
        description="局部修改已有文本/Markdown/代码文件。old_text 必须是文件内唯一的原文片段；优先使用本工具，只有新建文件或明确整文件重写时才使用 write_knowledge_file。",
        args_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件相对路径。"},
                "old_text": {"type": "string", "description": "唯一命中的原文片段。"},
                "new_text": {"type": "string", "description": "替换后的片段。"},
            },
            "required": ["path", "old_text", "new_text"],
        },
        function=patch_knowledge_file,
        display_name="局部修改文件",
    ),
    BuiltinToolDefinition(
        name="write_knowledge_file",
        description="创建新文本文件，或在用户明确要求整文件重写时覆盖已有文件。修改已有文件请优先使用 patch_knowledge_file。",
        args_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件相对于知识库根目录的路径。"},
                "content": {"type": "string", "description": "要写入的完整文件内容。"},
            },
            "required": ["path", "content"],
        },
        function=write_knowledge_file,
        display_name="创作文件",
    ),
    BuiltinToolDefinition(
        name="show_markdown_html",
        description=(
            "Display a generated Markdown/document HTML visualization in the editor front-end. "
            "Use this only after you have produced the final complete HTML for the current document visualization. "
            "The tool saves the HTML under runtime/visualizations, returns the local path and URL, "
            "and automatically triggers the front-end iframe mount. For any knowledge document, first read its "
            "canonical Markdown projection with read_file and build the HTML from that content."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Visualization title shown in the front-end panel."},
                "html": {"type": "string", "description": "Complete standalone HTML document or valid HTML fragment."},
                "source_path": {"type": "string", "description": "Optional source document path in the knowledge library."},
                "filename": {"type": "string", "description": "Optional preferred HTML filename; it will be sanitized and timestamped."},
            },
            "required": ["title", "html"],
        },
        function=show_markdown_html,
        display_name="展示Markdown-HTML",
    ),
    BuiltinToolDefinition(
        name="delete_knowledge_file",
        description="删除知识库中的文件或文件夹。删除文件夹会递归删除其下所有内容,请谨慎使用。",
        args_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "文件或文件夹相对于知识库根目录的路径。"}},
            "required": ["path"],
        },
        function=delete_knowledge_file,
        display_name="删除文件",
    ),
    BuiltinToolDefinition(
        name="rename_knowledge_file",
        description="重命名或移动知识库中的文件/文件夹。可以只改文件名,也可以移动到其他目录。",
        args_schema={
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "文件/文件夹的当前相对路径。"},
                "target_path": {"type": "string", "description": "新的相对路径。"},
            },
            "required": ["source_path", "target_path"],
        },
        function=rename_knowledge_file,
        display_name="重命名文件",
    ),
    BuiltinToolDefinition(
        name="create_knowledge_folder",
        description="在知识库中创建新文件夹(目录)。用于组织文件结构。",
        args_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "文件夹相对于知识库根目录的路径。"}},
            "required": ["path"],
        },
        function=create_knowledge_folder,
        display_name="创建文件夹",
    ),
]

LIBRARY_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = [
    BuiltinToolDefinition(
        name="list_library_items",
        description=(
            "列出当前用户知识库的图书馆条目(图书与集锦),返回条目标题、item_id、路径、状态与标签。"
            "parent_id 传集锦 item_id 可进入对应集锦,传空表示图书馆根层。"
            "返回的 item_id 供 add_library_book/add_library_collection 的 parent_id、update_library_item、remove_library_item 使用。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "parent_id": {"type": "string", "description": "集锦 item_id;为空表示图书馆根层。"},
                "query": {"type": "string", "description": "按标题、描述或真实文件名关键词过滤。"},
                "tag": {"type": "string", "description": "按标签名过滤。"},
                "content_type": {"type": "string", "description": "knowledge_file/web_url/external_file/collection 过滤。"},
                "sort": {"type": "string", "description": "title/source_mtime/updated_at/created_at/sort_order。"},
                "direction": {"type": "string", "description": "asc 或 desc。"},
            },
            "required": [],
        },
        function=list_library_items,
        display_name="列出图书馆",
    ),
    BuiltinToolDefinition(
        name="list_library_tags",
        description="列出当前用户知识库的图书馆标签,供新增条目时复用已有标签。",
        args_schema={"type": "object", "properties": {}, "required": []},
        function=list_library_tags,
        display_name="列出图书馆标签",
    ),
    BuiltinToolDefinition(
        name="add_library_book",
        description=(
            "将一份资料加入图书馆成为图书卡片。content_type 为 knowledge_file 时用 source_path 指定知识库相对路径,"
            "web_url 时用 source_url 指定网页地址,external_file 时用 source_path 指定外部本地文件路径。"
            "parent_id 传入集锦 item_id 可放入对应集锦;用户要求整理、收藏、归档资料到图书馆时使用。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "content_type": {"type": "string", "description": "knowledge_file/web_url/external_file,默认 knowledge_file。"},
                "source_path": {"type": "string", "description": "knowledge_file/external_file 时的源文件路径(知识库相对路径或外部绝对路径)。"},
                "source_url": {"type": "string", "description": "web_url 时的网页地址。"},
                "parent_id": {"type": "string", "description": "目标集锦 item_id;为空放入图书馆根层。"},
                "title": {"type": "string", "description": "图书标题;为空自动用源文件名。"},
                "description": {"type": "string", "description": "图书描述。"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签名列表。"},
            },
            "required": [],
        },
        function=add_library_book,
        display_name="新增图书",
    ),
    BuiltinToolDefinition(
        name="add_library_collection",
        description=(
            "在图书馆中新增一个集锦(资料分组),可嵌套到其他集锦。"
            "用户要求整理、归类、建分组、收藏主题资料时使用。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "集锦名称,会自动转换成可用文件夹名。"},
                "description": {"type": "string", "description": "集锦描述。"},
                "parent_id": {"type": "string", "description": "父集锦 item_id;为空放在图书馆根层。"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签名列表。"},
            },
            "required": ["title"],
        },
        function=add_library_collection,
        display_name="新增集锦",
    ),
    BuiltinToolDefinition(
        name="update_library_item",
        description=(
            "更新图书馆条目的虚拟元数据:改名(title)、移动集锦(parent_id,传空字符串移回根层)、改描述(description)、换标签(tags)。"
            "不传的字段保持不变。item_id 由 list_library_items 返回。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "目标条目 ID,由 list_library_items 返回。"},
                "title": {"type": "string", "description": "新标题;不传保留原标题。"},
                "parent_id": {"type": "string", "description": "新所在集锦 ID;传空字符串移回根层;不传不移动。"},
                "description": {"type": "string", "description": "新描述。"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "新的标签列表;传空数组清空标签;不传不修改。"},
            },
            "required": ["item_id"],
        },
        function=update_library_item,
        display_name="更新图书馆条目",
    ),
    BuiltinToolDefinition(
        name="remove_library_item",
        description=(
            "将条目移出图书馆,不删除真实文件。删除集锦时连带移除其嵌套子项。"
            "item_id 由 list_library_items 返回。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "目标条目 ID;集锦会连带移除嵌套子项。"},
            },
            "required": ["item_id"],
        },
        function=remove_library_item,
        display_name="移出图书馆",
    ),
]

TASK_LIST_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = [
    BuiltinToolDefinition(
        name="get_task_list_status",
        description=(
            "Read the current session task list without changing it. "
            "Use this when you need to confirm task list status, item ids, current item, "
            "or completion summaries before continuing long-running work."
        ),
        args_schema={"type": "object", "properties": {}, "required": []},
        function=get_task_list_status,
        display_name="获取任务列表状态",
    ),
    BuiltinToolDefinition(
        name="create_task_list",
        description=(
            "【强制规则】在开始执行任何需要多步骤、分阶段或可验收交付的任务之前,必须先调用本工具创建任务列表。"
            "适用场景包括:代码修改、调试、文件操作、文档处理、数据分析、工具链操作、多文件检查、"
            "分阶段调研/调查、资料整理、方案实现等所有需要先后完成多个具体步骤的请求。"
            "【例外】只有直接问答、单步说明、无需执行推进的概念解释或用户明确要求管理长期 Todo 时,才不创建。"
            "Task List 仅用于当前 Agent 会话内的执行进度跟踪,与用户长期 Todo 完全无关,二者不得混用。"
            "创建后,必须持续推进该列表,直到调用 finish_task_list 为止。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the task list."},
                "items": {
                    "type": "array",
                    "description": "Concrete task items to complete. Each item should be a short actionable string.",
                },
            },
            "required": ["items"],
        },
        function=create_task_list,
        display_name="创建任务列表",
    ),
    BuiltinToolDefinition(
        name="complete_task_list_item",
        description=(
            "每实际完成一个任务列表项,必须立即调用本工具将其标记完成,"
            "并填写具体的事实性完成摘要(做了什么、得到什么结论),再开始下一项。"
            "Mark one task list item complete. You must call this after actually completing an item, "
            "and include a concrete completion summary before starting another item."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "The task list item id."},
                "completion_summary": {
                    "type": "string",
                    "description": "A concise factual summary of what was completed for this item.",
                },
                "next_item_id": {
                    "type": "string",
                    "description": "Optional id of the next item to mark in progress.",
                },
            },
            "required": ["item_id", "completion_summary"],
        },
        function=complete_task_list_item,
        display_name="完成任务项",
    ),
    BuiltinToolDefinition(
        name="finish_task_list",
        description=(
            "所有有用任务项都完成后,必须调用本工具结束当前任务列表并做总体收尾。"
            "End the active session task list after the long-running task is complete. "
            "Do not call this until no useful task list work remains."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "final_summary": {"type": "string", "description": "Optional overall summary for the finished list."},
            },
            "required": [],
        },
        function=finish_task_list,
        display_name="完成任务列表",
    ),
]


CHILD_AGENT_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = [
    BuiltinToolDefinition(
        name="spawn_child_agent",
        display_name="召唤子 Agent",
        description=(
            "【何时必须使用】当用户请求需要彻底调研或全面盘点一个范围(如调研整个知识库含有什么内容、"
            "理解项目全部文件/代码结构)、或需要并行分析多个相互独立的方向(如分别比较多个方案)时,"
            "必须先调用本工具创建只读 explore 子 Agent 分头探索,再用 wait_for_child_agents 收取结果。"
            "不确定是否需要并行探索时,优先派 explore 子 Agent 探索,它只读不写、成本更低。"
            "创建一个不能继续召唤其他子 Agent 的子 Agent。必须提供明确目标。"
            "mode=foreground 会阻塞直到子 Agent 完成并返回结果;"
            "mode=background 只启动后台子 Agent 并立即返回 run_id,不会等待最终结果。"
            "一旦使用 background 创建了本轮所需的全部子 Agent,必须反复调用 wait_for_child_agents "
            "逐个收取结果;只要还有 created/running 子 Agent,就继续等待,不要输出最终结论。"
            "子 Agent 默认继承主 Agent 工具,但主 Agent 可缩小工具范围和沙盒权限。"
            "创建前台或后台子 Agent；provider与工作区选择遵循当前系统提示。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "子 Agent 必须完成的具体目标。"},
                "mode": {"type": "string", "description": "foreground 或 background。默认 background。"},
                "allowed_tools": {"type": "array", "description": "允许子 Agent 使用的工具名列表。"},
                "access_mode": {"type": "string", "description": "readonly、sandbox 或 full_access。"},
                "input_refs": {"type": "array", "description": "传给子 Agent 的输入引用列表。"},
                "output_contract": {"type": "object", "description": "对子 Agent 结果格式的要求。"},
                "agent_type": {
                    "type": "string",
                    "enum": ["explore", "dsh", "coding"],
                    "description": "真实子 Agent类型；代码任务有DSH时用dsh，否则用coding。",
                },
                "name": {
                    "type": "string",
                    "description": "子 Agent 名字,由主 Agent 起名;留空自动用角色模板名(如 plan1/agent1)。",
                },
                "workspace_root": {
                    "type": "string",
                    "description": "agent_type为dsh或coding时必填的工作区绝对路径。",
                },
            },
            "required": ["goal", "agent_type"],
        },
        function=spawn_child_agent,
    ),
    BuiltinToolDefinition(
        name="wait_for_child_agents",
        display_name="等待子 Agent",
        description=(
            "等待当前父 Agent 已召唤的一个后台子 Agent 产出终态结果。"
            "使用 spawn_child_agent 派发后台子 Agent 后,必须调用本工具逐个收取结果,否则子 Agent 结果不会出现在本轮。"
            "本工具一次最多返回一个子 Agent 的 completed/failed/stopped 结果;"
            "如果结果队列已有结果会立即返回,否则阻塞到下一个结果或超时。"
            "run_ids 为空时等待当前父 Agent 任意子 Agent 的下一个结果。"
            "如果返回的 children 中仍有 created/running 子 Agent,必须继续调用本工具。"
            "只有所有需要的后台子 Agent 都进入 completed/failed/stopped 后,才能汇总最终回答。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "run_ids": {"type": "array", "description": "可选,要等待的子 Agent run_id 列表。为空表示等待全部。"},
                "timeout_seconds": {"type": "number", "description": "可选等待秒数,默认 600。超时会返回当时状态。"},
            },
            "required": [],
        },
        function=wait_for_child_agents,
    ),
    BuiltinToolDefinition(
        name="continue_child_agent",
        display_name="继续 DSH 子 Agent",
        description=(
            "向已完成或失败的 DSH 子 Agent提交下一轮指令,复用原 run_id、Runtime和会话上下文。"
            "用于修复刚才失败的测试、继续检查调用链或完善同一代码任务。"
            "提交background后继续使用wait_for_child_agents收取结果。"
        ),
        args_schema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "原 DSH 子 Agent run_id。"},
                "prompt": {"type": "string", "description": "基于现有上下文继续执行的明确指令。"},
                "mode": {"type": "string", "enum": ["foreground", "background"], "description": "默认background。"},
            },
            "required": ["run_id", "prompt"],
        },
        function=continue_child_agent,
    ),
]

TODO_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = [
    BuiltinToolDefinition(
        name="list_todos",
        description="列出当前用户的所有待办事项。每行包含编号、ID(todo_xxx)、完成状态和截止日期。后续切换/编辑/删除时需要从输出中提取该 ID。",
        args_schema={"type": "object", "properties": {}, "required": []},
        function=list_todos,
        display_name="列出待办",
    ),
    BuiltinToolDefinition(
        name="add_todo",
        description="新增一条待办事项。可指定可选的截止日期。返回值包含新待办的 ID(todo_xxx),可供后续切换/编辑/删除使用。",
        args_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待办事项的文字描述。"},
                "due_date": {"type": "string", "description": "可选截止日期,格式 YYYY-MM-DD。"},
            },
            "required": ["text"],
        },
        function=add_todo,
        display_name="新增待办",
    ),
    BuiltinToolDefinition(
        name="add_automation",
        description="创建一个定时自动化任务,到时间后独立唤醒 Agent 执行指定 prompt。涉及写文件、git commit 等操作时,需要明确指定合适的 access_mode。",
        args_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "侧边栏中显示的自动化任务名称。"},
                "prompt": {"type": "string", "description": "到时间后交给 Agent 执行的任务说明。"},
                "next_run_at": {"type": "string", "description": "下一次执行时间,必须是带时区偏移的 ISO 时间,例如 2026-08-03T21:00:00+08:00。"},
                "timezone_name": {"type": "string", "description": "循环使用的 IANA 时区,默认 Asia/Shanghai。"},
                "recurrence_frequency": {
                    "type": "string",
                    "enum": ["none", "daily", "weekly", "monthly"],
                    "description": "循环频率，默认 none（仅执行一次）。",
                },
                "provider": {
                    "type": "string",
                    "enum": ["native", "dsh"],
                    "description": "native为通用知识子 Agent；dsh为专用代码子 Agent。默认native。",
                },
                "workspace_root": {
                    "type": "string",
                    "description": "provider=dsh时要修改和测试的工作区绝对路径。",
                },
                "recurrence_interval": {
                    "type": "integer",
                    "minimum": DEFAULT_BUSINESS_LIMITS.nonempty_min_length,
                    "maximum": DEFAULT_BUSINESS_LIMITS.todo_recurrence_max_interval,
                },
                "access_mode": {"type": "string", "enum": ["readonly", "sandbox", "full_access"]},
            },
            "required": ["text", "prompt", "next_run_at"],
        },
        function=add_automation,
        display_name="创建自动化任务",
    ),
    BuiltinToolDefinition(
        name="toggle_todo",
        description="切换待办事项的完成状态(已完成↔未完成)。需要 todo_id。",
        args_schema={
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "待办的唯一 ID,可通过 list_todos 获取。"},
            },
            "required": ["todo_id"],
        },
        function=toggle_todo,
        display_name="切换待办状态",
    ),
    BuiltinToolDefinition(
        name="edit_todo",
        description="编辑待办事项的文本或截止日期。只传需要修改的字段。不传 text 则保留原文本。",
        args_schema={
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "待办的唯一 ID,可通过 list_todos 获取。"},
                "text": {"type": "string", "description": "新的待办文本,留空则不修改文本。"},
                "due_date": {"type": "string", "description": "新的截止日期(YYYY-MM-DD),传入空字符串清除截止日期,不传则不修改。"},
            },
            "required": ["todo_id"],
        },
        function=edit_todo,
        display_name="编辑待办",
    ),
    BuiltinToolDefinition(
        name="delete_todo",
        description="删除指定的待办事项。需要 todo_id。",
        args_schema={
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "待办的唯一 ID,可通过 list_todos 获取。"},
            },
            "required": ["todo_id"],
        },
        function=delete_todo,
        display_name="删除待办",
    ),
]

WEB_SEARCH_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = [
    BuiltinToolDefinition(
        name="web_search",
        description="通过 DuckDuckGo 搜索互联网,返回格式化搜索结果列表(标题+URL+摘要)。尽量少次搜索,每次搜索要覆盖全面——宁可一次搜完,也不要分多次搜。本工具仅返回文本结果,无法搜索图片。如需搜索图片请使用 web_image_search 工具。",
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词。尽量精确、全面,一次覆盖所有可能的关键词。"},
                "max_results": {"type": "integer", "description": "最大返回结果数,不传则使用用户的配置值。"},
                "region": {"type": "string", "description": "搜索区域代码,默认 cn-zh。"},
                "time_range": {"type": "string", "description": "时间范围筛选。d/w/m/y。留空表示不限时间。"},
            },
            "required": ["query"],
        },
        function=web_search,
        display_name="联网搜索",
    ),
    BuiltinToolDefinition(
        name="web_image_search",
        description="通过 DuckDuckGo 搜索图片,返回图片 URL 列表,每个结果附带标题、图片地址、缩略图地址和来源页面 URL。搜索到图片后直接用 Markdown 热链接展示,不要调用 download_file 下载。",
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词。尽量精确、全面,一次覆盖所有可能的关键词。"},
                "max_results": {"type": "integer", "description": "最大返回结果数,不传则使用用户的配置值。"},
                "region": {"type": "string", "description": "搜索区域代码,默认 cn-zh。"},
            },
            "required": ["query"],
        },
        function=web_image_search,
        display_name="联网搜索图片",
    ),
]

from agent_service.tools.extended_definitions import EXTENDED_TOOL_DEFINITIONS  # noqa: E402

BUILTIN_TOOL_DEFINITIONS: list[BuiltinToolDefinition] = (
    UTILITY_TOOL_DEFINITIONS
    + GIT_TOOL_DEFINITIONS
    + SKILL_TOOL_DEFINITIONS
    + MEMORY_TOOL_DEFINITIONS
    + KNOWLEDGE_TOOL_DEFINITIONS
    + LIBRARY_TOOL_DEFINITIONS
    + FILE_TOOL_DEFINITIONS
    + TASK_LIST_TOOL_DEFINITIONS
    + CHILD_AGENT_TOOL_DEFINITIONS
    + TODO_TOOL_DEFINITIONS
    + WEB_SEARCH_TOOL_DEFINITIONS
    + EXTENDED_TOOL_DEFINITIONS
)
