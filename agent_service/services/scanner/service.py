"""Persistent scanner task, projection, and export service.

The service owns its bounded executor, stores originals below the active
library's ``.mw/scan`` directory, reuses the ingestion Markdown projection
stage, and persists user-editable drafts in SQLite.
"""

from __future__ import annotations

import io
import ipaddress
import json
import logging
import mimetypes
import re
import shutil
import socket
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import requests
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from agent_service.core.agent_config import AgentConfig
from agent_service.models.scanner import ScannerRecord
from agent_service.models.favorite import FavoriteRecord
from agent_service.schemas.scanner import ScannerConflictStrategy, ScannerOut, ScannerVariant
from agent_service.services.knowledge_library import KnowledgeLibraryService
from agent_service.services.memory.rag.frontmatter_bootstrap import FrontmatterBootstrapService
from agent_service.services.memory.rag.image_ocr import ImageOcrService
from agent_service.services.settings.service import SettingsService

logger = logging.getLogger(__name__)

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".json", ".jsonl", ".csv", ".tsv", ".html", ".htm", ".xml", ".tex", ".py", ".js", ".ts", ".css", ".yaml", ".yml"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
IMAGE_MARKDOWN_RE = re.compile(r"!\[[^\]]*\]\([^\n)]*\)")


class _HtmlMarkdownParser(HTMLParser):
    """Convert the readable structural subset of HTML into Markdown."""

    def __init__(self) -> None:
        """Initialize block, link, image, and page-title state."""

        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.images: list[tuple[str, str]] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._title_depth = 0
        self._link_href = ""
        self._pre_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open Markdown blocks and retain link/image metadata."""

        name = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if name in {"script", "style", "noscript", "template"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if name == "title":
            self._title_depth += 1
        elif name in {"p", "div", "section", "article", "header", "footer", "table", "tr", "blockquote"}:
            self.parts.append("\n\n")
        elif re.fullmatch(r"h[1-6]", name):
            self.parts.append(f"\n\n{'#' * int(name[1])} ")
        elif name == "li":
            self.parts.append("\n- ")
        elif name == "br":
            self.parts.append("\n")
        elif name == "a":
            self._link_href = values.get("href", "").strip()
            if self._link_href:
                self.parts.append("[")
        elif name == "pre":
            self._pre_depth += 1
            self.parts.append("\n\n```\n")
        elif name == "code" and not self._pre_depth:
            self.parts.append("`")
        elif name == "img" and values.get("src"):
            alt = values.get("alt", "").strip() or "image"
            src = values["src"].strip()
            self.images.append((src, alt))
            self.parts.append(f"\n\n![{alt}]({src})\n\n")

    def handle_endtag(self, tag: str) -> None:
        """Close Markdown links, code spans, and fenced blocks."""

        name = tag.lower()
        if name in {"script", "style", "noscript", "template"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if name == "title":
            self._title_depth = max(0, self._title_depth - 1)
        elif name == "a" and self._link_href:
            self.parts.append(f"]({self._link_href})")
            self._link_href = ""
        elif name == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)
            self.parts.append("\n```\n")
        elif name == "code" and not self._pre_depth:
            self.parts.append("`")

    def handle_data(self, data: str) -> None:
        """Append visible text while preserving preformatted whitespace."""

        if self._skip_depth or not data:
            return
        if self._title_depth:
            self.title_parts.append(data.strip())
            return
        self.parts.append(data if self._pre_depth else re.sub(r"\s+", " ", data))

    def markdown(self) -> str:
        """Return normalized Markdown without excessive blank lines."""

        value = "".join(self.parts).replace(" \n", "\n")
        return re.sub(r"\n{3,}", "\n\n", value).strip()

    def title(self) -> str:
        """Return the HTML title accumulated from visible title text."""

        return " ".join(part for part in self.title_parts if part).strip()


class ScannerService:
    """Own scanner persistence, one bounded worker pool, and managed artifacts."""

    def __init__(
        self,
        *,
        engine: Engine,
        config: AgentConfig,
        settings_service: SettingsService,
        knowledge_library_service: KnowledgeLibraryService,
    ) -> None:
        """Bind shared application services and recover interrupted records."""

        self.engine = engine
        self.config = config
        self.settings_service = settings_service
        self.knowledge_library_service = knowledge_library_service
        self._executor = ThreadPoolExecutor(max_workers=config.limits.scanner_worker_count, thread_name_prefix="scanner")
        self._lock = Lock()
        self._closed = False
        self._fail_interrupted_records()

    def stop(self) -> None:
        """Reject new tasks and release the scanner-owned worker pool."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)

    def create_file(self, *, user_id: str, filename: str, content: bytes, ocr_enabled: bool, source_kind: str = "file") -> ScannerOut:
        """Persist one managed source copy and enqueue its Markdown projection."""

        normalized_user = self._required(user_id, "user_id")
        safe_name = Path(filename).name.strip()
        if not safe_name:
            raise ValueError("filename is required")
        if len(content) > self.config.limits.scanner_source_max_bytes:
            raise ValueError("file exceeds scanner size limit")
        context = self._context(normalized_user)
        scan_id = f"scan_{uuid4().hex}"
        scan_root = self._scan_root(context=context, scan_id=scan_id)
        source_path = scan_root / "source" / safe_name
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(content)
        relative_path = source_path.relative_to(context["root"]).as_posix()
        record = ScannerRecord(
            scan_id=scan_id,
            user_id=context["user_id"],
            library_id=context["library_id"],
            source_kind=source_kind,
            source_name=safe_name,
            source_path=relative_path,
            size=len(content),
            ocr_enabled=ocr_enabled,
        )
        with Session(self.engine) as db:
            db.add(record)
            db.commit()
            db.refresh(record)
        self._submit(scan_id)
        return self._to_out(record, context=context, include_content=False)

    def create_url(self, *, user_id: str, url: str, ocr_enabled: bool) -> ScannerOut:
        """Persist a queued public webpage task and enqueue crawling."""

        normalized_user = self._required(user_id, "user_id")
        self._validate_public_url(url)
        context = self._context(normalized_user)
        scan_id = f"scan_{uuid4().hex}"
        source_name = (urlparse(url).hostname or "webpage") + ".html"
        record = ScannerRecord(
            scan_id=scan_id,
            user_id=context["user_id"],
            library_id=context["library_id"],
            source_kind="url",
            source_name=source_name,
            source_url=url,
            ocr_enabled=ocr_enabled,
        )
        with Session(self.engine) as db:
            db.add(record)
            db.commit()
            db.refresh(record)
        self._submit(scan_id)
        return self._to_out(record, context=context)

    def list_scans(self, *, user_id: str) -> list[ScannerOut]:
        """List current-library scanner records newest first."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            records = db.exec(
                select(ScannerRecord)
                .where(ScannerRecord.user_id == context["user_id"])
                .where(ScannerRecord.library_id == context["library_id"])
                .order_by(ScannerRecord.created_at.desc())
            ).all()
            return [self._to_out(record, context=context, include_content=False) for record in records]

    def get_scan(self, *, user_id: str, scan_id: str) -> ScannerOut:
        """Return one scanner record within the current user and library scope."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            return self._to_out(record, context=context)

    def update_draft(self, *, user_id: str, scan_id: str, variant: ScannerVariant, content: str) -> ScannerOut:
        """Persist one editable scanner Markdown variant in SQLite."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            if variant == "ocr":
                if not record.ocr_enabled:
                    raise ValueError("OCR variant is unavailable for this scan")
                record.ocr_markdown = content
            else:
                record.no_ocr_markdown = content
            record.updated_at = self._now()
            db.add(record)
            db.commit()
            db.refresh(record)
            return self._to_out(record, context=context)

    def update_source_text(self, *, user_id: str, scan_id: str, content: str) -> ScannerOut:
        """Write UTF-8 text into a managed text source without reparsing drafts."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            source = self._source_absolute(record=record, context=context)
            if source.suffix.lower() not in TEXT_SUFFIXES:
                raise ValueError("source is not an editable text file")
            source.write_text(content, encoding="utf-8")
            record.size = source.stat().st_size
            record.updated_at = self._now()
            db.add(record)
            db.commit()
            db.refresh(record)
            return self._to_out(record, context=context)

    def delete_scan(self, *, user_id: str, scan_id: str) -> bool:
        """Delete a terminal history record and its isolated managed directory."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            if record.status in {"queued", "running"}:
                raise ValueError("cannot delete a running scan")
            scan_root = self._scan_root(context=context, scan_id=scan_id)
            favorite = db.exec(
                select(FavoriteRecord)
                .where(FavoriteRecord.user_id == context["user_id"])
                .where(FavoriteRecord.library_id == context["library_id"])
                .where(FavoriteRecord.target_type == "scanner")
                .where(FavoriteRecord.target_id == scan_id)
            ).first()
            if favorite is not None:
                db.delete(favorite)
            db.delete(record)
            db.commit()
        if scan_root.is_dir():
            shutil.rmtree(scan_root)
        return True

    def save_to_knowledge(
        self,
        *,
        user_id: str,
        scan_id: str,
        variant: ScannerVariant,
        conflict_strategy: ScannerConflictStrategy,
    ) -> dict[str, Any]:
        """Write a chosen projection and its referenced assets into the knowledge root."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            markdown = self._variant_content(record, variant)
            filename = f"{Path(record.source_name).stem}.md"
            assets = self._asset_paths(record=record, context=context) if variant == "no_ocr" else []
        existing_target = context["root"] / filename
        if conflict_strategy == "skip" and existing_target.exists():
            return {"ok": True, "path": filename, "assets": [], "skipped": True}
        profile = self.settings_service.ensure_user_profile(user_id=context["user_id"])
        asset_dir = self._normalized_asset_dir(str(profile.get("editor_image_assets_dir") or "./assets/"))
        markdown, copied_assets = self._copy_assets_to_knowledge(
            markdown=markdown,
            assets=assets,
            root=context["root"],
            asset_dir=asset_dir,
            scan_id=scan_id,
        )
        target = self.knowledge_library_service.write_uploaded_file(
            user_id=context["user_id"],
            filename=filename,
            content=markdown.encode("utf-8"),
            conflict_strategy=conflict_strategy,
        )
        relative = target.relative_to(context["root"]).as_posix()
        if bool(profile.get("auto_ingest_on_upload")):
            self.knowledge_library_service.ingest_single_file(user_id=context["user_id"], path=relative)
        return {"ok": True, "path": relative, "assets": copied_assets}

    def export_payload(self, *, user_id: str, scan_id: str, variant: ScannerVariant) -> tuple[str, str, bytes]:
        """Return filename, media type, and bytes for native external saving."""

        context = self._context(user_id)
        with Session(self.engine) as db:
            record = self._owned_record(db=db, context=context, scan_id=scan_id)
            markdown = self._variant_content(record, variant)
            stem = Path(record.source_name).stem
            if variant == "ocr":
                return f"{stem}.md", "text/markdown; charset=utf-8", markdown.encode("utf-8")
            assets = self._asset_paths(record=record, context=context)
        profile = self.settings_service.ensure_user_profile(user_id=context["user_id"])
        asset_dir = self._normalized_asset_dir(str(profile.get("editor_image_assets_dir") or "./assets/"))
        markdown = self._rewrite_asset_directory(markdown, asset_dir)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{stem}.md", markdown)
            for asset in assets:
                archive.write(asset, f"{asset_dir}/{asset.name}")
        return f"{stem}.zip", "application/zip", buffer.getvalue()

    def _submit(self, scan_id: str) -> None:
        """Submit one record to the owned executor unless shutdown began."""

        with self._lock:
            if self._closed:
                raise RuntimeError("scanner service is stopped")
            self._executor.submit(self._process, scan_id)

    def _process(self, scan_id: str) -> None:
        """Run file projection or webpage crawling and persist a terminal state."""

        try:
            self._set_progress(scan_id, status="running", stage="prepare", label="正在准备文件", progress=2)
            with Session(self.engine) as db:
                record = db.get(ScannerRecord, scan_id)
                if record is None:
                    return
                context = self._context(record.user_id, expected_library_id=record.library_id)
                if record.source_kind == "url":
                    no_ocr, ocr, assets, ocr_blocks, source_name, source_path, size = self._crawl(record=record, context=context)
                else:
                    no_ocr, ocr, assets, ocr_blocks = self._project_file(record=record, context=context)
                    source_name, source_path, size = record.source_name, record.source_path, record.size
            with Session(self.engine) as db:
                record = db.get(ScannerRecord, scan_id)
                if record is None:
                    return
                record.source_name = source_name
                record.source_path = source_path
                record.size = size
                record.no_ocr_markdown = no_ocr
                record.ocr_markdown = ocr
                record.ocr_blocks_json = json.dumps(ocr_blocks, ensure_ascii=False)
                record.assets_json = json.dumps(assets, ensure_ascii=False)
                record.status = "finished"
                record.stage = "completed"
                record.stage_label = "解析完成"
                record.progress = 100
                record.error = ""
                record.finished_at = self._now()
                record.updated_at = self._now()
                db.add(record)
                db.commit()
        except Exception as exc:
            logger.exception("扫描器解析失败 | scan_id=%s", scan_id)
            with Session(self.engine) as db:
                record = db.get(ScannerRecord, scan_id)
                if record is None:
                    return
                record.status = "failed"
                record.stage = "failed"
                record.stage_label = "解析失败"
                record.error = str(exc)
                record.finished_at = self._now()
                record.updated_at = self._now()
                db.add(record)
                db.commit()

    def _project_file(self, *, record: ScannerRecord, context: dict[str, Any]) -> tuple[str, str, list[str], list[dict[str, Any]]]:
        """Create no-OCR and optional OCR projections through the shared cleaner."""

        source = self._source_absolute(record=record, context=context)
        supported = set(self.config.constants.knowledge_supported_suffixes)
        if not FrontmatterBootstrapService._can_structure_source_file(source, supported):
            raise ValueError(f"unsupported binary file type: {source.suffix.lower() or 'unknown'}")
        assets_dir = self._scan_root(context=context, scan_id=record.scan_id) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in IMAGE_SUFFIXES:
            asset = assets_dir / self._safe_asset_name(source.name)
            shutil.copy2(source, asset)
            no_ocr = f"# {source.stem}\n\n![{source.stem}](./assets/{asset.name})\n"
        else:
            no_ocr_doc = FrontmatterBootstrapService(config=self.config, ocr_enabled=False).build_markdown_projection(
                source_path=source,
                knowledge_dir=context["root"],
                asset_output_dir=assets_dir,
                asset_public_prefix="./assets",
                progress_callback=lambda payload: self._projection_progress(record.scan_id, payload, 4, 48),
            )
            no_ocr = no_ocr_doc.markdown
        assets = [path.relative_to(context["root"]).as_posix() for path in sorted(assets_dir.glob("*")) if path.is_file()]
        if not record.ocr_enabled:
            return no_ocr, "", assets, []
        ocr_doc = FrontmatterBootstrapService(config=self.config, ocr_enabled=True).build_markdown_projection(
            source_path=source,
            knowledge_dir=context["root"],
            asset_output_dir=assets_dir,
            asset_public_prefix="./assets",
            progress_callback=lambda payload: self._projection_progress(record.scan_id, payload, 50, 96),
        )
        ocr_blocks = [dict(block) for block in ocr_doc.metadata.get("ocr_blocks", []) if isinstance(block, dict)]
        return no_ocr, self._strip_markdown_images(ocr_doc.markdown), assets, ocr_blocks

    def _crawl(self, *, record: ScannerRecord, context: dict[str, Any]) -> tuple[str, str, list[str], list[dict[str, Any]], str, str, int]:
        """Fetch a public webpage, localize images, and build both projection variants."""

        self._set_progress(record.scan_id, status="running", stage="download", label="正在抓取网页", progress=12)
        final_url, content_type, body = self._fetch_url(record.source_url)
        if "html" not in content_type.lower():
            raise ValueError("webpage URL did not return HTML")
        text = body.decode("utf-8", errors="replace")
        parser = _HtmlMarkdownParser()
        parser.feed(text)
        title = parser.title() or urlparse(final_url).hostname or "webpage"
        safe_title = re.sub(r"[\\/:*?\"<>|]+", "-", title).strip(" .") or "webpage"
        scan_root = self._scan_root(context=context, scan_id=record.scan_id)
        source = scan_root / "source" / f"{safe_title}.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(body)
        markdown = parser.markdown()
        if not markdown.lstrip().startswith("#"):
            markdown = f"# {safe_title}\n\n{markdown}"
        assets_dir = scan_root / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        replacements: dict[str, str] = {}
        for index, (image_url, _alt) in enumerate(parser.images, start=1):
            try:
                absolute_url = urljoin(final_url, image_url)
                _, image_type, image_body = self._fetch_url(absolute_url)
                if not image_type.lower().startswith("image/"):
                    continue
                suffix = mimetypes.guess_extension(image_type.split(";", 1)[0].strip()) or Path(urlparse(absolute_url).path).suffix or ".img"
                name = self._safe_asset_name(f"image-{index}{suffix}")
                (assets_dir / name).write_bytes(image_body)
                replacements[image_url] = f"./assets/{name}"
            except Exception:
                logger.info("网页图片本地化失败 | scan_id=%s image=%s", record.scan_id, image_url)
        for remote, local in replacements.items():
            markdown = markdown.replace(f"]({remote})", f"]({local})")
        self._set_progress(record.scan_id, status="running", stage="normalize", label="正在生成 Markdown", progress=72)
        assets = [path.relative_to(context["root"]).as_posix() for path in sorted(assets_dir.glob("*")) if path.is_file()]
        ocr_texts: list[str] = []
        ocr_blocks: list[dict[str, Any]] = []
        if record.ocr_enabled and assets:
            ocr_service = ImageOcrService(config=self.config, enabled=True)
            for index, relative in enumerate(assets, start=1):
                result = ocr_service.extract_image_text(context["root"] / relative)
                if result.has_text:
                    ocr_texts.append(result.content)
                ocr_blocks.extend(dict(block) for block in result.blocks)
                self._set_progress(record.scan_id, status="running", stage="ocr", label=f"正在识别网页图片 {index}/{len(assets)}", progress=72 + round(index / len(assets) * 22))
        ocr_markdown = self._strip_markdown_images(markdown)
        if ocr_texts:
            ocr_markdown += "\n\n## 图片文字\n\n" + "\n\n".join(ocr_texts)
        return markdown.strip() + "\n", ocr_markdown.strip() + "\n" if record.ocr_enabled else "", assets, ocr_blocks, source.name, source.relative_to(context["root"]).as_posix(), len(body)

    def _fetch_url(self, url: str) -> tuple[str, str, bytes]:
        """Fetch one public URL with per-hop SSRF checks and bounded bytes."""

        current = url
        for _ in range(self.config.limits.scanner_redirect_limit + 1):
            self._validate_public_url(current)
            response = requests.get(
                current,
                headers={"User-Agent": "MetaWeave-Scanner/1.0"},
                timeout=self.config.limits.web_fetch_timeout_seconds,
                allow_redirects=False,
                stream=True,
            )
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location", "").strip()
                if not location:
                    raise ValueError("webpage redirect is missing a location")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_content(64 * 1024):
                data.extend(chunk)
                if len(data) > self.config.limits.scanner_web_max_bytes:
                    raise ValueError("web resource exceeds scanner size limit")
            return current, response.headers.get("Content-Type", ""), bytes(data)
        raise ValueError("webpage exceeded redirect limit")

    def _validate_public_url(self, url: str) -> None:
        """Reject non-HTTP schemes and DNS targets in private/local networks."""

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url must use http or https")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise ValueError("unable to resolve webpage host") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise ValueError("private or local webpage addresses are not allowed")

    def _projection_progress(self, scan_id: str, payload: dict[str, Any], start: int, end: int) -> None:
        """Map the shared 0-100 projection progress into one scanner phase."""

        source_progress = float(payload.get("overall_progress") or 0)
        progress = round(start + max(0, min(100, source_progress)) / 100 * (end - start), 1)
        self._set_progress(scan_id, status="running", stage=str(payload.get("stage") or "extract"), label=str(payload.get("stage_label") or "正在解析文件"), progress=progress)

    def _set_progress(self, scan_id: str, *, status: str, stage: str, label: str, progress: float) -> None:
        """Persist monotonic scanner task progress."""

        with Session(self.engine) as db:
            record = db.get(ScannerRecord, scan_id)
            if record is None:
                return
            record.status = status
            record.stage = stage
            record.stage_label = label
            running_max = self.config.limits.progress_max_percent - 0.1
            record.progress = max(record.progress, min(running_max, round(progress, 1)))
            record.updated_at = self._now()
            db.add(record)
            db.commit()

    def _copy_assets_to_knowledge(self, *, markdown: str, assets: list[Path], root: Path, asset_dir: str, scan_id: str) -> tuple[str, list[str]]:
        """Copy assets with collision-safe names and rewrite Markdown links."""

        target_dir = (root / asset_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        rewritten = self._rewrite_asset_directory(markdown, asset_dir)
        for asset in assets:
            target_name = self._safe_asset_name(f"{scan_id[-8:]}-{asset.name}")
            target = target_dir / target_name
            shutil.copy2(asset, target)
            rewritten = rewritten.replace(f"{asset_dir}/{asset.name}", f"{asset_dir}/{target_name}")
            copied.append(target.relative_to(root).as_posix())
        return rewritten, copied

    @staticmethod
    def _rewrite_asset_directory(markdown: str, asset_dir: str) -> str:
        """Rewrite scanner-local asset links to a configured relative directory."""

        normalized = f"./{asset_dir.strip('./')}/"
        return markdown.replace("./assets/", normalized)

    @staticmethod
    def _strip_markdown_images(markdown: str) -> str:
        """Remove Markdown and HTML image nodes from a pure-text OCR projection."""

        value = IMAGE_MARKDOWN_RE.sub("", markdown)
        value = re.sub(r"<img\b[^>]*>", "", value, flags=re.IGNORECASE)
        return re.sub(r"\n{3,}", "\n\n", value).strip() + "\n"

    @staticmethod
    def _normalized_asset_dir(value: str) -> str:
        """Return the safe slash-normalized relative asset directory."""

        parts = [part for part in value.replace("\\", "/").split("/") if part and part != "."]
        if not parts or ".." in parts:
            return "assets"
        return "/".join(parts)

    @staticmethod
    def _safe_asset_name(value: str) -> str:
        """Normalize one downloaded or extracted asset basename."""

        name = re.sub(r"[^0-9A-Za-z._-]+", "-", Path(value).name).strip(".-")
        return name or f"asset-{uuid4().hex[:8]}"

    def _asset_paths(self, *, record: ScannerRecord, context: dict[str, Any]) -> list[Path]:
        """Resolve persisted relative asset paths without permitting traversal."""

        try:
            relative_paths = json.loads(record.assets_json or "[]")
        except json.JSONDecodeError:
            relative_paths = []
        assets: list[Path] = []
        for value in relative_paths if isinstance(relative_paths, list) else []:
            candidate = (context["root"] / str(value)).resolve()
            if self._is_relative_to(candidate, context["root"]) and candidate.is_file():
                assets.append(candidate)
        return assets

    @staticmethod
    def _variant_content(record: ScannerRecord, variant: ScannerVariant) -> str:
        """Return an available terminal Markdown variant or raise a clear error."""

        if record.status != "finished":
            raise ValueError("scan is not finished")
        if variant == "ocr" and not record.ocr_enabled:
            raise ValueError("OCR variant is unavailable for this scan")
        content = record.ocr_markdown if variant == "ocr" else record.no_ocr_markdown
        if not content:
            raise ValueError("scanner Markdown is empty")
        return content

    def _context(self, user_id: str, expected_library_id: str = "") -> dict[str, Any]:
        """Resolve the active user/library/root and optionally verify task scope."""

        profile = self.settings_service.ensure_user_profile(user_id=self._required(user_id, "user_id"))
        active = dict(profile["active_knowledge_library"])
        library_id = str(active["library_id"])
        if expected_library_id and library_id != expected_library_id:
            raise ValueError("scanner record belongs to another knowledge library")
        root = Path(str(active["knowledge_dir"])).expanduser().resolve()
        return {"user_id": str(profile["user_id"]), "library_id": library_id, "root": root}

    @staticmethod
    def _scan_root(*, context: dict[str, Any], scan_id: str) -> Path:
        """Return one isolated scanner directory under the active knowledge root."""

        return Path(context["root"]) / ".mw" / "scan" / scan_id

    def _source_absolute(self, *, record: ScannerRecord, context: dict[str, Any]) -> Path:
        """Resolve a persisted managed source path within the active root."""

        source = (context["root"] / record.source_path).resolve()
        if not self._is_relative_to(source, context["root"]) or not source.is_file():
            raise ValueError("managed scanner source not found")
        return source

    @staticmethod
    def _owned_record(*, db: Session, context: dict[str, Any], scan_id: str) -> ScannerRecord:
        """Load one record and enforce user plus library ownership."""

        record = db.get(ScannerRecord, scan_id)
        if record is None or record.user_id != context["user_id"] or record.library_id != context["library_id"]:
            raise ValueError("scanner record not found")
        return record

    def _to_out(self, record: ScannerRecord, *, context: dict[str, Any], include_content: bool = True) -> ScannerOut:
        """Serialize a record, omitting large drafts from history-list payloads."""

        source_text: str | None = None
        if include_content and record.source_path:
            source = (context["root"] / record.source_path).resolve()
            if self._is_relative_to(source, context["root"]) and source.is_file() and source.suffix.lower() in TEXT_SUFFIXES:
                try:
                    source_text = source.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    source_text = source.read_text(encoding="utf-8", errors="replace")
        try:
            assets = json.loads(record.assets_json or "[]")
        except json.JSONDecodeError:
            assets = []
        try:
            ocr_blocks = json.loads(record.ocr_blocks_json or "[]")
        except json.JSONDecodeError:
            ocr_blocks = []
        return ScannerOut(
            scan_id=record.scan_id,
            user_id=record.user_id,
            library_id=record.library_id,
            source_kind=record.source_kind,
            source_name=record.source_name,
            source_path=record.source_path,
            source_url=record.source_url,
            size=record.size,
            ocr_enabled=record.ocr_enabled,
            status=record.status,
            stage=record.stage,
            stage_label=record.stage_label,
            progress=record.progress,
            no_ocr_markdown=record.no_ocr_markdown if include_content else "",
            ocr_markdown=record.ocr_markdown if include_content else "",
            ocr_blocks=[dict(item) for item in ocr_blocks if isinstance(item, dict)] if include_content else [],
            assets=[str(item) for item in assets] if isinstance(assets, list) else [],
            error=record.error,
            source_text=source_text,
            created_at=record.created_at,
            updated_at=record.updated_at,
            finished_at=record.finished_at,
        )

    def _fail_interrupted_records(self) -> None:
        """Move stale queued/running records to an explicit failed terminal state."""

        with Session(self.engine) as db:
            records = db.exec(select(ScannerRecord).where(ScannerRecord.status.in_(["queued", "running"]))).all()
            for record in records:
                record.status = "failed"
                record.stage = "interrupted"
                record.stage_label = "解析已中断"
                record.error = "应用退出时解析尚未完成，请重新上传"
                record.finished_at = self._now()
                record.updated_at = self._now()
                db.add(record)
            if records:
                db.commit()

    @staticmethod
    def _required(value: str, label: str) -> str:
        """Normalize a required string."""

        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{label} is required")
        return normalized

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        """Return whether a resolved path remains inside a resolved root."""

        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _now() -> datetime:
        """Return the current timezone-aware UTC timestamp."""

        return datetime.now(timezone.utc)
