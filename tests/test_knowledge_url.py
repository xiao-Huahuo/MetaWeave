"""显式知识块 URL 的四库解析、用户隔离与工具合同回归测试。

使用说明：单独运行本文件，不加载模型；每条链接读取正式来源 DTO，而非搜索缓存。
"""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from agent_service.api.rest.deps import bind_application_services
from agent_service.api.rest.unified_search import router as unified_search_router
from agent_service.services.settings.mcp_settings import selected_library
from agent_service.services.unified_search.service import UnifiedSearchService
from agent_service.tools import ToolRegistry
from agent_service.tools.builtin import knowledge


class _Settings:
    """模拟正式 SettingsService 的请求级知识库归属检查。"""

    def ensure_user_profile(self, *, user_id: str) -> dict:
        """只允许本人使用自己拥有的知识库。"""

        selection = selected_library.get()
        if user_id != "用户 & 1" or (selection and selection not in {
            (user_id, "原库 & 1"), (user_id, "当前库"),
        }):
            raise PermissionError("知识库无访问权限")
        library_id = selection[1] if selection else "当前库"
        return {"active_knowledge_library": {
            "library_id": library_id, "knowledge_dir": "D:/knowledge/current",
        }}


class _Sources:
    """提供正式四库列表形态，记录真实查询用户及库作用域。"""

    def __init__(self) -> None:
        """初始化最小原生卡片数据和来源访问记录。"""

        self.calls: list[tuple[str, str, object]] = []
        self.file = {"name": "文件 # &.md", "path": "目录/文件 # &.md", "isDir": False, "size": 7}
        self.book = {"item_id": "book & 1", "title": "图书", "display_title": "图书", "item_type": "book"}
        self.component = {"component_id": "cards/按钮 & #.vue", "title": "按钮", "source": "<template>按钮</template>"}
        self.entry = {"form_id": "form-1", "row_id": "row-1", "title": "文献", "asset_path": "paper.pdf"}

    def _record(self, source: str, user_id: str) -> None:
        """确保解析不会绕过当前请求归属检查。"""

        self.calls.append((source, user_id, selected_library.get()))

    def list_files(self, *, user_id: str) -> list:
        """返回文件库树形原生节点。"""

        self._record("files", user_id)
        return [self.file]

    def list_items(self, *, user_id: str, parent_id: str) -> dict:
        """返回图书馆根层级原生条目。"""

        self._record("library", user_id)
        return {"items": [self.book] if not parent_id else []}

    def list_components(self, *, user_id: str, tag: str) -> dict:
        """返回组件库原生源码卡片。"""

        self._record("components", user_id)
        return {"components": [self.component]}

    def list_literature_entries(self, *, user_id: str, library_id: str) -> list:
        """返回文献库原生摘要卡片。"""

        self._record("literature", user_id)
        assert library_id == selected_library.get()[1]
        return [self.entry]

    def list_forms(self, **kwargs) -> list:
        """返回文献表元数据。"""

        return [{"form_id": "form-1", "title": "研究文献"}]

    def get_form(self, **kwargs) -> dict:
        """返回与摘要匹配的正式文献行。"""

        return {"form": {"title": "研究文献", "rows": [{"id": "row-1", "cells": {}}]}}


def _service(sources: _Sources) -> UnifiedSearchService:
    """构造只依赖正式来源入口、没有检索或引用缓存的服务。"""

    return UnifiedSearchService(
        settings_service=_Settings(), knowledge_library_service=sources,
        library_service=sources, component_library_service=sources,
        smart_form_service=sources, retrieval_service=None,
    )


@pytest.mark.parametrize("source,resource_id,attribute", [
    ("files", "目录/文件 # &.md", "file"),
    ("library", "book & 1", "book"),
    ("components", "cards/按钮 & #.vue", "component"),
    ("literature", "form-1:row-1", "entry"),
])
def test_resolve_uses_real_source_dto_without_search_or_citation_cache(source, resource_id, attribute) -> None:
    """四库知识 URL 无需调用搜索或依赖会话引用便能还原原生 DTO。"""

    sources = _Sources()
    result = _service(sources).resolve_knowledge(
        user_id="用户 & 1", source=source, id=resource_id, library_id="原库 & 1",
    )
    assert result["item"] == getattr(sources, attribute)
    assert result["id"] == resource_id
    assert result["source"] == source
    assert result["library_id"] == "原库 & 1"
    assert result["matched_modes"] == []
    assert sources.calls == [(source, "用户 & 1", ("用户 & 1", "原库 & 1"))]
    assert selected_library.get() is None


def test_resolve_rejects_missing_resources_and_foreign_library_before_data_read() -> None:
    """对象必须真实存在，其他用户的库不得被读取。"""

    sources = _Sources()
    service = _service(sources)
    with pytest.raises(FileNotFoundError):
        service.resolve_knowledge(user_id="用户 & 1", source="components", id="missing.vue")
    sources.calls.clear()
    with pytest.raises(PermissionError):
        service.resolve_knowledge(user_id="用户 & 1", source="library", id="book & 1", library_id="他人库")
    assert sources.calls == []
    assert selected_library.get() is None
    with pytest.raises(ValueError):
        service.resolve_knowledge(user_id="用户 & 1", source="fake", id="anything")


def test_tool_encodes_special_characters_and_keeps_file_url_compatibility(monkeypatch) -> None:
    """统一工具返回可安全放进 Markdown 的 URL，文件仍使用旧 raw 路由。"""

    runtime = SimpleNamespace(user_id="用户 & 1", citation_map={}, unified_search_service=_service(_Sources()))
    monkeypatch.setattr(knowledge, "get_tool_runtime", lambda: runtime)
    file_url = knowledge.get_knowledge_url(path="目录/文件 # &.md")
    assert urlsplit(file_url).path == "/knowledge/files/raw"
    assert parse_qs(urlsplit(file_url).query) == {"user_id": [runtime.user_id], "path": ["目录/文件 # &.md"]}
    component_url = knowledge.get_knowledge_url(source="components", id="cards/按钮 & #.vue")
    assert urlsplit(component_url).path == "/knowledge/resolve"
    assert parse_qs(urlsplit(component_url).query) == {
        "user_id": [runtime.user_id], "source": ["components"],
        "id": ["cards/按钮 & #.vue"], "library_id": ["当前库"],
    }
    assert "不存在" in knowledge.get_knowledge_url(source="components", id="missing.vue")


def test_tool_resolves_search_citation_to_owned_origin_library(monkeypatch) -> None:
    """指定 K 引用只获取链接，不自动采纳引用或挂载知识块。"""

    sources = _Sources()
    citation = {"search_result": {"source": "library", "id": "book & 1", "library_id": "原库 & 1"}}
    runtime = SimpleNamespace(user_id="用户 & 1", citation_map={"K1": citation}, unified_search_service=_service(sources))
    monkeypatch.setattr(knowledge, "get_tool_runtime", lambda: runtime)
    url = knowledge.get_knowledge_url(citation_id="[K1]")
    assert parse_qs(urlsplit(url).query)["library_id"] == ["原库 & 1"]
    assert "adopted_by_default" not in citation
    assert sources.calls == [("library", runtime.user_id, (runtime.user_id, "原库 & 1"))]
    assert "无效" in knowledge.get_knowledge_url(citation_id="N1")


def test_rest_resolves_decoded_identifiers_and_maps_missing_or_foreign_resources() -> None:
    """REST 与原生服务共同提供稳定知识链接，并映射 404/403/422。"""

    sources = _Sources()
    app = FastAPI()
    app.state.services = SimpleNamespace(unified_search_service=_service(sources))
    router = APIRouter(dependencies=[Depends(bind_application_services)])
    router.include_router(unified_search_router)
    app.include_router(router)
    params = {"user_id": "用户 & 1", "source": "components", "id": "cards/按钮 & #.vue", "library_id": "原库 & 1"}
    with TestClient(app) as client:
        response = client.get("/knowledge/resolve", params=params)
        assert response.status_code == 200
        assert response.json()["item"] == sources.component
        assert client.get("/knowledge/resolve", params={**params, "id": "missing.vue"}).status_code == 404
        assert client.get("/knowledge/resolve", params={**params, "library_id": "他人库"}).status_code == 403
        assert client.get("/knowledge/resolve", params={**params, "source": "fake"}).status_code == 422


def test_unified_url_tool_is_registered_for_model_discovery() -> None:
    """新工具必须进入正式注册表和模型参数合同。"""

    registry = ToolRegistry.with_builtin_tools()
    definition = registry.get("get_knowledge_url")
    assert definition is not None
    assert set(definition.args_schema["properties"]) == {"source", "id", "path", "citation_id"}
    assert "get_knowledge_url" in {tool.name for tool in registry.to_langchain_tools()}
    assert "get_knowledge_file_url" not in {tool.name for tool in registry.to_langchain_tools()}
    assert not hasattr(knowledge, "get_knowledge_file_url")


def test_real_four_library_services_restore_seeded_knowledge_urls() -> None:
    """真实临时数据库与正式 CRUD 服务生成的链接通过正式 REST 还原原生卡片。"""

    from tests.knowledge_url_smoke_server import app

    with TestClient(app) as client:
        fixture = client.get("/knowledge/url-smoke/fixture").json()
        assert set(fixture["links"]) == {"files", "book", "collection", "components", "literature"}
        for label, link in fixture["links"].items():
            response = client.get(link["url"])
            assert response.status_code == 200, (label, response.text)
            if label == "files":
                assert "UTF-8 本地文件" in response.text
            else:
                assert response.json()["item"] == link["result"]["item"]
                assert response.json()["library_id"] == fixture["library_id"]


def test_raw_file_library_scope_reads_owned_original_library_after_switching(tmp_path) -> None:
    """历史原生图书封面必须读取原库文件，且不允许借 library_id 读取其他用户的库。"""

    from tests.knowledge_url_smoke_server import app

    with TestClient(app) as client:
        fixture = client.get("/knowledge/url-smoke/fixture").json()
        services = app.state.services
        user_id = fixture["user_id"]
        file_path = fixture["links"]["files"]["result"]["id"]
        # 在第二个真实库写同名文件，使漏传或忽略原库身份的读取可被准确复现。
        next_profile = services.settings_service.update_knowledge_dir(user_id=user_id, knowledge_dir=str(tmp_path / "next-library"))
        services.knowledge_library_service.write_file(user_id=user_id, path=file_path, content="同名文件属于新库。")
        params = {"user_id": user_id, "path": file_path, "library_id": fixture["library_id"]}
        historical = client.get("/knowledge/files/raw", params=params)
        assert historical.status_code == 200
        assert "UTF-8 本地文件" in historical.text
        current = client.get("/knowledge/files/raw", params={"user_id": user_id, "path": file_path})
        assert current.status_code == 200
        assert current.text == "同名文件属于新库。"
        assert client.get("/knowledge/files/raw", params={**params, "path": "missing.md"}).status_code == 404
        foreign = services.settings_service.update_knowledge_dir(user_id="foreign-user", knowledge_dir=str(tmp_path / "foreign-library"))
        response = client.get("/knowledge/files/raw", params={**params, "library_id": foreign["active_knowledge_library"]["library_id"]})
        assert response.status_code == 403
        assert services.settings_service.ensure_user_profile(user_id=user_id)["active_library_id"] == next_profile["active_library_id"]
        assert selected_library.get() is None
