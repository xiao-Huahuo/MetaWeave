"""四库联合搜索与显式知识 URL 解析 REST 端点。

使用说明：前端通过 ``GET /search`` 传入查询、全文/语义开关和逗号分隔的来源。
``GET /knowledge/resolve`` 按用户、库身份和稳定对象 ID 还原原生知识块。
本层只校验参数、调用领域服务并映射业务错误。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from agent_service.api.rest.deps import _require_unified_search_service
from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS
from agent_service.schemas.unified_search import UnifiedSearchResponse, UnifiedSearchResultOut
from agent_service.services.unified_search.service import SEARCH_SOURCES

router = APIRouter()


@router.get("/knowledge/resolve", response_model=UnifiedSearchResultOut)
async def resolve_knowledge_url(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    source: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    library_id: str = Query(default=""),
) -> dict[str, Any]:
    """从用户拥有的库读取显式链接对象，不依赖会话引用映射或搜索结果。"""

    try:
        return await run_in_threadpool(
            _require_unified_search_service().resolve_knowledge,
            user_id=user_id, source=source, id=id, library_id=library_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/search", response_model=UnifiedSearchResponse)
async def search_all_libraries(
    user_id: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    query: str = Query(..., min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length),
    sources: str = Query(default=",".join(SEARCH_SOURCES)),
    fulltext: bool = Query(default=True),
    semantic: bool = Query(default=False),
) -> dict[str, Any]:
    """严格按照用户选中的库和搜索能力执行联合搜索。"""

    selected_sources = {source.strip() for source in sources.split(",") if source.strip()}
    try:
        return await run_in_threadpool(
            _require_unified_search_service().search,
            user_id=user_id,
            query=query,
            sources=selected_sources,
            fulltext=fulltext,
            semantic=semantic,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
