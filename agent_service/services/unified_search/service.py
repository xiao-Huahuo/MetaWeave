"""文件库、图书馆、组件库与文献库的统一检索服务。

功能说明：标题匹配始终执行；全文部分匹配和语义召回严格由调用参数控制。
语义搜索复用项目的 Embedding、Chroma、混合召回和 ReRank 链路，并按用户当前
active library 的 owner ID 隔离非文件类索引。

使用说明：由应用装配层注入四库服务和 ``MemoryRetrievalService``，API 层调用
``search`` 并直接返回统一结果与四库分组；``resolve_knowledge`` 按显式链接中的
稳定身份读取原生知识块，不依赖搜索缓存，并复用请求级库作用域校验原库归属。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from agent_service.schemas.longterm_memory_spec import LongTermMemorySpecCreate
from agent_service.services.memory.rag.chunk import chunk_text
from agent_service.services.settings.service import SettingsService
from agent_service.services.settings.mcp_settings import use_library

SEARCH_SOURCES = ("files", "library", "components", "literature")
SEARCH_MODES = ("title", "fulltext", "semantic")
UNIFIED_SEARCH_MEMORY_TYPE = "unified_search_chunk"


@dataclass(slots=True)
class _SearchDocument:
    """统一表示一个可搜索且可还原为原生前端卡片的业务资源。"""

    source: str
    resource_id: str
    title: str
    content: str
    locator: str
    updated_at: str
    item: dict[str, Any]
    source_path: str = ""

    @property
    def index_source_id(self) -> str:
        """返回长期记忆表中的稳定来源 ID。"""

        return f"unified:{self.source}:{self.resource_id}"

    @property
    def index_text(self) -> str:
        """返回同时保留标题与正文语义的索引文本。"""

        return "\n".join(part for part in (self.title, self.content) if part).strip()


class UnifiedSearchService:
    """协调四个正式数据源并输出可供两种前端样式共享的搜索结果。"""

    def __init__(
        self,
        *,
        settings_service: Any,
        knowledge_library_service: Any,
        library_service: Any,
        component_library_service: Any,
        smart_form_service: Any,
        retrieval_service: Any,
    ) -> None:
        """保存四库、设置与检索服务依赖。"""

        self.settings_service = settings_service
        self.knowledge_library_service = knowledge_library_service
        self.library_service = library_service
        self.component_library_service = component_library_service
        self.smart_form_service = smart_form_service
        self.retrieval_service = retrieval_service

    def resolve_knowledge(
        self, *, user_id: str, source: str, id: str, library_id: str = "",
    ) -> dict[str, Any]:
        """按稳定 ID 还原真实原生卡片，并在请求作用域验证原库归属。

        library_id 为空时使用当前库；有值时复用已有库作用域读取原库，不修改用户
        active library。ID 与原生列表相匹配，不能由模型输入拼造不存在的卡片。
        """

        normalized_user_id = str(user_id or "").strip()
        normalized_source = str(source or "").strip().casefold()
        normalized_id = str(id or "").strip()
        self._normalize_sources({normalized_source})
        if not normalized_user_id or not normalized_id:
            raise ValueError("user_id and id are required")
        profile = self.settings_service.ensure_user_profile(user_id=normalized_user_id)
        resolved_library_id = str(library_id or profile["active_knowledge_library"]["library_id"]).strip()
        with use_library(normalized_user_id, resolved_library_id):
            # 正式 SettingsService 在读取数据前确认 library_id 属于本请求用户。
            profile = self.settings_service.ensure_user_profile(user_id=normalized_user_id)
            if normalized_source == "files":
                root = Path(str(profile["active_knowledge_library"]["knowledge_dir"])).expanduser().resolve()
                normalized_id = self._relative_library_path(normalized_id, root)
                documents = self._collect_file_documents(user_id=normalized_user_id)
            elif normalized_source == "library":
                documents = self._collect_library_documents(user_id=normalized_user_id)
            elif normalized_source == "components":
                documents = self._collect_component_documents(user_id=normalized_user_id)
            else:
                documents = self._collect_literature_documents(
                    user_id=normalized_user_id, library_id=resolved_library_id,
                )
            document = next((item for item in documents if item.resource_id == normalized_id), None)
            if document is None:
                raise FileNotFoundError("知识对象不存在或已删除。")
            return {**self._serialize_document(document), "library_id": resolved_library_id}

    def search(
        self,
        *,
        user_id: str,
        query: str,
        sources: set[str] | Iterable[str],
        fulltext: bool,
        semantic: bool,
    ) -> dict[str, Any]:
        """按照用户选择的来源和能力开关执行四库联合搜索。"""

        normalized_user_id = str(user_id or "").strip()
        normalized_query = str(query or "").strip()
        selected_sources = self._normalize_sources(sources)
        if not normalized_user_id:
            raise ValueError("user_id is required")
        if not normalized_query:
            raise ValueError("query is required")

        profile = self.settings_service.ensure_user_profile(user_id=normalized_user_id)
        active_library = dict(profile["active_knowledge_library"])
        library_id = str(active_library["library_id"])
        library_root = Path(str(active_library["knowledge_dir"])).expanduser().resolve()
        knowledge_owner_id = SettingsService.build_knowledge_owner_id(
            user_id=normalized_user_id,
            library_id=library_id,
        )

        needs_file_candidates = "files" in selected_sources or (
            "library" in selected_sources and (fulltext or semantic)
        )
        documents: dict[str, list[_SearchDocument]] = {source: [] for source in SEARCH_SOURCES}
        if needs_file_candidates:
            documents["files"] = self._collect_file_documents(user_id=normalized_user_id)
        if "library" in selected_sources:
            documents["library"] = self._collect_library_documents(user_id=normalized_user_id)
        if "components" in selected_sources:
            documents["components"] = self._collect_component_documents(user_id=normalized_user_id)
        if "literature" in selected_sources:
            documents["literature"] = self._collect_literature_documents(
                user_id=normalized_user_id,
                library_id=library_id,
            )

        result_map: dict[tuple[str, str], dict[str, Any]] = {}
        query_folded = normalized_query.casefold()
        for source in selected_sources:
            for document in documents[source]:
                if query_folded in document.title.casefold():
                    self._merge_hit(
                        result_map=result_map,
                        document=document,
                        mode="title",
                        snippet=document.locator,
                        score=1.0 if document.title.casefold() == query_folded else 0.92,
                    )

        file_partial_hits: dict[str, dict[str, Any]] = {}
        if fulltext:
            if needs_file_candidates:
                file_partial_hits = self._search_file_fulltext(
                    user_id=normalized_user_id,
                    knowledge_owner_id=knowledge_owner_id,
                    query=normalized_query,
                    library_root=library_root,
                )
            if "files" in selected_sources:
                file_documents = {document.locator: document for document in documents["files"]}
                for path, hit in file_partial_hits.items():
                    document = file_documents.get(path)
                    if document is not None:
                        self._merge_hit(result_map, document, "fulltext", str(hit.get("snippet") or ""), 0.76)
            if "library" in selected_sources:
                self._merge_library_file_hits(
                    result_map=result_map,
                    documents=documents["library"],
                    file_hits=file_partial_hits,
                    mode="fulltext",
                )
            for source in ("library", "components", "literature"):
                if source not in selected_sources:
                    continue
                for document in documents[source]:
                    position = document.content.casefold().find(query_folded)
                    if position >= 0:
                        self._merge_hit(
                            result_map,
                            document,
                            "fulltext",
                            self._snippet(document.content, position, len(normalized_query)),
                            0.74,
                        )

        if semantic:
            semantic_sources = selected_sources.intersection({"library", "components", "literature"})
            custom_documents = [document for source in semantic_sources for document in documents[source]]
            if custom_documents:
                self._sync_semantic_index(
                    owner_id=knowledge_owner_id,
                    library_id=library_id,
                    selected_sources=semantic_sources,
                    documents=custom_documents,
                )
                current_documents = {document.index_source_id: document for document in custom_documents}
                per_source_top_k = int(getattr(
                    self.retrieval_service.config.memory,
                    "knowledge_search_semantic_top_k",
                    getattr(self.retrieval_service.config.memory, "rerank_top_k", 20),
                ))
                top_k = per_source_top_k * max(1, len(semantic_sources))
                for hit in self.retrieval_service.retrieve_unified_search(
                    query=normalized_query,
                    user_id=knowledge_owner_id,
                    top_k=top_k,
                ):
                    document = current_documents.get(str(hit.memory.source_id or ""))
                    if document is None:
                        continue
                    metadata = dict(hit.memory.metadata_json or {})
                    if metadata.get("library_id") != library_id or metadata.get("source") != document.source:
                        continue
                    self._merge_hit(
                        result_map,
                        document,
                        "semantic",
                        str(hit.memory.content or ""),
                        float(hit.final_score),
                    )

            if needs_file_candidates:
                file_semantic_hits = self._search_file_semantic(
                    user_id=normalized_user_id,
                    query=normalized_query,
                    library_root=library_root,
                )
                if "files" in selected_sources:
                    file_documents = {document.locator: document for document in documents["files"]}
                    for path, hit in file_semantic_hits.items():
                        document = file_documents.get(path)
                        if document is not None:
                            self._merge_hit(
                                result_map,
                                document,
                                "semantic",
                                str(hit.get("snippet") or ""),
                                float(hit.get("score") or 0.0),
                            )
                if "library" in selected_sources:
                    self._merge_library_file_hits(
                        result_map=result_map,
                        documents=documents["library"],
                        file_hits=file_semantic_hits,
                        mode="semantic",
                    )

        results = sorted(
            result_map.values(),
            key=lambda item: (-float(item["score"]), str(item["title"]).casefold(), str(item["id"])),
        )
        for result in results:
            result["library_id"] = library_id
        groups = {
            source: [result for result in results if result["source"] == source]
            for source in SEARCH_SOURCES
        }
        return {
            "query": normalized_query,
            "selected_sources": [source for source in SEARCH_SOURCES if source in selected_sources],
            "fulltext": bool(fulltext),
            "semantic": bool(semantic),
            "results": results,
            "groups": groups,
            "counts": {source: len(groups[source]) for source in SEARCH_SOURCES},
            "total": len(results),
        }

    @staticmethod
    def _normalize_sources(sources: set[str] | Iterable[str]) -> set[str]:
        """校验来源集合并保持至少一个真实库。"""

        normalized = {str(source).strip().casefold() for source in sources if str(source).strip()}
        unsupported = normalized.difference(SEARCH_SOURCES)
        if unsupported:
            raise ValueError(f"unsupported search sources: {', '.join(sorted(unsupported))}")
        if not normalized:
            raise ValueError("at least one search source is required")
        return normalized

    def _collect_file_documents(self, *, user_id: str) -> list[_SearchDocument]:
        """从正式文件树收集文件名候选，目录不参与结果。"""

        tree = self.knowledge_library_service.list_files(user_id=user_id)
        documents: list[_SearchDocument] = []

        def visit(nodes: list[dict[str, Any]]) -> None:
            """递归展开文件树。"""

            for node in nodes:
                path = str(node.get("path") or "").replace("\\", "/").strip("/")
                managed = path == ".mw" or path.startswith(".mw/")
                if not bool(node.get("isDir")) and not managed:
                    documents.append(
                        _SearchDocument(
                            source="files",
                            resource_id=path,
                            title=str(node.get("name") or Path(path).name),
                            content="",
                            locator=path,
                            updated_at=str(node.get("mtime") or ""),
                            item=dict(node),
                            source_path=path,
                        )
                    )
                children = node.get("children")
                if isinstance(children, list) and not managed:
                    visit(children)

        visit(tree)
        return documents

    def _collect_library_documents(self, *, user_id: str) -> list[_SearchDocument]:
        """递归读取图书馆全部层级，并保留可直接渲染的原始卡片数据。"""

        documents: list[_SearchDocument] = []
        pending_parent_ids = [""]
        visited_parent_ids: set[str] = set()
        while pending_parent_ids:
            parent_id = pending_parent_ids.pop()
            if parent_id in visited_parent_ids:
                continue
            visited_parent_ids.add(parent_id)
            payload = self.library_service.list_items(user_id=user_id, parent_id=parent_id)
            for item in payload.get("items") or []:
                serialized = dict(item)
                item_id = str(serialized.get("item_id") or "")
                title = str(serialized.get("display_title") or serialized.get("title") or serialized.get("source_name") or item_id)
                tags = " ".join(str(tag) for tag in (serialized.get("tags") or []))
                content = "\n".join(
                    str(value or "")
                    for value in (
                        serialized.get("description"),
                        tags,
                        serialized.get("source_name"),
                        serialized.get("source_path"),
                        serialized.get("source_url"),
                    )
                    if value
                )
                source_path = str(serialized.get("source_path") or "").replace("\\", "/").strip("/")
                documents.append(
                    _SearchDocument(
                        source="library",
                        resource_id=item_id,
                        title=title,
                        content=content,
                        locator=source_path or str(serialized.get("source_url") or "图书馆"),
                        updated_at=str(serialized.get("updated_at") or ""),
                        item=serialized,
                        source_path=source_path,
                    )
                )
                if serialized.get("item_type") == "collection" and item_id:
                    pending_parent_ids.append(item_id)
        return documents

    def _collect_component_documents(self, *, user_id: str) -> list[_SearchDocument]:
        """读取组件标题、固定分类和完整源码。"""

        payload = self.component_library_service.list_components(user_id=user_id, tag="any")
        documents: list[_SearchDocument] = []
        for item in payload.get("components") or []:
            serialized = dict(item)
            component_id = str(serialized.get("component_id") or "")
            tag = str(serialized.get("tag") or "")
            source = str(serialized.get("source") or "")
            documents.append(
                _SearchDocument(
                    source="components",
                    resource_id=component_id,
                    title=str(serialized.get("title") or Path(component_id).stem),
                    content=f"{tag}\n{source}".strip(),
                    locator=component_id,
                    updated_at=str(serialized.get("updated_at") or ""),
                    item=serialized,
                )
            )
        return documents

    def _collect_literature_documents(self, *, user_id: str, library_id: str) -> list[_SearchDocument]:
        """读取文献行完整文本单元格，同时复用文献卡片摘要 DTO。"""

        entries = self.smart_form_service.list_literature_entries(user_id=user_id, library_id=library_id)
        entries_by_target = {
            (str(entry.get("form_id") or ""), str(entry.get("row_id") or "")): dict(entry)
            for entry in entries
        }
        documents: list[_SearchDocument] = []
        forms = self.smart_form_service.list_forms(user_id=user_id, library_id=library_id, form_kind="literature")
        for form_summary in forms:
            form_id = str(form_summary.get("form_id") or "")
            payload = self.smart_form_service.get_form(user_id=user_id, form_id=form_id) or {}
            form = dict(payload.get("form") or {})
            form_title = str(form.get("title") or form_summary.get("title") or "")
            for row in form.get("rows") or []:
                row_id = str(row.get("id") or "")
                entry = entries_by_target.get((form_id, row_id))
                if entry is None:
                    continue
                cells = dict(row.get("cells") or {})
                values = [self._cell_text(cell) for cell in cells.values()]
                content = "\n".join(value for value in (form_title, *values) if value)
                documents.append(
                    _SearchDocument(
                        source="literature",
                        resource_id=f"{form_id}:{row_id}",
                        title=str(entry.get("title") or entry.get("file_name") or row_id),
                        content=content,
                        locator=str(entry.get("asset_path") or entry.get("file_name") or form_title),
                        updated_at=str(entry.get("updated_at") or ""),
                        item=entry,
                        source_path=str(entry.get("asset_path") or "").replace("\\", "/").strip("/"),
                    )
                )
        return documents

    @staticmethod
    def _cell_text(cell: Any) -> str:
        """把智能表格单元格的持久化值转换为可检索文本。"""

        if isinstance(cell, dict):
            value = cell.get("value")
            if isinstance(value, (str, int, float, bool)):
                return str(value).strip()
        if isinstance(cell, (str, int, float, bool)):
            return str(cell).strip()
        return ""

    def _search_file_fulltext(
        self,
        *,
        user_id: str,
        knowledge_owner_id: str,
        query: str,
        library_root: Path,
    ) -> dict[str, dict[str, Any]]:
        """合并已解析正文索引与可直接读取文本文件的部分匹配。"""

        indexed: list[dict[str, Any]] = []
        for owner_id in dict.fromkeys((knowledge_owner_id, user_id)):
            indexed.extend(
                self.retrieval_service.memory_service.search_knowledge_content(
                    query=query,
                    user_id=owner_id,
                )
            )
        disk = self.knowledge_library_service.search_file_contents(user_id=user_id, query=query)
        matches: dict[str, dict[str, Any]] = {}
        for hit in [*indexed, *disk]:
            relative_path = self._relative_library_path(str(hit.get("source_uri") or ""), library_root)
            if relative_path and relative_path not in matches:
                matches[relative_path] = dict(hit)
        return matches

    def _search_file_semantic(
        self,
        *,
        user_id: str,
        query: str,
        library_root: Path,
    ) -> dict[str, dict[str, Any]]:
        """调用现有知识库向量召回、关键词候选合并和 ReRank 链路。"""

        top_k = int(getattr(self.retrieval_service.config.memory, "rerank_top_k", 20))
        matches: dict[str, dict[str, Any]] = {}
        for hit in self.retrieval_service.retrieve_knowledge(query=query, user_id=user_id, top_k=top_k):
            relative_path = self._relative_library_path(str(hit.memory.source_uri or ""), library_root)
            if not relative_path:
                continue
            current = matches.get(relative_path)
            score = float(hit.final_score)
            if current is None or score > float(current.get("score") or 0.0):
                matches[relative_path] = {"snippet": str(hit.memory.content or ""), "score": score}
        return matches

    @staticmethod
    def _relative_library_path(source_uri: str, library_root: Path) -> str:
        """只接受当前 active library 内的来源路径并转换为相对路径。"""

        if not source_uri:
            return ""
        candidate = Path(source_uri).expanduser()
        if not candidate.is_absolute():
            return candidate.as_posix().strip("/")
        try:
            return candidate.resolve().relative_to(library_root).as_posix()
        except ValueError:
            return ""

    def _sync_semantic_index(
        self,
        *,
        owner_id: str,
        library_id: str,
        selected_sources: set[str],
        documents: list[_SearchDocument],
    ) -> None:
        """按内容哈希增量同步非文件资源，并删除所选来源的陈旧向量。"""

        memory_service = self.retrieval_service.memory_service
        tag = self.retrieval_service.config.constants.knowledge_tag
        existing_source_ids = memory_service.list_source_ids(
            user_id=owner_id,
            tag=tag,
            memory_type=UNIFIED_SEARCH_MEMORY_TYPE,
        )
        current_source_ids = {document.index_source_id for document in documents}
        selected_prefixes = tuple(f"unified:{source}:" for source in selected_sources)
        for source_id in existing_source_ids:
            if source_id.startswith(selected_prefixes) and source_id not in current_source_ids:
                memory_service.delete_memories_for_source(
                    user_id=owner_id,
                    tag=tag,
                    memory_type=UNIFIED_SEARCH_MEMORY_TYPE,
                    source_id=source_id,
                )

        chunk_size = int(getattr(self.retrieval_service.config.memory, "chunk_size", 512))
        chunk_overlap = int(getattr(self.retrieval_service.config.memory, "chunk_overlap", 64))
        embedding_model = str(getattr(self.retrieval_service.config.model, "embedding_model_name", "") or "")
        for document in documents:
            index_text = document.index_text
            if not index_text:
                continue
            source_hash = hashlib.sha256(
                f"{library_id}\0{document.index_source_id}\0{index_text}".encode("utf-8")
            ).hexdigest()
            if memory_service.has_source_hash(
                source_hash=source_hash,
                memory_type=UNIFIED_SEARCH_MEMORY_TYPE,
                user_id=owner_id,
                source_id=document.index_source_id,
            ):
                continue
            chunks = chunk_text(text=index_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            vectors = self.retrieval_service.embedding_service.embed_texts([chunk.content for chunk in chunks])
            memory_service.delete_memories_for_source(
                user_id=owner_id,
                tag=tag,
                memory_type=UNIFIED_SEARCH_MEMORY_TYPE,
                source_id=document.index_source_id,
            )
            for chunk, vector in zip(chunks, vectors, strict=True):
                memory_service.create_memory(
                    LongTermMemorySpecCreate(
                        user_id=owner_id,
                        tag=tag,
                        memory_type=UNIFIED_SEARCH_MEMORY_TYPE,
                        content=chunk.content,
                        source_type=f"{document.source}_search",
                        source_id=document.index_source_id,
                        source_uri=f"metaweave-search://{library_id}/{document.source}/{document.resource_id}",
                        source_hash=source_hash,
                        source_range_json={
                            "chunk_index": chunk.index,
                            "start_char": chunk.start_char,
                            "end_char": chunk.end_char,
                        },
                        metadata_json={
                            "source": document.source,
                            "resource_id": document.resource_id,
                            "library_id": library_id,
                            "title": document.title,
                        },
                        embedding_model=embedding_model or None,
                        embedding_vector_json=vector,
                    )
                )

    def _merge_library_file_hits(
        self,
        *,
        result_map: dict[tuple[str, str], dict[str, Any]],
        documents: list[_SearchDocument],
        file_hits: dict[str, dict[str, Any]],
        mode: str,
    ) -> None:
        """把图书真实文件的正文命中投影回图书馆卡片。"""

        for document in documents:
            if not document.source_path:
                continue
            hit = file_hits.get(document.source_path)
            if hit is None:
                continue
            score = float(hit.get("score") or (0.76 if mode == "fulltext" else 0.0))
            self._merge_hit(
                result_map,
                document,
                mode,
                str(hit.get("snippet") or ""),
                score,
            )

    @staticmethod
    def _serialize_document(document: _SearchDocument) -> dict[str, Any]:
        """共享搜索结果和显式知识 URL 使用的原生卡片 DTO。"""

        return {
            "id": document.resource_id,
            "source": document.source,
            "title": document.title,
            "snippet": "",
            "locator": document.locator,
            "updated_at": document.updated_at,
            "score": 0.0,
            "matched_modes": [],
            "item": document.item,
        }

    @staticmethod
    def _merge_hit(
        result_map: dict[tuple[str, str], dict[str, Any]],
        document: _SearchDocument,
        mode: str,
        snippet: str,
        score: float,
    ) -> None:
        """按来源与稳定 ID 合并标题、全文、语义多路命中。"""

        key = (document.source, document.resource_id)
        result = result_map.setdefault(
            key,
            UnifiedSearchService._serialize_document(document),
        )
        if mode not in result["matched_modes"]:
            result["matched_modes"].append(mode)
            result["matched_modes"].sort(key=SEARCH_MODES.index)
        if snippet and (not result["snippet"] or mode in {"fulltext", "semantic"}):
            result["snippet"] = snippet
        result["score"] = max(float(result["score"]), max(0.0, min(1.0, float(score))))

    @staticmethod
    def _snippet(content: str, position: int, query_length: int) -> str:
        """围绕部分匹配位置生成简短上下文。"""

        start = max(0, position - 80)
        end = min(len(content), position + query_length + 80)
        snippet = content[start:end]
        return f"{'…' if start else ''}{snippet}{'…' if end < len(content) else ''}"
