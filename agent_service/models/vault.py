"""
密码库数据库模型。

功能说明:
本文件定义密码库加密条目、标签关系和图片资产表。统一登录账号管理主密码。
敏感业务字段不以明文列保存,统一放入 VaultItem.encrypted_payload。

使用说明:
Alembic 在应用启动前创建和升级这些表,REST 和 gRPC 层只通过服务层读写,
不得直接操作模型。
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Column, Field, SQLModel, Text

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS
from agent_service.models.session import utc_now


class VaultItem(SQLModel, table=True):
    """密码库加密条目。"""

    __tablename__ = "vault_items"

    item_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length)
    user_id: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    item_type: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.short_type_max_length)
    encrypted_payload: str = Field(sa_column=Column(Text))
    deleted_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class VaultTag(SQLModel, table=True):
    """密码库标签。"""

    __tablename__ = "vault_tags"

    tag_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length)
    user_id: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    name: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    created_at: datetime = Field(default_factory=utc_now)


class VaultItemTag(SQLModel, table=True):
    """密码库条目与标签的多对多关系。"""

    __tablename__ = "vault_item_tags"

    item_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length)
    tag_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length)


class VaultAsset(SQLModel, table=True):
    """密码库受鉴权保护的图片资产。"""

    __tablename__ = "vault_assets"

    asset_id: str = Field(primary_key=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length)
    item_id: str = Field(default="", index=True, max_length=DEFAULT_BUSINESS_LIMITS.standard_id_max_length,
                         description="Attached item; removed parents retain durable pending file cleanup, empty means an unattached upload.")
    user_id: str = Field(index=True, max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    mime_type: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.medium_name_max_length)
    file_name: str = Field(default="", max_length=DEFAULT_BUSINESS_LIMITS.summary_max_length)
    storage_path: str = Field(max_length=DEFAULT_BUSINESS_LIMITS.path_max_length)
    size: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)
