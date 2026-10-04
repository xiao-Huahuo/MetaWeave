"""
密码库 REST 端点。

功能说明:
本模块提供密码库共享登录会话鉴权、条目 CRUD、回收站、导入导出和
图片资产访问接口。所有 /vault 条目接口均要求 Authorization Bearer token。

使用说明:
前端先调用 /vault/status 判断是否需要设置主密码,再调用 /vault/setup 或
/vault/unlock 获取 30 分钟 vault token。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS
from agent_service.api.rest.deps import _require_vault_service, _require_auth_service, _require_auth_session
from agent_service.schemas.vault import VaultImportRequest, VaultItemCreate, VaultItemUpdate
from agent_service.api.rest.file_security import untrusted_file_headers

router = APIRouter()


def _vault_session(authorization: str) -> Any:
    """从 Authorization 头解析密码库会话。"""

    try:
        from agent_service.services.vault.service import VaultSession
        identity = _require_auth_service().verify_session(authorization) if authorization else _require_auth_session()
        return VaultSession(user_id=identity.user_id, fernet_key=identity.fernet_key, password_version=identity.password_version)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/vault/status")
async def vault_status(authorization: str = Header("", alias="Authorization")) -> dict[str, Any]:
    """The shared account session unlocks this account's existing encrypted vault."""
    return await run_in_threadpool(_require_vault_service().status, session=_vault_session(authorization))


@router.get("/vault/items")
async def list_vault_items(
    authorization: str = Header("", alias="Authorization"),
    query: str = Query(""),
    tag: str = Query(""),
    item_type: str = Query(""),
    trash: bool = Query(False),
) -> dict[str, Any]:
    """列出已解锁密码库中的条目。"""

    session = _vault_session(authorization)
    try:
        return await run_in_threadpool(
            _require_vault_service().list_items,
            session=session,
            query=query,
            tag=tag,
            item_type=item_type,
            trash=trash,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/vault/tags")
async def list_vault_tags(authorization: str = Header("", alias="Authorization")) -> dict[str, Any]:
    """列出密码库标签。"""

    return await run_in_threadpool(_require_vault_service().list_tags, session=_vault_session(authorization))


@router.post("/vault/items")
async def create_vault_item(
    body: VaultItemCreate,
    authorization: str = Header("", alias="Authorization"),
) -> dict[str, Any]:
    """创建密码库条目。"""

    try:
        return await run_in_threadpool(
            _require_vault_service().create_item,
            session=_vault_session(authorization),
            item_type=body.item_type,
            fields=body.fields,
            tags=body.tags,
            asset_ids=body.asset_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/vault/items/{item_id}")
async def get_vault_item(item_id: str, authorization: str = Header("", alias="Authorization")) -> dict[str, Any]:
    """读取密码库条目详情。"""

    try:
        return await run_in_threadpool(_require_vault_service().get_item, session=_vault_session(authorization), item_id=item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/vault/items/{item_id}")
async def update_vault_item(
    item_id: str,
    body: VaultItemUpdate,
    authorization: str = Header("", alias="Authorization"),
) -> dict[str, Any]:
    """更新密码库条目。"""

    try:
        return await run_in_threadpool(
            _require_vault_service().update_item,
            session=_vault_session(authorization),
            item_id=item_id,
            payload=body.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/vault/items/trash")
async def trash_vault_items(body: dict[str, Any], authorization: str = Header("", alias="Authorization")) -> dict[str, Any]:
    """将条目移入回收站。"""

    return await run_in_threadpool(
        _require_vault_service().move_to_trash,
        session=_vault_session(authorization),
        item_ids=[str(item) for item in body.get("item_ids", [])],
    )


@router.post("/vault/items/restore")
async def restore_vault_items(body: dict[str, Any], authorization: str = Header("", alias="Authorization")) -> dict[str, Any]:
    """恢复回收站条目。"""

    return await run_in_threadpool(
        _require_vault_service().restore_items,
        session=_vault_session(authorization),
        item_ids=[str(item) for item in body.get("item_ids", [])],
    )


@router.delete("/vault/items")
async def purge_vault_items(body: dict[str, Any], authorization: str = Header("", alias="Authorization")) -> dict[str, Any]:
    """永久删除密码库条目。"""

    return await run_in_threadpool(
        _require_vault_service().purge_items,
        session=_vault_session(authorization),
        item_ids=[str(item) for item in body.get("item_ids", [])],
    )


@router.post("/vault/items/purge")
async def purge_vault_items_post(body: dict[str, Any], authorization: str = Header("", alias="Authorization")) -> dict[str, Any]:
    """用 POST 永久删除密码库条目,方便前端携带 JSON body。"""

    return await purge_vault_items(body=body, authorization=authorization)


@router.post("/vault/export")
async def export_vault_items(body: dict[str, Any], authorization: str = Header("", alias="Authorization")) -> dict[str, Any]:
    """导出全部或选中的密码库条目。"""

    return await run_in_threadpool(
        _require_vault_service().export_items,
        session=_vault_session(authorization),
        item_ids=[str(item) for item in body.get("item_ids", [])] or None,
    )


@router.post("/vault/import")
async def import_vault_items(body: VaultImportRequest, authorization: str = Header("", alias="Authorization")) -> dict[str, Any]:
    """导入密码库 JSON。"""

    return await run_in_threadpool(
        _require_vault_service().import_items,
        session=_vault_session(authorization),
        raw_items=body.items,
    )


@router.post("/vault/assets")
async def upload_vault_asset(
    authorization: str = Header("", alias="Authorization"),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """上传密码库图片。"""

    content = await file.read()
    try:
        return await run_in_threadpool(
            _require_vault_service().upload_asset,
            session=_vault_session(authorization),
            filename=file.filename or "image.bin",
            content=content,
            mime_type=file.content_type or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/vault/assets/{asset_id}")
async def get_vault_asset(asset_id: str, authorization: str = Header("", alias="Authorization")) -> FileResponse:
    """读取受密码库 token 保护的图片。"""

    try:
        asset = await run_in_threadpool(_require_vault_service().get_asset, session=_vault_session(authorization), asset_id=asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(asset.storage_path, media_type=asset.mime_type, filename=asset.file_name,
                        headers=untrusted_file_headers())
