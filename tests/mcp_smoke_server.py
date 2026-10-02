"""Run the full production service container/REST/lifespan against an isolated temporary database for UI smoke.

Usage: python -X utf8 -m tests.mcp_smoke_server. No business or model data from the user's installation is edited.
"""
import socket
import tempfile
from pathlib import Path
import uvicorn
from fastapi import FastAPI
from agent_service.core.agent_config import AgentConfig
import agent_service.core.lifespan as lifecycle
from agent_service.api.rest import router

directory = Path(tempfile.mkdtemp(prefix="metaweave-mcp-smoke-"))
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    grpc_port = probe.getsockname()[1]
config = AgentConfig.load_config({"storage": {"project_root": str(directory), "base_data_dir": str(directory / "runtime"),
    "sqlite_path": str(directory / "runtime/test.db"), "knowledge_dir": str(directory / "knowledge"),
    "embedding_model_dir": str(directory / "runtime/models/embedding"),
    "rerank_model_dir": str(directory / "runtime/models/rerank"),
    "paddleocr_model_dir": str(directory / "runtime/models/paddleocr"),
    "assets_dir": str(directory / "runtime/assets"), "frontmatter_dir": str(directory / "runtime/frontmatter"),
    "chroma_persist_dir": str(directory / "runtime/chroma"), "relation_db_dir": str(directory / "runtime/db"),
    "vector_db_dir": str(directory / "runtime/vector"), "trash_dir": str(directory / "runtime/trash"),
    "log_dir": str(directory / "runtime/logs"), "mcp_server_config_dir": str(directory / "resources/mcp")},
    "server": {"grpc_host": "127.0.0.1", "grpc_port": grpc_port}},
    load_env=False, load_dotenv=False, ensure_directories=True, ensure_models=False)


def smoke_config():
    """Only substitute configuration; every production service and route remains real."""
    return config


lifecycle.load_startup_config = smoke_config
app = FastAPI(lifespan=lifecycle.agent_service_lifespan)
app.include_router(router)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8017, log_level="warning", access_log=False)
