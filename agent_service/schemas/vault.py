"""
密码库 DTO。

功能说明:
本文件集中定义密码库 REST/gRPC 可复用的数据传输结构。创建、更新与导入
请求使用普通 dict 字段承载不同条目类型的业务字段,服务层负责校验。

使用说明:
API 层可直接把请求体转换为这些 DTO,再交给 VaultService。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


VaultItemType = Literal["login", "card", "identity", "secure_note"]


class VaultItemCreate(BaseModel):
    """创建密码库条目的请求。"""

    item_type: VaultItemType
    fields: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)


class VaultItemUpdate(BaseModel):
    """更新密码库条目的请求。"""

    item_type: VaultItemType | None = None
    fields: dict[str, Any] | None = None
    tags: list[str] | None = None
    asset_ids: list[str] | None = None


class VaultImportRequest(BaseModel):
    """导入 JSON 条目的请求。"""

    items: list[dict[str, Any]] = Field(default_factory=list)
