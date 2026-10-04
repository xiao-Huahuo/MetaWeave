"""密码库加密条目、回收站、导入导出和图片资产业务服务。

统一登录管理主密码与会话。REST/gRPC 验证 AuthSession 后将同一身份、直接
派生 Fernet key 与 password_version 传入业务方法，密码库不再签发独立 JWT。
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import update
from sqlmodel import Session, col, select

from agent_service.core.agent_config import AgentConfig
from agent_service.models.account import Account
from agent_service.models.vault import VaultAsset, VaultItem, VaultItemTag, VaultTag

logger = logging.getLogger(__name__)

VAULT_ITEM_TYPES = {"login", "card", "identity", "secure_note"}
VAULT_CARD_BRANDS = {
    "UnionPay银联",
    "Visa",
    "Mastercard",
    "American Express",
    "JCB",
    "Discover",
    "Diners Club",
    "Maestro",
    "RuPay",
    "其他",
}
VAULT_TITLES = {"先生", "夫人", "女士", "Mx", "博士"}
REQUIRED_FIELDS = {
    "login": ("name", "password"),
    "card": ("name", "number"),
    "identity": ("name", "first_name"),
    "secure_note": ("name", "note"),
}
SENSITIVE_FIELDS = {"password", "security_code", "note", "number"}


@dataclass(frozen=True)
class VaultSession:
    """已解锁密码库会话。"""

    user_id: str
    fernet_key: str = field(repr=False)
    password_version: int


class VaultService:
    """密码库服务。"""

    def __init__(self, *, config: AgentConfig, engine: Any) -> None:
        """保存统一配置与 engine，并确保运行时图片目录存在。"""

        self.config = config
        self.engine = engine
        self.assets_root = config.storage.assets_dir / "vault"
        self.assets_root.mkdir(parents=True, exist_ok=True)
        self._retry_pending_asset_cleanup()

    def status(self, *, session: VaultSession) -> dict[str, Any]:
        """Return vault availability for the already authenticated account."""

        with Session(self.engine) as db:
            count = len(list(db.exec(select(VaultItem).where(VaultItem.user_id == session.user_id)).all()))
        return {"user_id": session.user_id, "configured": True, "item_count": count}

    def list_items(
        self,
        *,
        session: VaultSession,
        query: str = "",
        tag: str = "",
        item_type: str = "",
        trash: bool = False,
    ) -> dict[str, Any]:
        """列出当前用户的密码库条目,在服务端解密后进行全字段搜索。"""

        normalized_query = query.strip().lower()
        normalized_tag = tag.strip()
        normalized_type = item_type.strip()
        with Session(self.engine) as db:
            items = list(db.exec(select(VaultItem).where(VaultItem.user_id == session.user_id)).all())
            items = [item for item in items if bool(item.deleted_at) is trash]
            if normalized_type:
                items = [item for item in items if item.item_type == normalized_type]
            tags_by_item = self._tags_by_item(db=db, item_ids=[item.item_id for item in items])
            if normalized_tag:
                items = [item for item in items if normalized_tag in tags_by_item.get(item.item_id, [])]
            search_payloads = [self._serialize_item(item, tags_by_item.get(item.item_id, []), session, reveal_sensitive=True) for item in items]
            if normalized_query:
                search_payloads = [item for item in search_payloads if normalized_query in self._search_blob(item)]
            payloads = [self._redact_item(item) for item in search_payloads]
            payloads.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
            return {
                "items": payloads,
                "total": len(payloads),
                "type_counts": self._type_counts(payloads),
            }

    def list_tags(self, *, session: VaultSession) -> dict[str, Any]:
        """列出用户最近使用的密码库标签。"""

        with Session(self.engine) as db:
            tags = list(db.exec(select(VaultTag).where(VaultTag.user_id == session.user_id).order_by(VaultTag.created_at.desc())).all())
        return {"tags": [{"tag_id": tag.tag_id, "name": tag.name} for tag in tags]}

    def create_item(
        self,
        *,
        session: VaultSession,
        item_type: str,
        fields: dict[str, Any],
        tags: list[str],
        asset_ids: list[str],
    ) -> dict[str, Any]:
        """创建一个加密密码库条目。"""

        normalized_type, normalized_fields = self._normalize_item_payload(item_type, fields)
        now = self._now()
        item = VaultItem(
            item_id=self._new_id("vault"),
            user_id=session.user_id,
            item_type=normalized_type,
            encrypted_payload=self._encrypt(session, normalized_fields),
            created_at=now,
            updated_at=now,
        )
        with Session(self.engine) as db:
            self._begin_write(db=db, session=session)
            db.add(item)
            db.flush()
            self._replace_tags(db=db, user_id=session.user_id, item_id=item.item_id, tag_names=tags)
            self._attach_assets(db=db, session=session, item_id=item.item_id, asset_ids=asset_ids)
            result = self._serialize_item(item, self._tags_by_item(db=db, item_ids=[item.item_id]).get(item.item_id, []), session, reveal_sensitive=True)
            db.commit()
            return {"item": result}

    def get_item(self, *, session: VaultSession, item_id: str) -> dict[str, Any]:
        """读取一个当前用户拥有的密码库条目。"""

        with Session(self.engine) as db:
            item = self._get_owned_item(db=db, session=session, item_id=item_id)
            tags = self._tags_by_item(db=db, item_ids=[item.item_id]).get(item.item_id, [])
            return {"item": self._serialize_item(item, tags, session, reveal_sensitive=True)}

    def update_item(
        self,
        *,
        session: VaultSession,
        item_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """更新一个密码库条目,只有显式保存才写入数据库。"""

        with Session(self.engine) as db:
            self._begin_write(db=db, session=session)
            item = self._get_owned_item(db=db, session=session, item_id=item_id)
            item_type = str(payload.get("item_type") or item.item_type)
            fields = payload.get("fields")
            if fields is None:
                fields = self._decrypt(session, item.encrypted_payload)
            normalized_type, normalized_fields = self._normalize_item_payload(item_type, fields)
            item.item_type = normalized_type
            item.encrypted_payload = self._encrypt(session, normalized_fields)
            item.updated_at = self._now()
            db.add(item)
            if "tags" in payload:
                self._replace_tags(db=db, user_id=session.user_id, item_id=item.item_id, tag_names=list(payload.get("tags") or []))
            if "asset_ids" in payload:
                self._attach_assets(db=db, session=session, item_id=item.item_id, asset_ids=list(payload.get("asset_ids") or []))
            tags = self._tags_by_item(db=db, item_ids=[item.item_id]).get(item.item_id, [])
            result = self._serialize_item(item, tags, session, reveal_sensitive=True)
            db.commit()
            return {"item": result}

    def move_to_trash(self, *, session: VaultSession, item_ids: list[str]) -> dict[str, Any]:
        """将条目移入密码库回收站。"""

        return self._mark_deleted(session=session, item_ids=item_ids, deleted=True)

    def restore_items(self, *, session: VaultSession, item_ids: list[str]) -> dict[str, Any]:
        """从密码库回收站恢复条目。"""

        return self._mark_deleted(session=session, item_ids=item_ids, deleted=False)

    def purge_items(self, *, session: VaultSession, item_ids: list[str]) -> dict[str, Any]:
        """永久删除条目并同步删除关联图片文件。"""

        normalized_ids = list(dict.fromkeys(item_id.strip() for item_id in item_ids if item_id.strip()))
        deleted = 0
        assets_to_clean: list[tuple[str, str]] = []
        with Session(self.engine) as db:
            self._begin_write(db=db, session=session)
            items = []
            # Validate the whole request before any deletion. Missing items are
            # retryable only when this owner has a formal pending asset record.
            for item_id in normalized_ids:
                item = db.get(VaultItem, item_id)
                assets = list(db.exec(select(VaultAsset).where(VaultAsset.item_id == item_id)
                                      .where(VaultAsset.user_id == session.user_id)).all())
                if (item is not None and item.user_id != session.user_id) or (item is None and not assets):
                    raise ValueError("vault item not found")
                if item is not None:
                    items.append(item)
                assets_to_clean.extend((asset.asset_id, asset.storage_path) for asset in assets)
            for item in items:
                for link in list(db.exec(select(VaultItemTag).where(VaultItemTag.item_id == item.item_id)).all()):
                    db.delete(link)
                db.delete(item)
                deleted += 1
            db.commit()
        # Until cleanup succeeds, asset rows referencing the removed parent are
        # durable tombstones. They cannot be served or attached to another item.
        if not self._cleanup_purged_assets(assets_to_clean):
            raise ValueError("vault items deleted; image cleanup is pending, close the file and retry")
        return {"ok": True, "deleted_count": deleted}

    def export_items(self, *, session: VaultSession, item_ids: list[str] | None = None) -> dict[str, Any]:
        """导出全部或选中的密码库条目为明文 JSON。"""

        with Session(self.engine) as db:
            statement = select(VaultItem).where(VaultItem.user_id == session.user_id).where(VaultItem.deleted_at == None)  # noqa: E711
            if item_ids:
                statement = statement.where(col(VaultItem.item_id).in_(item_ids))
            items = list(db.exec(statement).all())
            tags_by_item = self._tags_by_item(db=db, item_ids=[item.item_id for item in items])
            exported = [self._serialize_item(item, tags_by_item.get(item.item_id, []), session, reveal_sensitive=True) for item in items]
        return {
            "format": "metaweave-vault-json",
            "exported_at": self._now().isoformat(),
            "warning": "该文件包含密码库敏感明文,请仅保存到可信位置。",
            "items": exported,
        }

    def import_items(self, *, session: VaultSession, raw_items: list[dict[str, Any]]) -> dict[str, Any]:
        """导入 JSON 条目,字段不匹配时转为安全笔记。"""

        imported = 0
        converted = 0
        failed = 0
        for raw in raw_items:
            try:
                item_type, fields, tags = self._coerce_import_item(raw)
                if item_type == "secure_note" and str(raw.get("item_type") or raw.get("type") or "") not in {"secure_note", "note"}:
                    converted += 1
                self.create_item(session=session, item_type=item_type, fields=fields, tags=tags, asset_ids=[])
                imported += 1
            except ValueError:
                failed += 1
        return {"imported": imported, "converted_to_secure_note": converted, "failed": failed}

    def upload_asset(self, *, session: VaultSession, filename: str, content: bytes, mime_type: str) -> dict[str, Any]:
        """上传一个密码库图片到受保护运行时目录。"""

        if not content:
            raise ValueError("file is empty")
        if mime_type and not mime_type.startswith("image/"):
            raise ValueError("only image uploads are supported")
        asset_id = self._new_id("vasset")
        safe_name = self._safe_filename(filename)
        user_dir = self.assets_root / self._safe_filename(session.user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        storage_path = user_dir / f"{asset_id}_{safe_name}"
        asset = VaultAsset(
            asset_id=asset_id,
            user_id=session.user_id,
            file_name=safe_name,
            mime_type=mime_type or "application/octet-stream",
            storage_path=str(storage_path),
            size=len(content),
            created_at=self._now(),
        )
        with Session(self.engine) as db:
            self._begin_write(db=db, session=session)
            try:
                storage_path.write_bytes(content)
                db.add(asset)
                result = self._serialize_asset(asset)
                db.commit()
            except Exception:
                # A failed insert/write never leaves unowned sensitive assets.
                storage_path.unlink(missing_ok=True)
                raise
        return {"asset": result}

    def get_asset(self, *, session: VaultSession, asset_id: str) -> VaultAsset:
        """读取当前用户拥有的图片资产。"""

        with Session(self.engine) as db:
            asset = db.get(VaultAsset, asset_id)
            if asset is None or asset.user_id != session.user_id:
                raise ValueError("vault asset not found")
            if asset.item_id and db.get(VaultItem, asset.item_id) is None:
                raise ValueError("vault asset not found")
            return asset

    def _mark_deleted(self, *, session: VaultSession, item_ids: list[str], deleted: bool) -> dict[str, Any]:
        """批量修改回收站状态。"""

        normalized_ids = [item_id.strip() for item_id in item_ids if item_id.strip()]
        changed = 0
        with Session(self.engine) as db:
            self._begin_write(db=db, session=session)
            for item_id in normalized_ids:
                item = self._get_owned_item(db=db, session=session, item_id=item_id)
                item.deleted_at = self._now() if deleted else None
                item.updated_at = self._now()
                db.add(item)
                changed += 1
            db.commit()
        return {"ok": True, "changed_count": changed}

    def _normalize_item_payload(self, item_type: str, fields: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """校验并规范化不同类型条目的字段。"""

        normalized_type = item_type.strip()
        if normalized_type not in VAULT_ITEM_TYPES:
            raise ValueError("unsupported vault item_type")
        normalized_fields = dict(fields or {})
        normalized_fields["name"] = str(normalized_fields.get("name") or normalized_fields.get("title") or "").strip()
        if normalized_type == "card":
            brand = str(normalized_fields.get("brand") or "").strip()
            if brand and brand not in VAULT_CARD_BRANDS:
                raise ValueError("unsupported card brand")
        if normalized_type == "identity":
            title = str(normalized_fields.get("title") or "").strip()
            if title and title not in VAULT_TITLES:
                raise ValueError("unsupported identity title")
        for field_name in REQUIRED_FIELDS[normalized_type]:
            if not str(normalized_fields.get(field_name) or "").strip():
                raise ValueError(f"{field_name} is required")
        custom_fields = normalized_fields.get("custom_fields")
        if custom_fields is not None and not isinstance(custom_fields, list):
            raise ValueError("custom_fields must be a list")
        normalized_fields["custom_fields"] = custom_fields or []
        normalized_fields["asset_ids"] = [str(item) for item in normalized_fields.get("asset_ids", []) if str(item).strip()]
        return normalized_type, normalized_fields

    def _coerce_import_item(self, raw: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
        """把导入记录转换为可创建条目。"""

        if not isinstance(raw, dict):
            raise ValueError("invalid import item")
        item_type = str(raw.get("item_type") or raw.get("type") or "").strip()
        fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else dict(raw)
        tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
        if item_type in VAULT_ITEM_TYPES:
            try:
                normalized_type, normalized_fields = self._normalize_item_payload(item_type, fields)
                return normalized_type, normalized_fields, [str(tag) for tag in tags]
            except ValueError:
                pass
        note = json.dumps(raw, ensure_ascii=False, indent=2)
        name = str(raw.get("name") or raw.get("title") or raw.get("项目名称") or "导入条目").strip()
        if not name or note == "{}":
            raise ValueError("unrecognizable import item")
        return "secure_note", {"name": name, "note": note, "custom_fields": []}, [str(tag) for tag in tags]

    def _serialize_item(
        self,
        item: VaultItem,
        tags: list[str],
        session: VaultSession,
        *,
        reveal_sensitive: bool,
    ) -> dict[str, Any]:
        """解密并序列化条目。"""

        fields = self._decrypt(session, item.encrypted_payload)
        safe_fields = {key: value for key, value in fields.items() if key not in SENSITIVE_FIELDS}
        response_fields = fields if reveal_sensitive else safe_fields
        field_keys = [key for key, value in fields.items() if self._field_value_is_non_empty(value)]
        return {
            "item_id": item.item_id,
            "user_id": item.user_id,
            "item_type": item.item_type,
            "name": str(fields.get("name") or ""),
            "fields": response_fields,
            "safe_fields": safe_fields,
            "field_keys": field_keys,
            "tags": tags,
            "deleted_at": item.deleted_at.isoformat() if item.deleted_at else "",
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }

    @staticmethod
    def _field_value_is_non_empty(value: Any) -> bool:
        """Report field presence without exposing an encrypted field value."""

        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

    def _redact_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Return a list-safe item payload with sensitive fields removed."""

        safe_fields = dict(item.get("safe_fields", {}) or {})
        return {
            **item,
            "fields": safe_fields,
            "safe_fields": safe_fields,
        }

    def _search_blob(self, item: dict[str, Any]) -> str:
        """构造仅用于内存匹配的全字段搜索文本。"""

        return json.dumps({"fields": item.get("fields", {}), "tags": item.get("tags", [])}, ensure_ascii=False).lower()

    def _type_counts(self, items: list[dict[str, Any]]) -> dict[str, int]:
        """统计四类密码条目的数量。"""

        counts = {item_type: 0 for item_type in VAULT_ITEM_TYPES}
        for item in items:
            item_type = str(item.get("item_type") or "")
            if item_type in counts:
                counts[item_type] += 1
        return counts

    def _encrypt(self, session: VaultSession, payload: dict[str, Any]) -> str:
        """使用会话解密材料加密 JSON。"""

        return Fernet(session.fernet_key.encode("ascii")).encrypt(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")

    def _decrypt(self, session: VaultSession, encrypted_payload: str) -> dict[str, Any]:
        """解密 JSON 业务字段。"""

        try:
            raw = Fernet(session.fernet_key.encode("ascii")).decrypt(encrypted_payload.encode("ascii"))
            payload = json.loads(raw.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("unable to decrypt vault item with current token") from exc
        return payload if isinstance(payload, dict) else {}

    def _replace_tags(self, *, db: Session, user_id: str, item_id: str, tag_names: list[str]) -> None:
        """替换条目标签关系。"""

        for link in list(db.exec(select(VaultItemTag).where(VaultItemTag.item_id == item_id)).all()):
            db.delete(link)
        normalized_names = []
        for name in tag_names:
            normalized = str(name).strip()
            if normalized and normalized not in normalized_names:
                normalized_names.append(normalized[:self.config.limits.vault_tag_name_max_chars])
        for name in normalized_names:
            tag = db.exec(select(VaultTag).where(VaultTag.user_id == user_id).where(VaultTag.name == name)).first()
            if tag is None:
                tag = VaultTag(tag_id=self._new_id("vtag"), user_id=user_id, name=name, created_at=self._now())
                db.add(tag)
                db.flush()
            db.add(VaultItemTag(item_id=item_id, tag_id=tag.tag_id))
        db.flush()

    def _tags_by_item(self, *, db: Session, item_ids: list[str]) -> dict[str, list[str]]:
        """批量读取条目的标签名。"""

        if not item_ids:
            return {}
        links = list(db.exec(select(VaultItemTag).where(col(VaultItemTag.item_id).in_(item_ids))).all())
        tag_ids = [link.tag_id for link in links]
        tags = {tag.tag_id: tag.name for tag in db.exec(select(VaultTag).where(col(VaultTag.tag_id).in_(tag_ids))).all()} if tag_ids else {}
        result: dict[str, list[str]] = {item_id: [] for item_id in item_ids}
        for link in links:
            name = tags.get(link.tag_id)
            if name:
                result.setdefault(link.item_id, []).append(name)
        return result

    def _attach_assets(self, *, db: Session, session: VaultSession, item_id: str, asset_ids: list[str]) -> None:
        """把上传图片绑定到条目。"""

        for asset_id in asset_ids:
            asset = db.get(VaultAsset, str(asset_id))
            if asset is not None and asset.user_id == session.user_id:
                if asset.item_id and db.get(VaultItem, asset.item_id) is None:
                    raise ValueError("vault asset not found")
                asset.item_id = item_id
                db.add(asset)
        db.flush()

    def _cleanup_purged_assets(self, assets: list[tuple[str, str]]) -> bool:
        """Delete files after parent commit and retain failed cleanup in formal rows."""
        cleaned = []
        complete = True
        for asset_id, storage_path in assets:
            try:
                self._delete_asset_file(storage_path)
            except OSError as exc:
                complete = False
                logger.warning("Vault image cleanup pending | asset_id=%s error_type=%s", asset_id, type(exc).__name__)
            else:
                cleaned.append(asset_id)
        if cleaned:
            with Session(self.engine) as db:
                for asset_id in cleaned:
                    record = db.get(VaultAsset, asset_id)
                    if record is not None and record.item_id and db.get(VaultItem, record.item_id) is None:
                        db.delete(record)
                db.commit()
        return complete

    def _retry_pending_asset_cleanup(self) -> None:
        """Recover interrupted purges at application startup without a new worker."""
        with Session(self.engine) as db:
            records = db.exec(select(VaultAsset).where(VaultAsset.item_id != "")
                .where(~select(VaultItem.item_id).where(VaultItem.item_id == VaultAsset.item_id).exists())).all()
            assets = [(asset.asset_id, asset.storage_path) for asset in records]
        try:
            self._cleanup_purged_assets(assets)
        except Exception as exc:
            logger.warning("Vault pending cleanup deferred | error_type=%s", type(exc).__name__)

    def _serialize_asset(self, asset: VaultAsset) -> dict[str, Any]:
        """序列化图片资产元数据,不暴露真实磁盘路径。"""

        return {
            "asset_id": asset.asset_id,
            "item_id": asset.item_id,
            "mime_type": asset.mime_type,
            "file_name": asset.file_name,
            "size": asset.size,
            "created_at": asset.created_at.isoformat(),
        }

    def _get_owned_item(self, *, db: Session, session: VaultSession, item_id: str) -> VaultItem:
        """读取当前用户拥有的条目。"""

        item = db.get(VaultItem, item_id.strip())
        if item is None or item.user_id != session.user_id:
            raise ValueError("vault item not found")
        return item

    @staticmethod
    def _begin_write(*, db: Session, session: VaultSession) -> None:
        """Serialize vault writes with password changes and reject stale key versions.

        The conditional no-op account write acquires the database writer slot;
        password change cannot rotate keys between this check and item commit.
        There is no Python lock around database I/O.
        """
        result = db.exec(update(Account).where(Account.user_id == session.user_id)
                         .where(Account.password_version == session.password_version)
                         .values(password_version=session.password_version))
        if result.rowcount != 1:
            raise ValueError("login session is invalid or expired")

    @staticmethod
    def _now() -> datetime:
        """返回当前 UTC 时间。"""

        return datetime.now(timezone.utc)

    def _new_id(self, prefix: str) -> str:
        """生成业务主键。"""

        return f"{prefix}_{uuid4().hex[:self.config.limits.generated_long_id_suffix_chars]}"

    def _safe_filename(self, value: str) -> str:
        """清理文件名或目录名中的危险字符。"""

        cleaned = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in value.strip())
        return (cleaned.strip(" .") or "asset")[:self.config.limits.vault_asset_filename_max_chars]

    @staticmethod
    def _delete_asset_file(storage_path: str) -> None:
        """删除图片文件或目录,忽略已经不存在的路径。"""

        path = Path(storage_path)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
