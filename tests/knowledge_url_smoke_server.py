"""显式知识 URL 浏览器验收服务，所有对象通过正式四库服务写入临时 SQLite。

使用说明：python -X utf8 -m uvicorn tests.knowledge_url_smoke_server:app --port 18072。
GET /knowledge/url-smoke/fixture 返回真实对象 ID 和链接；应用关闭后回收数据库与目录。
"""

from contextlib import asynccontextmanager
import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from sqlmodel import SQLModel

import agent_service.models  # noqa: F401 - register test-only database tables.
from agent_service.api.rest.deps import bind_application_services
from agent_service.api.rest.knowledge import router as knowledge_router
from agent_service.api.rest.library import router as library_router
from agent_service.api.rest.component_library import router as component_router
from agent_service.api.rest.smart_forms import router as forms_router
from agent_service.api.rest.unified_search import router as search_router
from agent_service.core.agent_config import AgentConfig
from agent_service.core.db.engine import get_database_engine
from agent_service.services.component_library.service import ComponentLibraryService
from agent_service.services.knowledge_library import KnowledgeLibraryService
from agent_service.services.library.service import LibraryService
from agent_service.services.memory.longterm_memory_service import LongTermMemoryService
from agent_service.services.settings.service import SettingsService
from agent_service.services.smart_form.service import SmartFormService
from agent_service.services.unified_search.service import UnifiedSearchService
from agent_service.tools.builtin.knowledge import get_knowledge_url, search_knowledge
from agent_service.tools.runtime_context import clear_tool_runtime, set_tool_runtime

SMOKE_USER_ID = "knowledge-url-smoke"


def _seed_services(config, engine) -> tuple[SimpleNamespace, dict]:
    """用正式 CRUD 创建四库资源，返回服务依赖和浏览器验收链接。"""

    memory = LongTermMemoryService(config=config, engine=engine, create_tables=False)
    settings = SettingsService(config=config, memory_service=memory)
    profile = settings.update_knowledge_dir(
        user_id=SMOKE_USER_ID, knowledge_dir=str(config.storage.base_data_dir / "knowledge"), name="知识链接验收库",
    )
    library_id = profile["active_knowledge_library"]["library_id"]
    files = KnowledgeLibraryService(config=config, memory_service=memory, settings_service=settings)
    library = LibraryService(
        config=config, settings_service=settings, knowledge_library_service=files,
        knowledge_graph_service=files.knowledge_graph_service,
    )
    components = ComponentLibraryService(settings_service=settings)
    forms = SmartFormService(engine=engine, create_tables=False)
    search = UnifiedSearchService(
        settings_service=settings, knowledge_library_service=files, library_service=library,
        component_library_service=components, smart_form_service=forms, retrieval_service=None,
    )
    file_path = "资料/文件 # &.md"
    files.write_file(user_id=SMOKE_USER_ID, path=file_path, content="# 链接验收\nUTF-8 本地文件\n")
    # 复用项目多模态测试的有效微型 PNG，通过正式上传与图书 CRUD 提供原生图片封面。
    files.write_uploaded_file(
        user_id=SMOKE_USER_ID, filename="知识链接封面.png", relative_dir="资料",
        content=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="),
    )
    book = library.create_item(
        user_id=SMOKE_USER_ID, content_type="knowledge_file", source_path="资料/知识链接封面.png",
        title="显式挂载图书", description="原生图书卡片", cover_mode="source_image",
    )["item"]
    collection = library.create_collection(user_id=SMOKE_USER_ID, title="显式挂载集锦")["item"]
    component = components.create_component(
        user_id=SMOKE_USER_ID, tag="cards", filename="知识链接.vue",
        source="<template><article style=\"padding:12px\">显式挂载组件</article></template>",
    )["component"]
    literature_path = "资料/知识链接文献.md"
    files.write_file(user_id=SMOKE_USER_ID, path=literature_path, content="文献正文来自正式文件服务。\n")
    form = forms.save_form(
        user_id=SMOKE_USER_ID, library_id=library_id, form_kind="literature", asset_dir="资料",
        form={
            "title": "知识链接文献表",
            "columns": [
                {"id": "literature_file", "title": "文献上传", "type": "file"},
                {"id": "literature_content", "title": "文献内容", "type": "readonly_text"},
                {"id": "title", "title": "标题", "type": "smart_text"},
            ],
            "rows": [{"id": "row-smoke", "cells": {
                "literature_file": {"value": "知识链接文献.md", "fileName": "知识链接文献.md", "assetPath": literature_path},
                "literature_content": {"value": "原生文献块：知识链接验收正文。"},
                "title": {"value": "显式挂载文献"},
            }}],
        },
    )
    identities = {
        "files": file_path, "book": book["item_id"], "collection": collection["item_id"],
        "components": component["component_id"], "literature": f"{form['form_id']}:row-smoke",
    }
    links = {}
    citations = {}
    # This URL-only smoke never invokes vector providers; all knowledge services are real.
    set_tool_runtime(
        config=config, user_id=SMOKE_USER_ID, session_id="knowledge-url-smoke",
        memory_service=memory, unified_search_service=search, database_engine=engine,
        retrieval_service=SimpleNamespace(), embedding_service=SimpleNamespace(), citation_map=citations,
    )
    try:
        search_knowledge("显式", fulltext=False, semantic=False)
        for label, resource_id in identities.items():
            source = "library" if label in {"book", "collection"} else label
            result = search.resolve_knowledge(user_id=SMOKE_USER_ID, source=source, id=resource_id)
            citation_id = next((key for key, value in citations.items() if (
                value.get("search_result", {}).get("source") == source
                and value.get("search_result", {}).get("id") == resource_id
            )), "")
            links[label] = {
                "result": result,
                "url": get_knowledge_url(citation_id=citation_id) if citation_id else get_knowledge_url(source=source, id=resource_id),
            }
    finally:
        clear_tool_runtime()
    services = SimpleNamespace(
        settings_service=settings, knowledge_library_service=files, library_service=library,
        component_library_service=components, smart_form_service=forms, unified_search_service=search,
    )
    return services, {
        "user_id": SMOKE_USER_ID, "library_id": library_id,
        "knowledge_dir": profile["active_knowledge_library"]["knowledge_dir"], "links": links,
        "citation_map": citations,
    }


@asynccontextmanager
async def lifespan(app):
    """临时数据由测试应用独占，退出时关闭连接并清理所有业务资料。"""

    with TemporaryDirectory(prefix="mw-knowledge-url-") as directory:
        root = Path(directory)
        config = AgentConfig.load_config(
            {"storage": {"project_root": str(root), "base_data_dir": str(root / "runtime")}},
            load_env=False, load_dotenv=False, ensure_models=False,
        )
        engine = get_database_engine(config)
        SQLModel.metadata.create_all(engine)
        try:
            app.state.services, app.state.fixture = _seed_services(config, engine)
            yield
        finally:
            engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(search_router, dependencies=[Depends(bind_application_services)])
app.include_router(knowledge_router, dependencies=[Depends(bind_application_services)])
app.include_router(library_router, dependencies=[Depends(bind_application_services)])
app.include_router(component_router, dependencies=[Depends(bind_application_services)])
app.include_router(forms_router, dependencies=[Depends(bind_application_services)])


@app.get("/knowledge/url-smoke/fixture")
def fixture() -> dict:
    """返回临时业务库中真实对象的链接，供开发代理和浏览器组件共同验收。"""

    return app.state.fixture
