"""Session attachment upload, parsing, and context injection service."""

from __future__ import annotations

import json
import hashlib
import logging
import mimetypes
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

import agent_service.models  # noqa: F401
from agent_service.core.agent_config import AgentConfig
from agent_service.core.db.engine import get_database_engine
from agent_service.models.attachment import SessionAttachmentRecord
from agent_service.services.memory.rag.frontmatter_bootstrap import FrontmatterBootstrapService
from agent_service.services.memory.rag.frontmatter_document import StructuredKnowledgeDocument
from agent_service.services.settings.service import SettingsService

logger = logging.getLogger(__name__)

AttachmentProgressCallback = Callable[[str, int], None]


@dataclass(slots=True)
class AttachmentContext:
    """Prepared context text and citation metadata for session attachments."""

    content: str
    citation_map: dict[str, dict[str, str]]
    attachment_count: int
    injected_count: int


@dataclass(slots=True)
class AttachmentParseFlight:
    """协调同一附件的一次在途解析；事件等待不持有注册表锁。"""

    completed: threading.Event
    error: Exception | None = None


class SessionAttachmentService:
    """Manage uploaded files that are available to the current Agent session only."""

    REFERENCE_HINT_PATTERN = re.compile(
        r"(\u9644\u4ef6|\u4e0a\u4f20|\u4e0a\u50b3|\u6587\u4ef6|\u6587\u6863|\u6587\u6a94|\u8fd9\u4e2a|\u9019\u500b|\u8fd9\u4e9b|\u9019\u4e9b|\u521a\u624d|\u525b\u624d|\u521a\u521a|\u525b\u525b|"
        r"attachment|attachments|uploaded|upload|file|files|document|documents)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        config: AgentConfig,
        settings_service: SettingsService,
        engine: Engine | None = None,
        create_tables: bool = True,
    ) -> None:
        """保存依赖并建立按附件隔离的解析锁注册表。"""

        self.config = config
        self.settings_service = settings_service
        self.engine = engine or get_database_engine(config)
        self._parse_flights_guard = threading.Lock()
        self._parse_flights: dict[str, AttachmentParseFlight] = {}

    def upload_file(
        self,
        *,
        user_id: str,
        session_id: str,
        filename: str,
        content: bytes,
        mime_type: str = "",
    ) -> dict[str, object]:
        """只保存原文件与附件记录；解析由 Agent 的读取工具按需触发。"""

        normalized_user_id = user_id.strip()
        normalized_session_id = session_id.strip()
        safe_filename = Path(filename).name.strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        if not normalized_session_id:
            raise ValueError("session_id is required")
        if not safe_filename:
            raise ValueError("filename is required")

        active_library = self.settings_service.get_active_knowledge_library(user_id=normalized_user_id)
        library_id = str(active_library["library_id"])
        library_name = str(active_library.get("name") or library_id)
        upload_dir = self._upload_dir(
            user_id=normalized_user_id,
            library=library_id,
            session_id=normalized_session_id,
        )
        upload_dir.mkdir(parents=True, exist_ok=True)
        target_path = self._write_unique_upload(
            target_dir=upload_dir,
            preferred_name=safe_filename,
            content=content,
        )

        attachment_id = f"att_{uuid4().hex}"
        record = SessionAttachmentRecord(
            attachment_id=attachment_id,
            user_id=normalized_user_id,
            session_id=normalized_session_id,
            library_id=library_id,
            library_name=library_name,
            filename=safe_filename,
            stored_name=target_path.name,
            path=str(target_path),
            text_path="",
            uri=self._attachment_uri(
                user_id=normalized_user_id,
                library=library_id,
                session_id=normalized_session_id,
                filename=target_path.name,
            ),
            mime_type=mime_type or mimetypes.guess_type(target_path.name)[0] or "",
            size=len(content),
            source_type="attachment",
            summary="",
            metadata_json={
                "processing_status": "uploaded",
                "processing_stage": "uploaded",
                "processing_progress": 100,
                "content_status": "unparsed",
            },
        )
        try:
            with Session(self.engine) as db_session:
                db_session.add(record)
                db_session.commit()
                db_session.refresh(record)
        except Exception:
            target_path.unlink(missing_ok=True)
            raise
        return self._record_to_dict(record)

    def get_attachment(self, *, user_id: str, session_id: str, attachment_id: str) -> dict[str, object]:
        """返回当前用户会话中一个附件的最新解析状态 DTO。"""

        with Session(self.engine) as db_session:
            record = db_session.get(SessionAttachmentRecord, attachment_id.strip())
            if record is None or record.user_id != user_id.strip() or record.session_id != session_id.strip():
                raise ValueError("attachment not found")
            return self._record_to_dict(record)

    def get_attachment_file_by_uri(self, *, uri: str) -> tuple[Path, str, str]:
        """按完整 session-upload URI 精确解析附件文件，禁止 basename 模糊匹配。"""

        normalized_uri = uri.strip()
        if not normalized_uri.startswith("session-upload://"):
            raise ValueError("invalid attachment uri")
        with Session(self.engine) as db_session:
            record = db_session.exec(
                select(SessionAttachmentRecord).where(SessionAttachmentRecord.uri == normalized_uri)
            ).first()
        if record is None:
            raise ValueError("attachment not found")
        path = Path(record.path).expanduser().resolve()
        uploads_root = (self.config.storage.base_data_dir / "uploads").resolve()
        try:
            path.relative_to(uploads_root)
        except ValueError as exc:
            raise ValueError("attachment path escaped upload root") from exc
        if not path.is_file():
            raise ValueError("attachment file not found")
        return path, record.mime_type, record.filename

    def read_attachment_text(
        self,
        *,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> tuple[SessionAttachmentRecord, str]:
        """首次读取时解析一个会话附件，后续读取直接复用已持久化文本。"""

        normalized_attachment_id = attachment_id.strip()
        record = self._require_session_attachment(
            user_id=user_id,
            session_id=session_id,
            attachment_id=normalized_attachment_id,
        )
        cached_text = self._read_cached_attachment_text(record.text_path)
        if cached_text is not None:
            return record, cached_text

        with self._parse_flights_guard:
            flight = self._parse_flights.get(normalized_attachment_id)
            is_owner = flight is None
            if flight is None:
                flight = AttachmentParseFlight(completed=threading.Event())
                self._parse_flights[normalized_attachment_id] = flight
        if not is_owner:
            wait_seconds = max(float(self.config.limits.knowledge_file_wait_timeout_seconds), 0.001)
            if not flight.completed.wait(timeout=wait_seconds):
                raise TimeoutError("附件正在由另一个工具调用解析，请稍后重试。")
            if flight.error is not None:
                raise RuntimeError("附件解析失败，请重试或检查文件格式。") from flight.error
            completed = self._require_session_attachment(
                user_id=user_id,
                session_id=session_id,
                attachment_id=normalized_attachment_id,
            )
            return completed, self._read_cached_attachment_text(completed.text_path) or ""

        try:
            record = self._require_session_attachment(
                user_id=user_id,
                session_id=session_id,
                attachment_id=normalized_attachment_id,
            )
            cached_text = self._read_cached_attachment_text(record.text_path)
            if cached_text is not None:
                return record, cached_text

            source_path = Path(record.path).expanduser().resolve()
            if not source_path.is_file():
                raise FileNotFoundError(f"附件原文件不存在: {record.filename}")
            self._update_processing_status(
                attachment_id=normalized_attachment_id,
                status="processing",
                stage="parsing",
                progress=10,
            )
            try:
                text_path, document = self._parse_to_attachment_text(
                    attachment_id=normalized_attachment_id,
                    source_path=source_path,
                    upload_dir=source_path.parent,
                    user_id=user_id,
                    progress_callback=lambda stage, progress: self._update_processing_status(
                        attachment_id=normalized_attachment_id,
                        status="processing",
                        stage=stage,
                        progress=progress,
                    ),
                )
                self._complete_processing(
                    attachment_id=normalized_attachment_id,
                    text_path=text_path,
                    document=document,
                )
            except Exception as exc:  # noqa: BLE001
                flight.error = exc
                logger.exception("附件按需解析失败 | attachment=%s", normalized_attachment_id)
                self._update_processing_status(
                    attachment_id=normalized_attachment_id,
                    status="failed",
                    stage="failed",
                    progress=100,
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise
            completed = self._require_session_attachment(
                user_id=user_id,
                session_id=session_id,
                attachment_id=normalized_attachment_id,
            )
            return completed, self._read_cached_attachment_text(completed.text_path) or ""
        finally:
            flight.completed.set()
            with self._parse_flights_guard:
                if self._parse_flights.get(normalized_attachment_id) is flight:
                    self._parse_flights.pop(normalized_attachment_id, None)

    def _require_session_attachment(
        self,
        *,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> SessionAttachmentRecord:
        """读取并校验一个附件确实属于当前用户与会话。"""

        with Session(self.engine) as db_session:
            record = db_session.get(SessionAttachmentRecord, attachment_id)
            if record is None or record.user_id != user_id.strip() or record.session_id != session_id.strip():
                raise ValueError("attachment not found")
            db_session.expunge(record)
            return record

    def _update_processing_status(
        self,
        *,
        attachment_id: str,
        status: str,
        stage: str,
        progress: int,
        error: str = "",
    ) -> None:
        """原子更新一个附件的解析状态，不覆盖其他元数据。"""

        with Session(self.engine) as db_session:
            record = db_session.get(SessionAttachmentRecord, attachment_id)
            if record is None:
                return
            metadata = dict(record.metadata_json or {})
            metadata.update({
                "processing_status": status,
                "processing_stage": stage,
                "processing_progress": max(0, min(100, int(progress))),
            })
            if error:
                metadata["processing_error"] = error
            record.metadata_json = metadata
            db_session.add(record)
            db_session.commit()

    def _complete_processing(
        self,
        *,
        attachment_id: str,
        text_path: Path,
        document: StructuredKnowledgeDocument,
    ) -> None:
        """保存解析产物并发布 completed 终态。"""

        with Session(self.engine) as db_session:
            record = db_session.get(SessionAttachmentRecord, attachment_id)
            if record is None:
                return
            record.text_path = str(text_path)
            record.source_type = document.source_type
            record.summary = document.summary
            record.metadata_json = {
                "title": document.title,
                "source_hash": document.source_hash,
                "section_count": len(document.sections),
                "parser": "FrontmatterBootstrapService",
                "multimodal_metadata": document.metadata,
                "processing_status": "completed",
                "processing_stage": "completed",
                "processing_progress": 100,
                "content_status": "parsed",
            }
            db_session.add(record)
            db_session.commit()

    def list_session_attachments(self, *, user_id: str, session_id: str) -> list[SessionAttachmentRecord]:
        """Return attachments for a user session in upload order."""

        statement = (
            select(SessionAttachmentRecord)
            .where(SessionAttachmentRecord.user_id == user_id)
            .where(SessionAttachmentRecord.session_id == session_id)
            .order_by(SessionAttachmentRecord.created_at.asc())
        )
        with Session(self.engine) as db_session:
            return list(db_session.exec(statement).all())

    def delete_attachment(self, *, user_id: str, session_id: str, attachment_id: str) -> bool:
        """Delete one session attachment record and its runtime files."""

        normalized_user_id = user_id.strip()
        normalized_session_id = session_id.strip()
        normalized_attachment_id = attachment_id.strip()
        if not normalized_user_id or not normalized_session_id or not normalized_attachment_id:
            raise ValueError("user_id, session_id and attachment_id are required")
        with Session(self.engine) as db_session:
            record = db_session.get(SessionAttachmentRecord, normalized_attachment_id)
            if record is None:
                return False
            if record.user_id != normalized_user_id or record.session_id != normalized_session_id:
                return False
            self._delete_runtime_file(record.path)
            self._delete_runtime_file(record.text_path)
            db_session.delete(record)
            db_session.commit()
            return True

    def build_context(
        self,
        *,
        user_id: str,
        session_id: str,
        current_prompt: str,
        max_total_chars: int | None = None,
        max_attachment_chars: int | None = None,
    ) -> AttachmentContext:
        """Build session attachment catalog and relevant content snippets for the model."""

        # 兼容旧调用参数，但模型可见容量统一由最终 ContextBuilder token 预算裁决。
        del max_total_chars, max_attachment_chars
        attachments = self.list_session_attachments(user_id=user_id, session_id=session_id)
        if not attachments:
            return AttachmentContext(content="", citation_map={}, attachment_count=0, injected_count=0)

        selected = [
            item
            for item in self._select_relevant_attachments(attachments=attachments, current_prompt=current_prompt)
            if self._read_text_preview(item.text_path, None)
        ]
        citation_map: dict[str, dict[str, str]] = {}
        lines = [
            "--- Session Uploaded Attachments Start ---",
            "The user uploaded these files directly into this session. They are NOT knowledge-base files and must not be ingested.",
            "Use read_file with an attachment:// reference when the file content is needed. Use understand_image for visual meaning.",
            "Attachment catalog:",
        ]
        selected_ids = {item.attachment_id for item in selected}
        for index, item in enumerate(attachments, 1):
            marker = " (content injected below)" if item.attachment_id in selected_ids else ""
            lines.append(
                f"- [A{index}] {item.filename} | {item.size} bytes | {item.source_type} | "
                f"attachment://{item.attachment_id}{marker}"
            )
            citation_map[f"A{index}"] = {
                "source_uri": item.uri or item.path,
                "content": item.summary or self._read_text_preview(item.text_path, None),
                "title": item.filename,
                "source": "session_attachment",
                "adopted_by_default": True,
            }

        injected_count = 0
        if selected:
            lines.append("Relevant attachment content:")
        for item in selected:
            attachment_index = attachments.index(item) + 1
            text = self._read_text_preview(item.text_path, None)
            if not text:
                continue
            block = (
                f"### [A{attachment_index}] {item.filename}\n"
                f"Content ref: attachment://{item.attachment_id}\n{text}"
            )
            lines.append(block)
            injected_count += 1
        lines.append("--- Session Uploaded Attachments End ---")
        return AttachmentContext(
            content="\n".join(lines),
            citation_map=citation_map,
            attachment_count=len(attachments),
            injected_count=injected_count,
        )

    def _parse_to_attachment_text(
        self,
        *,
        attachment_id: str,
        source_path: Path,
        upload_dir: Path,
        user_id: str,
        progress_callback: AttachmentProgressCallback | None = None,
    ) -> tuple[Path, StructuredKnowledgeDocument]:
        """解析附件为文本，并按真实处理里程碑报告当前文件进度。"""

        report = progress_callback or (lambda _stage, _progress: None)
        suffixes = set(self.config.constants.knowledge_supported_suffixes)
        frontmatter_dir = upload_dir / ".attachments" / "frontmatter"
        text_dir = upload_dir / ".attachments" / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        is_direct_image = source_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        ocr_enabled = is_direct_image or self.settings_service.is_ocr_enabled_for_user(user_id=user_id)
        vlm_config = self.settings_service.get_vlm_config(user_id=user_id)
        report("ocr" if is_direct_image else "parsing", 30)
        try:
            _, frontmatter_path = FrontmatterBootstrapService(
                config=self.config,
                ocr_enabled=ocr_enabled,
                vlm_config=vlm_config,
                online_enabled=bool(vlm_config.get("enabled")),
            ).build_frontmatter_file(
                source_path=source_path,
                knowledge_dir=upload_dir,
                frontmatter_dir=frontmatter_dir,
                supported_suffixes=suffixes,
            )
            payload = json.loads(frontmatter_path.read_text(encoding="utf-8"))
            document = StructuredKnowledgeDocument.from_dict(payload)
        except ValueError:
            document = self._build_fallback_document(source_path=source_path, upload_dir=upload_dir)
        report("text_ready", 70)
        report("finalizing", 95)
        text_path = text_dir / f"{attachment_id}.txt"
        text_path.write_text(self._document_to_text(document), encoding="utf-8")
        return text_path, document

    def _build_fallback_document(self, *, source_path: Path, upload_dir: Path) -> StructuredKnowledgeDocument:
        """Build a lightweight attachment document for unsupported suffixes."""

        raw_bytes = source_path.read_bytes()
        source_hash = hashlib.sha256(raw_bytes).hexdigest()
        try:
            body = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            body = source_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            body = f"Binary or unsupported file: {source_path.name}"
        if not body.strip():
            body = f"Empty or unsupported file: {source_path.name}"
        relative_path = source_path.relative_to(upload_dir).as_posix()
        return StructuredKnowledgeDocument(
            document_id=hashlib.sha1(relative_path.encode("utf-8")).hexdigest(),
            source_type="attachment",
            source_path=str(source_path),
            source_uri=str(source_path),
            source_hash=source_hash,
            title=source_path.name,
            summary="",
            tags=[],
            authority=0.5,
            valid_from=None,
            valid_until=None,
            metadata={
                "file_suffix": source_path.suffix.lower(),
                "relative_path": relative_path,
                "modality": "unsupported",
            },
            sections=[
                StructuredKnowledgeSection(
                    section_id="fallback",
                    heading=source_path.name,
                    title_path=[source_path.name],
                    content=body,
                    start_char=0,
                    end_char=len(body),
                )
            ],
        )

    @staticmethod
    def _document_to_text(document: StructuredKnowledgeDocument) -> str:
        lines = [f"# {document.title}".strip()]
        if document.summary:
            lines.extend(["", document.summary.strip()])
        for section in document.sections:
            title_path = " / ".join(section.title_path) or section.heading
            content = section.content.strip()
            if not content:
                continue
            lines.extend(["", f"## {title_path}", content])
        return "\n".join(lines).strip()

    def _select_relevant_attachments(
        self,
        *,
        attachments: list[SessionAttachmentRecord],
        current_prompt: str,
    ) -> list[SessionAttachmentRecord]:
        prompt = current_prompt.casefold()
        selected = [
            item
            for item in attachments
            if item.filename.casefold() in prompt or Path(item.filename).stem.casefold() in prompt
        ]
        if selected:
            return selected
        if self.REFERENCE_HINT_PATTERN.search(current_prompt):
            return attachments
        if len(attachments) == 1:
            return attachments
        return []

    def _attachment_uri(self, *, user_id: str, library: str, session_id: str, filename: str) -> str:
        return (
            "session-upload://"
            f"{self._safe_component(user_id)}/{self._safe_component(library)}/"
            f"{self._safe_component(session_id)}/{filename}"
        )

    def _upload_dir(self, *, user_id: str, library: str, session_id: str) -> Path:
        return (
            self.config.storage.base_data_dir
            / "uploads"
            / self._safe_component(user_id)
            / self._safe_component(library)
            / self._safe_component(session_id)
        )

    @staticmethod
    def _safe_component(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "default"

    def _write_unique_upload(self, *, target_dir: Path, preferred_name: str, content: bytes) -> Path:
        """用独占创建原子分配文件名，保证并行同名上传不会互相覆盖。"""

        safe_name = Path(preferred_name).name.strip() or "untitled"
        first_path = (target_dir / safe_name).resolve()
        stem = first_path.stem
        suffix = first_path.suffix
        for index in range(self.config.limits.attachment_name_collision_attempts):
            candidate = first_path if index == 0 else (target_dir / f"{stem} ({index}){suffix}").resolve()
            try:
                with candidate.open("xb") as handle:
                    handle.write(content)
                return candidate
            except FileExistsError:
                continue
        fallback = (target_dir / f"{stem}-{uuid4().hex}{suffix}").resolve()
        with fallback.open("xb") as handle:
            handle.write(content)
        return fallback

    @staticmethod
    def _read_cached_attachment_text(text_path: str) -> str | None:
        """区分“尚未解析”和“已解析但正文为空”，避免空结果被重复解析。"""

        if not text_path:
            return None
        path = Path(text_path)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace").strip()

    @staticmethod
    def _read_text_preview(text_path: str, limit: int | None) -> str:
        if not text_path:
            return ""
        path = Path(text_path)
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if limit is None or len(text) <= limit:
            return text
        return text[:limit].rstrip() + "\n...(已截断)"

    def _delete_runtime_file(self, path_value: str) -> None:
        if not path_value:
            return
        path = Path(path_value).expanduser().resolve()
        uploads_root = (self.config.storage.base_data_dir / "uploads").resolve()
        try:
            path.relative_to(uploads_root)
        except ValueError:
            return
        if path.is_file():
            path.unlink(missing_ok=True)

    @staticmethod
    def _record_to_dict(record: SessionAttachmentRecord) -> dict[str, object]:
        return {
            "attachment_id": record.attachment_id,
            "user_id": record.user_id,
            "session_id": record.session_id,
            "library_id": record.library_id,
            "library_name": record.library_name,
            "filename": record.filename,
            "stored_name": record.stored_name,
            "uri": record.uri,
            "mime_type": record.mime_type,
            "size": record.size,
            "source_type": record.source_type,
            "summary": record.summary,
            "metadata": record.metadata_json,
            "created_at": record.created_at.isoformat(),
        }
