"""
模型管理与编译管理 REST/gRPC 对齐测试。

使用说明:
验证两个管理面板通过正式后端服务获得同形数据，用户标识缺失时保持传输层校验。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import inspect
from types import SimpleNamespace
from typing import Any

import grpc
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct

from agent_service.api.grpc.agent_service_pb2_grpc import (
    AgentServiceStub,
    add_AgentServiceServicer_to_server,
)
from agent_service.api.grpc.servicer import AgentServiceServicer
from agent_service.api.rest import settings as settings_rest
from agent_service.core.agent_config import AgentConfig


class _ModelManagementStub:
    """返回一条带真实管理字段形状的模型记录。"""

    def get_management_status(self, *, user_id: str) -> dict[str, Any]:
        """保留 user_id 以验证 REST/gRPC 参数一致。"""

        return {"models": [{
            "key": "embedding", "name": "demo", "path": "D:/models/demo",
            "size_bytes": 12, "file_count": 3, "enabled": True, "active": True,
            "downloaded": True, "status": "ready", "progress": {"status": "idle"},
            "details": {"user_id": user_id},
        }]}

    def initialize_after_startup(self, *, user_id: str) -> dict[str, str]:
        """返回不会触发任何真实模型工作的初始化结果。"""

        return {"status": f"started:{user_id}"}


class _SettingsStub:
    """提供模型与 DSH用户偏好的纯内存替身。"""

    dsh_enabled = False

    def get_model_preferences(self, *, user_id: str) -> dict[str, object]:
        """返回默认关闭状态。"""

        return {"user_id": user_id, "auto_download_enabled": False}

    def save_model_preferences(self, *, user_id: str, auto_download_enabled: bool) -> dict[str, object]:
        """原样返回显式保存值。"""

        return {"user_id": user_id, "auto_download_enabled": auto_download_enabled}

    def get_knowledge_ingestion_config(self, *, user_id: str) -> dict[str, object]:
        """返回默认关闭的识图设置。"""

        return {"user_id": user_id, "ocr_enabled": False, "vision_understanding_enabled": False}

    def save_knowledge_ingestion_config(self, *, user_id: str, **payload: object) -> dict[str, object]:
        """返回 gRPC 传入的识图覆盖值。"""

        result = {"user_id": user_id, **{key: value for key, value in payload.items() if value is not None}}
        if "dsh_coding_agent_enabled" in result:
            self.dsh_enabled = bool(result["dsh_coding_agent_enabled"])
        return result

    def is_dsh_coding_agent_enabled_for_user(self, *, user_id: str) -> bool:  # noqa: ARG002
        """返回当前测试显式保存的 DSH开关。"""

        return self.dsh_enabled


class _DshRuntimeStub:
    """记录 DSH后台安装是否被启动。"""

    def __init__(self) -> None:
        self.start_calls = 0

    def start_install(self) -> dict[str, object]:
        """模拟立即返回的后台安装任务。"""

        self.start_calls += 1
        return {"status": "verifying"}


class _LatexManagementStub:
    """返回系统 MiKTeX 管理详情。"""

    def get_management_status(self) -> dict[str, Any]:
        """返回编译器来源、路径、大小和引擎。"""

        return {
            "status": "ready", "source": "system", "distribution": "MiKTeX",
            "distribution_path": "D:/MiKTeX", "size_bytes": 100, "file_count": 20,
            "default_engine": "pdflatex", "engines": [{"name": "pdflatex", "available": True}],
        }


class _AgentStub:
    """提供 gRPC servicer 所需的最小 Agent。"""

    config = SimpleNamespace()

    def close(self) -> None:
        """测试无需释放资源。"""


def _struct(payload: dict[str, object]) -> Struct:
    """构造通用 protobuf 请求。"""

    return ParseDict(payload, Struct())


def test_management_rest_returns_service_owned_details(monkeypatch: Any) -> None:
    """REST 管理接口不得由前端拼接模型或编译器详情。"""

    monkeypatch.setattr(settings_rest, "_require_model_management_service", lambda: _ModelManagementStub())
    monkeypatch.setattr(settings_rest, "_require_settings_service", lambda: _SettingsStub())
    monkeypatch.setattr(settings_rest, "_require_latex_service", lambda: _LatexManagementStub())
    app = FastAPI()
    app.include_router(settings_rest.router)
    client = TestClient(app)

    models = client.get("/settings/models/management", params={"user_id": "u1"})
    compiler = client.get("/settings/latex/management", params={"user_id": "u1"})

    assert models.status_code == 200
    assert models.json()["models"][0]["details"]["user_id"] == "u1"
    assert compiler.status_code == 200
    assert compiler.json()["source"] == "system"


def test_storage_management_reads_run_in_fastapi_threadpool() -> None:
    """四个独立磁盘来源不得在主事件循环串行阻塞其他管理区。"""

    assert not inspect.iscoroutinefunction(settings_rest.get_storage_config)
    assert not inspect.iscoroutinefunction(settings_rest.get_model_management)
    assert not inspect.iscoroutinefunction(settings_rest.get_latex_management)
    assert not inspect.iscoroutinefunction(settings_rest.get_dsh_sdk_management)


def test_model_preferences_and_initialization_match_over_rest_and_grpc(monkeypatch: Any) -> None:
    """模型偏好与启动后初始化必须通过 REST 和 gRPC 暴露相同字段。"""

    model_service = _ModelManagementStub()
    settings_service = _SettingsStub()
    monkeypatch.setattr(settings_rest, "_require_model_management_service", lambda: model_service)
    monkeypatch.setattr(settings_rest, "_require_settings_service", lambda: settings_service)
    app = FastAPI()
    app.include_router(settings_rest.router)
    client = TestClient(app)

    rest_saved = client.put(
        "/settings/models/preferences",
        json={"user_id": "u1", "auto_download_enabled": True},
    )
    rest_initialized = client.post("/settings/models/initialize", json={"user_id": "u1"})

    server = grpc.server(ThreadPoolExecutor(max_workers=1))
    add_AgentServiceServicer_to_server(
        AgentServiceServicer(
            agent=_AgentStub(),  # type: ignore[arg-type]
            session_service=SimpleNamespace(),  # type: ignore[arg-type]
            settings_service=settings_service,  # type: ignore[arg-type]
            model_management_service=model_service,  # type: ignore[arg-type]
        ),
        server,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        stub = AgentServiceStub(channel)
        grpc_saved = MessageToDict(stub.SaveModelPreferences(_struct({
            "user_id": "u1", "auto_download_enabled": True,
        }), timeout=5))
        grpc_initialized = MessageToDict(stub.InitializeModels(_struct({"user_id": "u1"}), timeout=5))
    finally:
        channel.close()
        server.stop(0).wait(timeout=5)

    assert rest_saved.json() == {"user_id": "u1", "auto_download_enabled": True}
    assert grpc_saved == rest_saved.json()
    assert rest_initialized.json() == {"status": "started:u1"}
    assert grpc_initialized == rest_initialized.json()


def test_basic_agent_settings_are_available_over_grpc() -> None:
    """gRPC面板必须能保存与 REST同形的识图和 DSH开关。"""

    settings_service = _SettingsStub()
    server = grpc.server(ThreadPoolExecutor(max_workers=1))
    add_AgentServiceServicer_to_server(
        AgentServiceServicer(
            agent=_AgentStub(),  # type: ignore[arg-type]
            session_service=SimpleNamespace(),  # type: ignore[arg-type]
            settings_service=settings_service,  # type: ignore[arg-type]
        ),
        server,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        payload = MessageToDict(AgentServiceStub(channel).SaveKnowledgeIngestionConfig(_struct({
            "user_id": "u1", "vision_understanding_enabled": True,
            "dsh_coding_agent_enabled": True,
        }), timeout=5))
    finally:
        channel.close()
        server.stop(0).wait(timeout=5)

    assert payload["user_id"] == "u1"
    assert payload["vision_understanding_enabled"] is True
    assert payload["dsh_coding_agent_enabled"] is True


def test_dsh_setting_starts_background_install_and_initializes_after_startup(monkeypatch: Any) -> None:
    """开启 DSH后应持久化并异步安装，启动后初始化复用同一后台任务。"""

    settings_service = _SettingsStub()
    runtime = _DshRuntimeStub()
    monkeypatch.setattr(settings_rest, "_require_settings_service", lambda: settings_service)
    monkeypatch.setattr(settings_rest, "_require_dsh_runtime_manager", lambda: runtime)
    app = FastAPI()
    app.include_router(settings_rest.router)
    client = TestClient(app)

    saved = client.put("/settings/profile/ingestion", json={
        "user_id": "u1", "dsh_coding_agent_enabled": True,
    })
    initialized = client.post("/settings/sdks/dsh/initialize", json={"user_id": "u1"})

    assert saved.json()["dsh_coding_agent_enabled"] is True
    assert initialized.json() == {"status": "verifying", "enabled": True}
    assert runtime.start_calls == 2


def test_management_grpc_matches_rest_fields() -> None:
    """gRPC 暴露与 REST 相同的模型和编译器字段。"""

    server = grpc.server(ThreadPoolExecutor(max_workers=2))
    add_AgentServiceServicer_to_server(
        AgentServiceServicer(
            agent=_AgentStub(),  # type: ignore[arg-type]
            session_service=SimpleNamespace(),  # type: ignore[arg-type]
            model_management_service=_ModelManagementStub(),  # type: ignore[arg-type]
            latex_service=_LatexManagementStub(),  # type: ignore[arg-type]
        ),
        server,
    )
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    try:
        stub = AgentServiceStub(channel)
        models = MessageToDict(stub.GetModelManagement(_struct({"user_id": "u1"}), timeout=5))
        compiler = MessageToDict(stub.GetLatexManagement(_struct({"user_id": "u1"}), timeout=5))
    finally:
        channel.close()
        server.stop(0).wait(timeout=5)

    assert models["models"][0]["path"] == "D:/models/demo"
    assert compiler["distribution"] == "MiKTeX"


def test_legacy_local_qwen_download_and_load_routes_are_rejected(tmp_path, monkeypatch: Any) -> None:
    """模型管理 REST 不得再接受已删除的本地 Qwen 下载或加载请求。"""

    config = AgentConfig.load_config(
        {"storage": {"base_data_dir": str(tmp_path / "runtime")}},
        load_env=False,
        ensure_directories=True,
        ensure_models=False,
    )
    monkeypatch.setattr(settings_rest, "_require_settings_service", lambda: SimpleNamespace(config=config))
    app = FastAPI()
    app.include_router(settings_rest.router)
    client = TestClient(app)

    download = client.post("/settings/models/download", json={"model": "local_qwen"})
    load = client.post("/settings/models/load", json={"model": "local_qwen"})

    assert download.status_code == 422
    assert load.status_code == 422
