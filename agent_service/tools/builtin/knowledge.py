"""knowledge 类内置工具实现。

函数体由原 builtin.py 机械迁移，工具行为不变。
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from agent_service.tools.runtime_context import (
    AGENT_ACCESS_READONLY,
    get_markdown_html_visualization_callback,
    get_task_list_callback,
    get_tool_service,
    get_tool_runtime,
    register_network_citation,
    register_tool_citation,
)
from agent_service.schemas.longterm_memory_spec import LongTermMemorySpecCreate
from agent_service.services.todo.service import TodoService
from agent_service.services.automation.service import AutomationService
from agent_service.tools.builtin.builtin import (
    BuiltinToolDefinition, _deny_readonly_write, _is_readonly_access,
    _safe_visualization_filename, _strip_markdown_html_fence,
)

def rebuild_knowledge_base(knowledge_dir: str = "") -> str:
    """
    主动重新扫描当前用户的知识库并灌入向量库。

    knowledge_dir: 可选新知识库目录;为空时使用当前用户设置中的目录。
    """

    if _is_readonly_access():
        return _deny_readonly_write("重建知识库")
    runtime = get_tool_runtime()
    from agent_service.services.knowledge_library import KnowledgeLibraryService
    from agent_service.services.settings.service import SettingsService

    if runtime.memory_service is None:
        return "知识库重建失败: 当前工具运行时缺少记忆写入服务。"
    settings_service = SettingsService(config=runtime.config, memory_service=runtime.memory_service)
    knowledge_service = KnowledgeLibraryService(
        config=runtime.config,
        memory_service=runtime.memory_service,
        settings_service=settings_service,
        embedding_service=runtime.embedding_service,
    )
    try:
        result = knowledge_service.rebuild_user_knowledge(
            user_id=runtime.user_id,
            knowledge_dir=knowledge_dir.strip() or None,
        )
    except ValueError as exc:
        return f"知识库重建失败: {exc}"
    return (
        "知识库重建完成: "
        f"扫描 {result.frontmatter_files_seen} 个文件, "
        f"写入 {result.files_ingested} 个文档, "
        f"创建 {result.chunks_created} 个切片, "
        f"清理 {result.chunks_deleted} 个旧切片。"
    )
def search_knowledge(
    query: str,
    sources: list[str] | None = None,
    fulltext: bool = True,
    semantic: bool = False,
) -> str:
    """复用前端同源服务搜索文件库、图书馆、组件库和文献库。"""

    runtime = get_tool_runtime()
    service = runtime.unified_search_service
    if service is None:
        return "搜索失败: 当前 Agent 运行时缺少四库联合搜索服务。"
    selected_sources = set(sources if sources is not None else ("files", "library", "components", "literature"))
    payload = service.search(
        user_id=runtime.user_id,
        query=query,
        sources=selected_sources,
        fulltext=fulltext,
        semantic=semantic,
    )
    results = list(payload.get("results") or [])
    if not results:
        return f"四库联合搜索未找到与 '{query}' 相关的结果。"

    source_labels = {
        "files": "文件库",
        "library": "图书馆",
        "components": "组件库",
        "literature": "文献库",
    }
    mode_labels = {"title": "标题", "fulltext": "全文", "semantic": "语义"}
    lines = [
        "请在最终回答中引用需要挂载的结果编号（例如 [K1]）。",
        f"四库联合搜索共 {len(results)} 条结果:",
    ]
    for index, result in enumerate(results, 1):
        source = str(result.get("source") or "")
        title = str(result.get("title") or result.get("id") or "未命名结果")
        locator = str(result.get("locator") or result.get("id") or title)
        snippet = str(result.get("snippet") or "")
        citation_id = register_tool_citation(
            source_uri=locator,
            content=snippet or title,
            metadata={"search_result": result},
        )
        lines.append(f"{index}. [{source_labels.get(source, source)}] 来源: {locator} [{citation_id}]")
        lines.append(f"   标题: {title}")
        modes = [mode_labels.get(str(mode), str(mode)) for mode in result.get("matched_modes") or []]
        if modes:
            lines.append(f"   命中: {', '.join(modes)}")
        if snippet:
            lines.append(f"   片段: {snippet}")
    return "\n".join(lines)
def _build_knowledge_service():
    """从当前工具运行时构建 KnowledgeLibraryService 实例。"""
    from agent_service.services.knowledge_library import KnowledgeLibraryService
    from agent_service.services.settings.service import SettingsService

    runtime = get_tool_runtime()
    if runtime.memory_service is None:
        raise RuntimeError("缺少 MemoryService,无法操作知识库文件系统。")
    settings_service = SettingsService(config=runtime.config, memory_service=runtime.memory_service)
    return KnowledgeLibraryService(
        config=runtime.config,
        memory_service=runtime.memory_service,
        settings_service=settings_service,
        embedding_service=runtime.embedding_service,
    )
def _flatten_tree(nodes: list[dict], prefix: str = "") -> list[str]:
    """递归展开文件树为路径字符串列表。"""
    lines: list[str] = []
    for node in nodes:
        full = f"{prefix}/{node['name']}" if prefix else node["name"]
        kind = "[DIR]" if node.get("isDir") else "[FILE]"
        size = f" ({node.get('size', 0)} bytes)" if not node.get("isDir") and node.get("size") else ""
        lines.append(f"  {kind} {full}{size}")
        if node.get("isDir") and node.get("children"):
            lines.extend(_flatten_tree(node["children"], full))
    return lines
def list_knowledge_files() -> str:
    """
    列出当前用户知识库的完整文件树。

    返回值: 包含文件总数统计和完整路径列表的人类可读文本。
    """

    runtime = get_tool_runtime()
    service = _build_knowledge_service()
    try:
        tree = service.list_files(user_id=runtime.user_id)
    except Exception as exc:
        return f"列出文件失败: {exc}"
    if not tree:
        return "知识库为空,暂无任何文件或文件夹。"
    flat = _flatten_tree(tree)
    file_count = sum(1 for line in flat if line.strip().startswith("[FILE]"))
    dir_count = sum(1 for line in flat if line.strip().startswith("[DIR]"))
    summary = f"共 {file_count} 个文件, {dir_count} 个文件夹:\n"
    return summary + "\n".join(flat)
def read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    cursor: int | None = None,
) -> str:
    """按需读取知识库文件或会话附件；会话附件首次读取时才解析并缓存。"""

    runtime = get_tool_runtime()
    prefix = "attachment://"
    normalized_path = path.strip()
    if not normalized_path:
        return "读取文件失败: path 不能为空。"
    if not normalized_path.startswith(prefix):
        service = _build_knowledge_service()
        try:
            result = service.read_markdown_projection(user_id=runtime.user_id, path=normalized_path)
        except Exception as exc:
            return f"读取文件失败: {exc}"
        content = str(result.get("content", ""))
        source_uri = str(result.get("path") or normalized_path)
        citation_id = register_tool_citation(
            source_uri=source_uri,
            content=content,
            adopted_by_default=True,
        )
        return f"Citation ID: [{citation_id}]\nSource: {source_uri}\n\n{content}"

    attachment_id = normalized_path.removeprefix(prefix).strip()
    if not attachment_id:
        return "读取文件失败: attachment:// 引用缺少附件 ID。"
    try:
        record, content = get_tool_service("session_attachment").read_attachment_text(
            user_id=runtime.user_id,
            session_id=runtime.session_id,
            attachment_id=attachment_id,
        )
    except Exception as exc:
        return f"读取文件失败: {exc}"
    lines = content.splitlines()
    start = max(int(cursor if cursor is not None else start_line or 0), 0)
    default_lines = runtime.config.limits.terminal_read_default_lines
    max_lines = runtime.config.limits.terminal_read_max_lines
    requested_end = int(end_line) if end_line is not None else start + default_lines
    end = min(max(requested_end, start), start + max_lines, len(lines))
    next_cursor = end if end < len(lines) else None
    return json.dumps({
        "path": normalized_path,
        "filename": record.filename,
        "start_line": start,
        "end_line": end,
        "total_lines": len(lines),
        "next_cursor": next_cursor,
        "complete": next_cursor is None,
        "content": "\n".join(lines[start:end]),
    }, ensure_ascii=False, indent=2)
def write_knowledge_file(path: str, content: str) -> str:
    """
    在知识库中创建或覆盖一个文本文件。

    path: 文件相对于知识库根目录的路径,例如 `notes/summary.md`。
    content: 要写入的完整文件内容。
    """

    if _is_readonly_access():
        return _deny_readonly_write("写入知识库文件")
    runtime = get_tool_runtime()
    service = _build_knowledge_service()
    try:
        try:
            before = service.read_file(user_id=runtime.user_id, path=path)["content"]
        except ValueError:
            before = None
        result = service.write_file(user_id=runtime.user_id, path=path, content=content)
        if runtime.change_service is not None:
            runtime.change_service.record_edit(
                user_id=runtime.user_id,
                run_id=runtime.run_id,
                path=str(result["path"]),
                before=before,
                after=content,
            )
    except Exception as exc:
        return f"写入文件失败: {exc}"
    return f"已保存文件: {result['path']} (大小: {result.get('size', 'N/A')} 字节)"
def patch_knowledge_file(path: str, old_text: str, new_text: str) -> str:
    """Replace one unique text fragment in an existing knowledge file."""

    if _is_readonly_access():
        return _deny_readonly_write("局部修改知识库文件")
    if not old_text:
        return "局部修改失败: old_text 不能为空。"
    runtime = get_tool_runtime()
    service = _build_knowledge_service()
    try:
        before = service.read_file(user_id=runtime.user_id, path=path)["content"]
        occurrences = before.count(old_text)
        if occurrences != 1:
            return f"局部修改失败: 目标片段应唯一命中，当前命中 {occurrences} 次。"
        after = before.replace(old_text, new_text, 1)
        result = service.write_file(user_id=runtime.user_id, path=path, content=after)
        # Keep the complete file versions for the tool trace so its preview and
        # the persisted turn snapshot calculate the same absolute line numbers.
        runtime.latest_file_patch = {"path": str(result["path"]), "before": before, "after": after, "complete": True}
        if runtime.change_service is not None:
            runtime.change_service.record_edit(
                user_id=runtime.user_id, run_id=runtime.run_id, path=str(result["path"]), before=before, after=after,
            )
    except Exception as exc:
        return f"局部修改失败: {exc}"
    return f"已局部修改文件: {result['path']}"
def show_markdown_html(title: str, html: str, source_path: str = "", filename: str = "") -> str:
    """
    Save generated document visualization HTML under runtime/visualizations and notify the front-end.

    title: Human-readable title shown by the front-end visualization panel.
    html: Complete HTML document or HTML fragment generated from the source document.
    source_path: Optional source document path relative to the active knowledge library root.
    filename: Optional preferred output filename; it is sanitized and timestamped.
    """

    if _is_readonly_access():
        return _deny_readonly_write("generate Markdown-HTML visualization")
    clean_html = _strip_markdown_html_fence(html)
    if not clean_html:
        return "Markdown-HTML visualization failed: html is empty."

    runtime = get_tool_runtime()
    output_dir = (runtime.config.storage.base_data_dir / "visualizations").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_visualization_filename(title, source_path, filename)
    output_path = (output_dir / safe_name).resolve()
    if output_dir not in output_path.parents and output_path != output_dir:
        return "Markdown-HTML visualization failed: output path escaped runtime directory."

    try:
        output_path.write_text(clean_html, encoding="utf-8")
    except Exception as exc:
        return f"Markdown-HTML visualization failed: {exc}"

    display_title = title.strip() or source_path.strip() or safe_name
    payload = {
        "title": display_title,
        "filename": safe_name,
        "path": str(output_path),
        "url": f"/visualizations/{safe_name}",
        "source_path": source_path,
        "created_at": datetime.now().isoformat(),
    }
    callback = get_markdown_html_visualization_callback()
    if callback is not None:
        callback(payload)
    return (
        f"Markdown-HTML visualization generated and mounted: {display_title}\n"
        f"URL: {payload['url']}\n"
        f"Local path: {output_path}"
    )
def delete_knowledge_file(path: str) -> str:
    """
    删除知识库中的文件或文件夹。

    path: 文件或文件夹相对于知识库根目录的路径。
    注意: 删除文件夹会递归删除其下所有内容。
    """

    if _is_readonly_access():
        return _deny_readonly_write("删除知识库文件")
    runtime = get_tool_runtime()
    service = _build_knowledge_service()
    try:
        service.delete_path(user_id=runtime.user_id, path=path)
    except Exception as exc:
        return f"删除失败: {exc}"
    return f"已删除: {path}"
def rename_knowledge_file(source_path: str, target_path: str) -> str:
    """
    重命名或移动知识库中的文件/文件夹。

    source_path: 当前相对路径,例如 `old_name.md`。
    target_path: 新相对路径,例如 `new_name.md` 或 `archive/new_name.md`。
    """

    if _is_readonly_access():
        return _deny_readonly_write("重命名或移动知识库文件")
    runtime = get_tool_runtime()
    service = _build_knowledge_service()
    try:
        result = service.rename_path(user_id=runtime.user_id, source_path=source_path, target_path=target_path)
    except Exception as exc:
        return f"重命名失败: {exc}"
    return f"已重命名: {source_path} -> {result['path']}"
def create_knowledge_folder(path: str) -> str:
    """
    在知识库中创建新文件夹。

    path: 文件夹相对于知识库根目录的路径,例如 `projects/new-project`。
    """

    if _is_readonly_access():
        return _deny_readonly_write("创建知识库文件夹")
    runtime = get_tool_runtime()
    service = _build_knowledge_service()
    try:
        result = service.create_folder(user_id=runtime.user_id, path=path)
    except Exception as exc:
        return f"创建文件夹失败: {exc}"
    return f"已创建文件夹: {result['path']}"
def save_uploaded_attachment_to_knowledge(
    attachment: str = "",
    target_path: str = "",
    conflict_strategy: str = "rename",
    ingest: bool = True,
) -> str:
    """
    Promote one session-uploaded attachment into the active knowledge library.

    attachment: Optional attachment_id, exact filename, or filename keyword. Empty means the latest session attachment.
    target_path: Optional target relative path in the active knowledge library. Empty keeps the original filename at root.
    conflict_strategy: overwrite, skip, or rename. Defaults to rename.
    ingest: Whether to immediately ingest the copied file into the knowledge index.
    """

    from pathlib import Path

    from sqlalchemy import desc
    from sqlmodel import Session, select

    from agent_service.models.attachment import SessionAttachmentRecord

    if _is_readonly_access():
        return _deny_readonly_write("保存上传附件到知识库")
    runtime = get_tool_runtime()
    service = _build_knowledge_service()
    normalized_attachment = attachment.strip()
    engine = runtime.database_engine
    if engine is None:
        return "No application database is available for uploaded attachments."
    statement = (
        select(SessionAttachmentRecord)
        .where(SessionAttachmentRecord.user_id == runtime.user_id)
        .where(SessionAttachmentRecord.session_id == runtime.session_id)
        .order_by(desc(SessionAttachmentRecord.created_at))
    )
    with Session(engine) as db_session:
        attachments = list(db_session.exec(statement).all())
    if not attachments:
        return "No uploaded attachments were found in the current session."

    if normalized_attachment:
        lowered = normalized_attachment.casefold()
        matches = [
            item for item in attachments
            if item.attachment_id == normalized_attachment
            or item.filename.casefold() == lowered
            or lowered in item.filename.casefold()
        ]
    else:
        matches = [attachments[0]]

    if not matches:
        available = "\n".join(
            f"- {item.filename} ({item.attachment_id})"
            for item in attachments[:runtime.config.limits.tool_attachment_match_preview_count]
        )
        return f"Attachment not found in this session. Available attachments:\n{available}"
    if len(matches) > 1:
        available = "\n".join(
            f"- {item.filename} ({item.attachment_id})"
            for item in matches[:runtime.config.limits.tool_attachment_match_preview_count]
        )
        return f"Multiple uploaded attachments matched. Please specify one attachment_id:\n{available}"

    record = matches[0]
    source_path = Path(record.path).expanduser().resolve()
    if not source_path.is_file():
        return f"Attachment file is missing from runtime uploads: {record.filename}"

    normalized_strategy = conflict_strategy.strip().lower() or "rename"
    if normalized_strategy not in {"overwrite", "skip", "rename"}:
        return "Invalid conflict_strategy. Use overwrite, skip, or rename."

    raw_target = target_path.strip().replace("\\", "/").strip("/")
    if raw_target:
        target = Path(raw_target)
        if raw_target.endswith("/"):
            relative_dir = raw_target.rstrip("/")
            target_filename = record.filename
        else:
            relative_dir = target.parent.as_posix() if str(target.parent) != "." else ""
            target_filename = target.name or record.filename
    else:
        relative_dir = ""
        target_filename = record.filename

    try:
        copied_path = service.write_uploaded_file(
            user_id=runtime.user_id,
            filename=target_filename,
            content=source_path.read_bytes(),
            relative_dir=relative_dir,
            conflict_strategy=normalized_strategy,
        )
    except Exception as exc:
        return f"Failed to copy attachment into the knowledge library: {exc}"

    root = service.get_active_root_path(user_id=runtime.user_id)
    try:
        relative_path = copied_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return f"Copied file escaped the active knowledge library: {copied_path}"

    if not ingest:
        return f"Saved uploaded attachment to knowledge library: {relative_path}. It was not ingested."

    try:
        result = service.ingest_single_file(user_id=runtime.user_id, path=relative_path)
    except Exception as exc:
        return f"Saved uploaded attachment to knowledge library as {relative_path}, but ingestion failed: {exc}"

    status = result.status_message or "ingested"
    return (
        f"Saved uploaded attachment to knowledge library: {relative_path}\n"
        f"Ingestion status: {status}\n"
        f"Files ingested: {result.files_ingested}; chunks created: {result.chunks_created}; "
        f"files skipped: {result.files_skipped}; skip reason: {result.skip_reason or 'none'}."
    )
def _read_attachment_ocr_text(text_path: Path) -> str:
    """读取附件正文并移除先前生成的视觉理解章节。"""

    if not text_path.is_file():
        return ""
    kept: list[str] = []
    skipping_vision = False
    for line in text_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## "):
            skipping_vision = "视觉理解" in line
        if not skipping_vision:
            kept.append(line)
    return "\n".join(kept).strip()


def understand_image(attachment: str = "", prompt: str = "") -> str:
    """使用已配置的远程视觉模型重新理解当前会话中的上传图片。

    attachment: 可选 attachment_id、完整文件名或文件名关键词；为空使用最新图片。
    prompt: 可选识图问题；为空返回对象、布局、关系和图表语义的综合描述。
    """

    from pathlib import Path

    from sqlalchemy import desc
    from sqlmodel import Session, select

    from agent_service.models.attachment import SessionAttachmentRecord
    from agent_service.services.vision.service import (
        VisionConfigurationError,
        VisionInputError,
        VisionRequestError,
    )

    runtime = get_tool_runtime()
    if (
        runtime.settings_service is None
        or not runtime.settings_service.is_vision_understanding_enabled_for_user(user_id=runtime.user_id)
    ):
        return "识图功能未开启；当前图片仅使用已提取的 OCR 文字，不会发送到远程视觉模型。"
    engine = runtime.database_engine
    if engine is None:
        return "当前工具运行时没有可用的应用数据库。"
    statement = (
        select(SessionAttachmentRecord)
        .where(SessionAttachmentRecord.user_id == runtime.user_id)
        .where(SessionAttachmentRecord.session_id == runtime.session_id)
        .order_by(desc(SessionAttachmentRecord.created_at))
    )
    with Session(engine) as db_session:
        images = [
            item for item in db_session.exec(statement).all()
            if Path(item.filename).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        ]
    if not images:
        return "当前会话没有可识别的已上传图片。"
    normalized = attachment.strip().casefold()
    matches = images if not normalized else [
        item for item in images
        if item.attachment_id.casefold() == normalized
        or item.filename.casefold() == normalized
        or normalized in item.filename.casefold()
    ]
    if not matches:
        return "未找到指定图片。可用图片:\n" + "\n".join(
            f"- {item.filename} ({item.attachment_id})"
            for item in images[:runtime.config.limits.tool_attachment_match_preview_count]
        )
    if len(matches) > 1 and normalized:
        return "匹配到多张图片，请指定 attachment_id:\n" + "\n".join(
            f"- {item.filename} ({item.attachment_id})"
            for item in matches[:runtime.config.limits.tool_attachment_match_preview_count]
        )
    record = matches[0]
    image_path = Path(record.path).expanduser().resolve()
    if not image_path.is_file():
        return f"图片文件已不存在: {record.filename}"
    text_path = Path(record.text_path).expanduser().resolve() if record.text_path else None
    ocr_text = _read_attachment_ocr_text(text_path) if text_path is not None else ""
    try:
        vision_service = get_tool_service("vision")
        result = vision_service.understand_image(
            user_id=runtime.user_id,
            image_path=image_path,
            ocr_text=ocr_text,
            prompt=prompt,
        )
    except (VisionConfigurationError, VisionInputError, VisionRequestError) as exc:
        return f"识图失败: {exc}"
    except Exception as exc:  # noqa: BLE001 - unexpected provider errors must remain redacted.
        return f"识图失败: {type(exc).__name__}"
    return f"图片: {record.filename}\n视觉模型: {result.model_name}\n视觉理解:\n{result.text}"
def get_current_viewing_document() -> str:
    """
    获取当前用户在 editor 前端正在观看的文档基本信息。

    返回值只包含路径、文件名、知识库、大小、修改时间和 dirty 状态等基本信息;
    不返回文件正文。若需要正文,应继续调用 read_file(path)。
    """

    runtime = get_tool_runtime()
    from agent_service.services.editor_context.service import editor_context_service

    info = editor_context_service.get_current_document(runtime.user_id)
    if info is None:
        return "当前没有 editor 前端上报的正在观看文档。"
    if not info.path:
        return "当前用户没有正在观看的活动文件。"
    return json.dumps(
        {
            "path": info.path,
            "name": info.name,
            "knowledge_dir": info.knowledge_dir,
            "library_id": info.library_id,
            "library_name": info.library_name,
            "size": info.size,
            "mtime": info.mtime,
            "dirty": info.dirty,
            "open_tab_count": info.open_tab_count,
            "updated_at": info.updated_at,
            "next_step_hint": "如需读取正文,请调用 read_file 并传入 path。",
        },
        ensure_ascii=False,
    )
def get_knowledge_file_url(path: str) -> str:
    """
    获取知识库中本地文件的浏览器可访问 URL。用于在回复中以 Markdown 图片或链接形式引用知识库文件。

    path: 文件相对于知识库根目录的路径。
    """

    runtime = get_tool_runtime()
    return f"/knowledge/files/raw?user_id={runtime.user_id}&path={path}"
