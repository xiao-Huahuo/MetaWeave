"""
知识库结构化文档入库服务。
功能说明:
本文件负责读取 `frontmatter_bootstrap` 生成的结构化知识 JSON,按章节切块、生成 Embedding,
并以 `tag=Knowledge`、`memory_type=knowledge_chunk` 的统一长期记忆格式写入数据库。它不再
直接解析原始 Markdown/TXT,而是只消费 `runtime/frontmatter` 中的结构化文档。
使用说明:
service = KnowledgeIngestionService(config=config)
result = service.ingest_frontmatter_dir()
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from agent_service.core.agent_config import AgentConfig

logger = logging.getLogger(__name__)
from agent_service.schemas.longterm_memory_spec import LongTermMemorySpecCreate
from agent_service.services.memory.longterm_memory_service import LongTermMemoryService
from agent_service.services.memory.rag.chunk import chunk_text
from agent_service.services.memory.rag.embedding import EmbeddingService
from agent_service.services.memory.rag.frontmatter_document import StructuredKnowledgeDocument


@dataclass(slots=True)
class KnowledgeIngestionResult:
    """
    知识库入库结果。
    files_seen: 扫描到的结构化知识文档数量。
    files_ingested: 实际入库的结构化知识文档数量。
    files_skipped: 因哈希锁跳过的结构化知识文档数量。
    chunks_created: 创建的知识切片数量。
    chunks_deleted: 删除的旧知识切片数量。
    source_ids_seen: 本轮扫描到的结构化文档 ID 集合,用于上层清理已删除文件。
    """

    files_seen: int = 0
    files_ingested: int = 0
    files_skipped: int = 0
    chunks_created: int = 0
    chunks_deleted: int = 0
    source_ids_seen: set[str] | None = None


class KnowledgeIngestionService:
    """
    结构化知识文档入库服务。
    config: 全局配置对象。
    embedding_service: 可选 Embedding 服务,测试时可注入假向量。
    memory_service: 可选长期记忆服务,测试时可注入 SQLite 版本。
    """

    def __init__(
        self,
        *,
        config: AgentConfig,
        embedding_service: EmbeddingService | None = None,
        memory_service: LongTermMemoryService | None = None,
    ) -> None:
        """初始化结构化知识文档入库服务。"""

        self.config = config
        self.embedding_service = embedding_service or EmbeddingService(config=config)
        self.memory_service = memory_service or LongTermMemoryService(config=config)

    def ingest_frontmatter_dir(
        self,
        *,
        frontmatter_dir: Path | None = None,
        user_id: str = "system",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> KnowledgeIngestionResult:
        """
        扫描并入库结构化知识文档目录。
        frontmatter_dir: 可选结构化知识目录;为空时使用全局配置。
        user_id: 知识切片归属用户;默认 system 保持启动灌库兼容。
        返回值描述结构化文档与 chunk 的处理统计。
        """

        source_root = frontmatter_dir or self.config.storage.frontmatter_dir
        result = KnowledgeIngestionResult(source_ids_seen=set())
        frontmatter_files = self._iter_frontmatter_files(source_root)
        logger.info("知识库向量灌库开始 | 扫描到 %d 个结构化文档", len(frontmatter_files))
        total = len(frontmatter_files)
        for frontmatter_path in frontmatter_files:
            result.files_seen += 1
            rel_path = frontmatter_path.relative_to(source_root)
            document = self._load_document(frontmatter_path)
            result.source_ids_seen.add(document.document_id)
            self._emit_progress(
                progress_callback,
                status="started",
                document=document,
                frontmatter_path=frontmatter_path,
                fallback_path=rel_path,
                processed=result.files_seen - 1,
                total=total,
                result=result,
            )
            if self.config.memory.knowledge_hash_lock_enabled and self.memory_service.has_source_hash(
                source_hash=document.ingestion_hash,
                memory_type="knowledge_chunk",
                user_id=user_id,
                source_id=document.document_id,
            ):
                result.files_skipped += 1
                self._emit_progress(
                    progress_callback,
                    status="skipped",
                    document=document,
                    frontmatter_path=frontmatter_path,
                    fallback_path=rel_path,
                    processed=result.files_seen,
                    total=total,
                    result=result,
                    message="source hash unchanged",
                )
                logger.debug("  [跳过] %s (哈希未变更)", rel_path)
                continue
            self.memory_service.delete_memories_for_source(
                user_id=user_id,
                tag=self.config.constants.knowledge_tag,
                memory_type="knowledge_chunk",
                source_id=document.document_id,
            )
            chunks_created = self._ingest_document(
                document=document,
                user_id=user_id,
                progress_callback=progress_callback,
            )
            if chunks_created == 0:
                result.files_skipped += 1
                self._emit_progress(
                    progress_callback,
                    status="skipped",
                    document=document,
                    frontmatter_path=frontmatter_path,
                    fallback_path=rel_path,
                    processed=result.files_seen,
                    total=total,
                    result=result,
                    message="0 chunks",
                )
                logger.warning("  [跳过] %s (0 chunk)", rel_path)
                continue
            result.files_ingested += 1
            result.chunks_created += chunks_created
            self._emit_progress(
                progress_callback,
                status="ingested",
                document=document,
                frontmatter_path=frontmatter_path,
                fallback_path=rel_path,
                processed=result.files_seen,
                total=total,
                result=result,
                chunks_created=chunks_created,
            )
            logger.info("  [入库] %s → %d chunks", document.title, chunks_created)
        logger.info(
            "知识库向量灌库完成 | %d 文档: %d 入库, %d 跳过, 共 %d chunks",
            result.files_seen,
            result.files_ingested,
            result.files_skipped,
            result.chunks_created,
        )
        return result

    def ingest_frontmatter_file(
        self,
        *,
        frontmatter_path: Path,
        user_id: str = "system",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> KnowledgeIngestionResult:
        """
        只入库单个结构化知识文档。仅清理该文档自己的旧 chunk,不影响其他文件。

        frontmatter_path: 单个结构化 JSON 路径。
        user_id: 知识切片归属用户。
        """

        resolved_path = frontmatter_path.expanduser().resolve()
        if not resolved_path.is_file():
            raise ValueError("frontmatter json not found")
        result = KnowledgeIngestionResult(files_seen=1, source_ids_seen=set())
        document = self._load_document(resolved_path)
        result.source_ids_seen.add(document.document_id)
        self._emit_progress(
            progress_callback,
            status="started",
            document=document,
            frontmatter_path=resolved_path,
            fallback_path=resolved_path.name,
            processed=0,
            total=1,
            result=result,
        )
        if self.config.memory.knowledge_hash_lock_enabled and self.memory_service.has_source_hash(
            source_hash=document.ingestion_hash,
            memory_type="knowledge_chunk",
            user_id=user_id,
            source_id=document.document_id,
        ):
            result.files_skipped = 1
            self._emit_progress(
                progress_callback,
                status="skipped",
                document=document,
                frontmatter_path=resolved_path,
                fallback_path=resolved_path.name,
                processed=1,
                total=1,
                result=result,
                message="source hash unchanged",
            )
            logger.debug("  [跳过] %s (哈希未变更)", resolved_path.name)
            return result
        result.chunks_deleted = self.memory_service.delete_memories_for_source(
            user_id=user_id,
            tag=self.config.constants.knowledge_tag,
            memory_type="knowledge_chunk",
            source_id=document.document_id,
        )
        chunks_created = self._ingest_document(
            document=document,
            user_id=user_id,
            progress_callback=progress_callback,
        )
        if chunks_created == 0:
            result.files_skipped = 1
            self._emit_progress(
                progress_callback,
                status="skipped",
                document=document,
                frontmatter_path=resolved_path,
                fallback_path=resolved_path.name,
                processed=1,
                total=1,
                result=result,
                message="0 chunks",
            )
            logger.warning("  [跳过] %s (0 chunk)", resolved_path.name)
            return result
        result.files_ingested = 1
        result.chunks_created = chunks_created
        self._emit_progress(
            progress_callback,
            status="ingested",
            document=document,
            frontmatter_path=resolved_path,
            fallback_path=resolved_path.name,
            processed=1,
            total=1,
            result=result,
            chunks_created=chunks_created,
        )
        logger.info("  [单文件入库] %s → %d chunks", document.title, chunks_created)
        return result

    @staticmethod
    def _emit_progress(
        progress_callback: Callable[[dict[str, Any]], None] | None,
        *,
        status: str,
        document: StructuredKnowledgeDocument,
        frontmatter_path: Path,
        fallback_path: Path | str,
        processed: int,
        total: int,
        result: KnowledgeIngestionResult,
        message: str = "",
        chunks_created: int = 0,
    ) -> None:
        if not progress_callback:
            return
        relative_path = str(document.metadata.get("relative_path") or Path(fallback_path).with_suffix("").as_posix())
        payload: dict[str, Any] = {
            "phase": "ingestion",
            "status": status,
            "path": relative_path.replace("\\", "/"),
            "name": Path(relative_path).name or frontmatter_path.stem,
            "processed": processed,
            "total": total,
            "files_ingested": result.files_ingested,
            "files_skipped": result.files_skipped,
            "chunks_created": result.chunks_created,
        }
        if chunks_created:
            payload["file_chunks_created"] = chunks_created
        if message:
            payload["message"] = message
        progress_callback(payload)

    def _ingest_document(
        self,
        *,
        document: StructuredKnowledgeDocument,
        user_id: str,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> int:
        """
        将单个结构化知识文档切块并写入长期记忆。
        document: 由 frontmatter_bootstrap 生成的结构化知识文档。
        user_id: 知识切片归属用户。
        """

        chunk_rows: list[tuple[Any, Any, str]] = []
        for section in document.sections:
            chunk_inputs = chunk_text(
                text=section.content,
                chunk_size=self.config.memory.chunk_size,
                chunk_overlap=self.config.memory.chunk_overlap,
            )
            if not chunk_inputs:
                continue
            for chunk_input in chunk_inputs:
                chunk_rows.append((
                    section,
                    chunk_input,
                    self._build_chunk_content(
                    document=document,
                    section_heading=section.heading,
                    chunk_text=chunk_input.content,
                    ),
                ))
        total_chunks = len(chunk_rows)
        self._emit_detailed_progress(
            progress_callback,
            document=document,
            stage="split",
            stage_label=f"切片完成，共 {total_chunks} 个切片",
            current=total_chunks,
            total=total_chunks,
            overall_progress=54,
        )
        created = 0
        batch_size = self.config.limits.knowledge_ingestion_batch_size
        total_batches = max(1, (total_chunks + batch_size - 1) // batch_size)
        for batch_index, batch_start in enumerate(range(0, total_chunks, batch_size), start=1):
            batch = chunk_rows[batch_start:batch_start + batch_size]
            logger.debug("    Embedding batch %d/%d (%d chunks)...", batch_index, total_batches, len(batch))
            vectors = self.embedding_service.embed_texts([row[2] for row in batch])
            for (section, chunk_input, chunk_content), vector in zip(batch, vectors, strict=True):
                self.memory_service.create_memory(
                    LongTermMemorySpecCreate(
                        user_id=user_id,
                        session_id=None,
                        tag=self.config.constants.knowledge_tag,
                        memory_type="knowledge_chunk",
                        content=chunk_content,
                        source_type=document.source_type,
                        source_id=document.document_id,
                        source_uri=document.source_uri,
                        source_hash=document.ingestion_hash,
                        source_range_json={
                            "section_id": section.section_id,
                            "chunk_index": chunk_input.index,
                            "section_start_char": section.start_char,
                            "section_end_char": section.end_char,
                            "chunk_start_char": chunk_input.start_char,
                            "chunk_end_char": chunk_input.end_char,
                        },
                        metadata_json={
                            "source_hash": document.source_hash,
                            "projection_hash": document.projection_hash,
                            "title": document.title,
                            "summary": document.summary,
                            "tags": document.tags,
                            "section_heading": section.heading,
                            "title_path": section.title_path,
                            **document.metadata,
                        },
                        valid_from=self._parse_optional_datetime(document.valid_from),
                        valid_until=self._parse_optional_datetime(document.valid_until),
                        confidence=1.0,
                        importance=0.5,
                        authority=document.authority,
                        embedding_model=self.config.model.embedding_model_name,
                        embedding_vector_json=vector,
                    )
                )
                created += 1
            self._emit_detailed_progress(
                progress_callback,
                document=document,
                stage="embedding",
                stage_label=f"正在写入向量批次 {batch_index} / {total_batches}",
                current=batch_index,
                total=total_batches,
                overall_progress=round(54 + (batch_index / total_batches) * 42, 1),
                message=f"已写入 {created} / {total_chunks} 个切片",
            )
        return created

    @staticmethod
    def _emit_detailed_progress(
        progress_callback: Callable[[dict[str, Any]], None] | None,
        *,
        document: StructuredKnowledgeDocument,
        stage: str,
        stage_label: str,
        current: int,
        total: int,
        overall_progress: float,
        message: str = "",
    ) -> None:
        """发送切片和分批向量写入的真实工作单位。"""

        if not progress_callback:
            return
        relative_path = str(document.metadata.get("relative_path") or document.source_uri)
        progress_callback({
            "phase": "ingestion",
            "status": "processing",
            "path": relative_path.replace("\\", "/"),
            "name": Path(relative_path).name,
            "stage": stage,
            "stage_label": stage_label,
            "stage_current": current,
            "stage_total": total,
            "overall_progress": overall_progress,
            "message": message,
        })

    @staticmethod
    def _build_chunk_content(
        *,
        document: StructuredKnowledgeDocument,
        section_heading: str,
        chunk_text: str,
    ) -> str:
        """
        组合真正参与检索和入库的知识片文本。
        document: 结构化知识文档。
        section_heading: 当前章节标题。
        chunk_text: 当前 chunk 正文。
        """

        title_line = f"文档标题: {document.title}"
        section_line = f"章节标题: {section_heading}"
        return f"{title_line}\n{section_line}\n\n{chunk_text}".strip()

    @staticmethod
    def _parse_optional_datetime(value: str | None) -> datetime | None:
        """
        解析 frontmatter 中的 ISO 时间字符串。
        value: 结构化知识文档中的时间字符串。
        """

        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)

    @staticmethod
    def _load_document(frontmatter_path: Path) -> StructuredKnowledgeDocument:
        """
        从结构化知识 JSON 文件加载统一文档对象。
        frontmatter_path: 结构化知识 JSON 文件路径。
        """

        payload = json.loads(frontmatter_path.read_text(encoding="utf-8"))
        return StructuredKnowledgeDocument.from_dict(payload)

    def _iter_frontmatter_files(self, frontmatter_dir: Path) -> list[Path]:
        """
        扫描可入库的结构化知识 JSON。
        frontmatter_dir: 结构化知识文档根目录。
        """

        if not frontmatter_dir.exists():
            return []
        source_root = frontmatter_dir.resolve()
        return sorted(
            path
            for path in source_root.rglob("*.json")
            if path.is_file() and not self._is_user_frontmatter_under_global_root(path=path, source_root=source_root)
        )

    def _is_user_frontmatter_under_global_root(self, *, path: Path, source_root: Path) -> bool:
        """
        全局启动灌库时跳过用户隔离 frontmatter。

        `config.storage.frontmatter_dir` 是全局结构化目录,其 `users/<user>/<kb>/...`
        子树由 editor 用户知识库灌库产生。启动灌库只应消费全局知识源 JSON,不能把用户
        frontmatter 输出再次作为全局输入,否则会导致重复扫描和哈希锁误判。
        当调用方显式传入 `frontmatter/users/<user>/<kb>` 作为 source_root 时,这里不会跳过。
        """

        global_root = self.config.storage.frontmatter_dir.resolve()
        if source_root != global_root:
            return False
        try:
            relative_parts = path.resolve().relative_to(global_root).parts
        except ValueError:
            return False
        return bool(relative_parts) and relative_parts[0] == "users"
