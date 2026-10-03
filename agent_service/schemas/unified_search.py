"""四库联合搜索请求与响应 DTO。

使用说明：REST、gRPC 和前端共享本模块定义的来源常量与输出结构；业务搜索由
``UnifiedSearchService`` 执行，DTO 不包含检索逻辑。
"""

from __future__ import annotations

from typing import Any, Literal

from sqlmodel import Field, SQLModel

from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS

UnifiedSearchSource = Literal["files", "library", "components", "literature"]
UnifiedSearchMode = Literal["title", "fulltext", "semantic"]


class UnifiedSearchRequest(SQLModel):
    """描述一次四库联合搜索请求。"""

    user_id: str = Field(min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length)
    query: str = Field(min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length)
    sources: list[UnifiedSearchSource]
    fulltext: bool = True
    semantic: bool = False


class UnifiedSearchResultOut(SQLModel):
    """统一列表和分裂原生卡片共同消费的一条结果。"""

    id: str
    source: UnifiedSearchSource
    # 原始知识库身份使显式知识链接在切库和重载会话后仍能正确还原。
    library_id: str = ""
    title: str
    snippet: str = ""
    locator: str = ""
    updated_at: str = ""
    score: float = 0.0
    matched_modes: list[UnifiedSearchMode]
    item: dict[str, Any]


class UnifiedSearchResponse(SQLModel):
    """返回统一排序序列、四库分组和真实计数。"""

    query: str
    selected_sources: list[UnifiedSearchSource]
    fulltext: bool
    semantic: bool
    results: list[UnifiedSearchResultOut]
    groups: dict[str, list[UnifiedSearchResultOut]]
    counts: dict[str, int]
    total: int
