"""web 类内置工具实现。

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

def web_search(
    query: str,
    max_results: int | None = None,
    region: str = "cn-zh",
    time_range: str = "",
) -> str:
    """
    通过 DuckDuckGo 搜索互联网，返回格式化的搜索结果列表。

    query: 搜索关键词。
    max_results: 最大返回结果数，不传则使用用户的配置值。
    region: 搜索区域代码，默认 cn-zh（中国中文）。
    time_range: 时间范围。d=一天内, w=一周内, m=一个月内, y=一年内。留空不限时间。
    """
    try:
        runtime = get_tool_runtime()
    except RuntimeError:
        return "搜索失败：无法获取运行上下文。"

    try:
        if runtime.settings_service is None:
            return "搜索失败：设置服务未就绪。"
        config = runtime.settings_service.get_web_search_config(user_id=runtime.user_id)
    except Exception:
        return "搜索失败：无法读取搜索配置。"

    if not config.get("web_search_enabled", False):
        return "联网搜索未启用，请在设置中开启。"

    proxy_url = config.get("proxy_url", "") or ""
    limits = runtime.config.limits
    configured_max = config.get("web_search_max_results", limits.default_web_search_max_results) or limits.default_web_search_max_results
    effective_max = max(1, configured_max)

    try:
        from ddgs import DDGS
        import time
        raw_results = []
        for attempt in range(limits.web_search_retry_count):
            with DDGS(proxy=proxy_url or None, timeout=limits.web_search_timeout_seconds) as ddgs:
                raw_results = list(ddgs.text(
                    query,
                    region=region,
                    max_results=effective_max * limits.web_search_candidate_multiplier,
                    timelimit=time_range if time_range else None,
                ))
            if raw_results:
                break
            if attempt < limits.web_search_retry_count - 1:
                time.sleep(limits.web_search_retry_delay_seconds)
    except Exception as exc:
        return f"搜索失败: {exc}"

    if not raw_results:
        return "未搜索到相关结果。"

    seen_hrefs: set[str] = set()
    filtered: list[dict] = []
    for item in raw_results:
        href = (item.get("href") or "").strip()
        title = (item.get("title") or "").strip()
        body = (item.get("body") or "").strip()
        if not href or not title or not body:
            continue
        if href in seen_hrefs:
            continue
        if len(body) < limits.web_search_min_snippet_chars:
            continue
        seen_hrefs.add(href)
        filtered.append(item)
        if len(filtered) >= effective_max:
            break

    if not filtered:
        return "未搜索到相关结果。"

    # Try to fetch full page text for each result, fall back to DDGS snippet on failure
    import html as html_mod
    import re as re_mod
    import urllib.request as url_req

    def extract_page_text(url: str, fallback: str) -> str:
        """Fetch a URL and extract readable text. Returns fallback on any failure."""
        try:
            req = url_req.Request(url, headers={"User-Agent": "MetaWeave/1.0"})
            with url_req.urlopen(req, timeout=limits.web_fetch_timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            # Strip HTML tags
            text = re_mod.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re_mod.DOTALL | re_mod.IGNORECASE)
            text = re_mod.sub(r"<style[^>]*>.*?</style>", "", text, flags=re_mod.DOTALL | re_mod.IGNORECASE)
            text = re_mod.sub(r"<[^>]+>", " ", text)
            text = html_mod.unescape(text)
            # Collapse whitespace
            text = re_mod.sub(r"\s+", " ", text).strip()
            if len(text) < limits.web_fetch_min_chars:
                return fallback
            return text
        except Exception:
            return fallback

    lines: list[str] = []
    for i, item in enumerate(filtered, 1):
        title = item.get("title", "").strip()
        href = item.get("href", "").strip()
        body = item.get("body", "").strip()
        full_text = extract_page_text(href, body)
        citation_id = register_network_citation(
            source_uri=href,
            content=full_text,
            title=title,
            adopted_by_default=False,
        )
        lines.append(f"{i}. {title}")
        lines.append(f"   Citation ID: [{citation_id}]")
        lines.append(f"   URL: {href}")
        lines.append(f"   摘要: {full_text}")
        if i < len(filtered):
            lines.append("")
    lines.append("")
    lines.append("Citation rule: only cite a result with its exact [N#] id when facts from that result are used in the final answer.")
    return "\n".join(lines)
def web_image_search(
    query: str,
    max_results: int | None = None,
    region: str = "cn-zh",
) -> str:
    """
    通过 DuckDuckGo 搜索图片，返回图片结果列表（含图片 URL、标题、来源页面）。

    query: 搜索关键词。
    max_results: 最大返回结果数，不传则使用用户的配置值。
    region: 搜索区域代码，默认 cn-zh（中国中文）。
    """
    try:
        runtime = get_tool_runtime()
    except RuntimeError:
        return "搜索失败：无法获取运行上下文。"

    try:
        if runtime.settings_service is None:
            return "搜索失败：设置服务未就绪。"
        config = runtime.settings_service.get_web_search_config(user_id=runtime.user_id)
    except Exception:
        return "搜索失败：无法读取搜索配置。"

    if not config.get("web_search_enabled", False):
        return "联网搜索未启用，请在设置中开启。"

    proxy_url = config.get("proxy_url", "") or ""
    limits = runtime.config.limits
    configured_max = config.get("web_search_max_results", limits.default_web_search_max_results) or limits.default_web_search_max_results
    effective_max = max(1, configured_max)

    try:
        from ddgs import DDGS
        import time
        raw_results = []
        for attempt in range(limits.web_search_retry_count):
            with DDGS(proxy=proxy_url or None, timeout=limits.web_search_timeout_seconds) as ddgs:
                raw_results = list(ddgs.images(
                    query,
                    region=region,
                    max_results=effective_max,
                ))
            if raw_results:
                break
            if attempt < limits.web_search_retry_count - 1:
                time.sleep(limits.web_search_retry_delay_seconds)
    except Exception as exc:
        return f"图片搜索失败: {exc}"

    if not raw_results:
        return "未搜索到相关图片结果。"

    seen_image_urls: set[str] = set()
    filtered: list[dict] = []
    for item in raw_results:
        image_url = (item.get("image") or "").strip()
        title = (item.get("title") or "").strip()
        source_url = (item.get("url") or "").strip()
        if not image_url or not title:
            continue
        if image_url in seen_image_urls:
            continue
        seen_image_urls.add(image_url)
        filtered.append(item)
        if len(filtered) >= effective_max:
            break

    if not filtered:
        return "未搜索到相关图片结果。"

    lines: list[str] = []
    for i, item in enumerate(filtered, 1):
        title = item.get("title", "").strip()
        image_url = item.get("image", "").strip()
        source_url = item.get("url", "").strip()
        thumbnail_url = item.get("thumbnail", "").strip()

        citation_id = register_network_citation(
            source_uri=source_url,
            content=f"图片标题: {title}\n图片 URL: {image_url}",
            title=title,
            adopted_by_default=False,
        )
        lines.append(f"{i}. {title}")
        lines.append(f"   Citation ID: [{citation_id}]")
        lines.append(f"   图片地址: {image_url}")
        lines.append(f"   缩略图: {thumbnail_url}")
        lines.append(f"   来源页面: {source_url}")
        lines.append(f"   Markdown展示: ![{title}]({image_url})")
        if i < len(filtered):
            lines.append("")

    lines.append("")
    lines.append("Citation rule: only cite a result with its exact [N#] id when facts from that result are used in the final answer.")
    return "\n".join(lines)
def download_file(url: str, save_to_knowledge: bool = False) -> str:
    """
    从网络下载文件并存储到本地。可选的 save_to_knowledge=True 可将下载的文件复制到知识库并灌库。

    url: 需要下载的文件的完整 URL。
    save_to_knowledge: 是否将下载后的文件复制到知识库并灌库。默认 False。
    """

    import uuid
    import urllib.request

    runtime = get_tool_runtime()
    downloads_dir = runtime.config.storage.assets_dir / "downloads" / runtime.user_id
    downloads_dir.mkdir(parents=True, exist_ok=True)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MetaWeave/1.0"})
        with urllib.request.urlopen(req, timeout=runtime.config.limits.download_timeout_seconds) as response:
            content = response.read()
            content_type = response.headers.get("Content-Type", "")
    except Exception as exc:
        return f"下载失败: {exc}"

    ext = _infer_extension(content_type, url)
    filename = f"{uuid.uuid4().hex}{ext}"
    local_path = downloads_dir / filename
    local_path.write_bytes(content)
    local_url = f"/downloads/{runtime.user_id}/{filename}"

    if not save_to_knowledge:
        return (
            f"文件已下载到本地。预览: ![]({local_url})\n\n"
            f"本地 URL: {local_url}\n"
            f"文件名: {filename}\n"
            f"类型: {content_type}\n"
            f"大小: {len(content)} 字节"
        )

    # Copy to knowledge library and ingest
    try:
        from agent_service.services.knowledge_library import KnowledgeLibraryService
        from agent_service.services.settings.service import SettingsService

        if runtime.memory_service is None:
            return "下载成功,但无法保存到知识库: 当前工具运行时缺少记忆写入服务。"

        settings_service = SettingsService(config=runtime.config, memory_service=runtime.memory_service)
        knowledge_service = KnowledgeLibraryService(
            config=runtime.config,
            memory_service=runtime.memory_service,
            settings_service=settings_service,
            embedding_service=runtime.embedding_service,
        )

        uploaded_path = knowledge_service.write_uploaded_file(
            user_id=runtime.user_id,
            filename=filename,
            content=content,
            relative_dir="",
            conflict_strategy="rename",
        )
        root = knowledge_service.get_active_root_path(user_id=runtime.user_id)
        relative_path = uploaded_path.resolve().relative_to(root.resolve()).as_posix()
        result = knowledge_service.ingest_single_file(user_id=runtime.user_id, path=relative_path)
        status = result.status_message or "ingested"

        return (
            f"文件已下载并存入知识库。预览: ![]({local_url})\n\n"
            f"本地 URL: {local_url}\n"
            f"知识库路径: {relative_path}\n"
            f"灌库状态: {status}\n"
            f"类型: {content_type}\n"
            f"大小: {len(content)} 字节"
        )
    except Exception as exc:
        return (
            f"文件已下载到本地,但存入知识库失败: {exc}\n"
            f"本地 URL: {local_url}\n"
            f"大小: {len(content)} 字节"
        )
def _infer_extension(content_type: str, url: str) -> str:
    """从 Content-Type 或 URL 后缀推断文件扩展名。"""

    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/bmp": ".bmp",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "text/html": ".html",
        "text/csv": ".csv",
        "application/json": ".json",
        "application/zip": ".zip",
    }
    for ct, ext in ext_map.items():
        if content_type.startswith(ct):
            return ext
    # Fallback: extract from URL
    import pathlib
    url_ext = pathlib.Path(url.split("?")[0].split("#")[0]).suffix
    if url_ext and len(url_ext) <= 6:
        return url_ext
    return ".bin"
