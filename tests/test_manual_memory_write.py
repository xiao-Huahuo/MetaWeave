"""Regression tests for independent manual memories and failed-write preservation.

Run ``python -m pytest tests/test_manual_memory_write.py``. Tests use temporary
SQLite storage and real keyword retrieval without loading embedding models.
"""

from types import SimpleNamespace

import pytest
from sqlmodel import create_engine

from agent_service.core.agent_config import AgentConfig
from agent_service.models.longterm_memory_spec import LongTermMemorySpec
from agent_service.services.memory.longterm_memory_service import LongTermMemoryService
from agent_service.services.memory.manual_write import write_manual_memory
from agent_service.services.memory.rag.hybrid_retrieval import HybridRetrievalService


@pytest.fixture
def memory_service(tmp_path):
    """Provide the real memory service with an isolated database and no models."""
    config = AgentConfig.load_config(
        {"storage": {"base_data_dir": str(tmp_path), "sqlite_path": str(tmp_path / "memory.db")}},
        load_env=False, load_dotenv=False, ensure_directories=False, ensure_models=False,
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'memory.db'}")
    LongTermMemorySpec.__table__.create(engine)
    try:
        yield LongTermMemoryService(config=config, engine=engine, create_tables=False)
    finally:
        engine.dispose()


def test_agent_and_mcp_writes_keep_independent_memories_retrievable(memory_service, monkeypatch):
    """Both write adapters must preserve unrelated facts of the same default type."""
    from agent_service.services.mcp_server.catalog import execute_business
    from agent_service.tools.builtin import memory as memory_tools

    config = memory_service.config
    runtime = SimpleNamespace(
        config=config, memory_service=memory_service, embedding_service=None,
        user_id="owner", session_id="first_session",
    )
    monkeypatch.setattr(memory_tools, "get_tool_runtime", lambda: runtime)
    first_content = "用户喜欢简洁回答。"
    second_content = "用户正在学习 Transformer。"
    assert memory_tools.write_long_term_memory(first_content) == f"已记住: {first_content}"
    services = SimpleNamespace(
        config=config, memory_service=memory_service,
        retrieval_service=SimpleNamespace(embedding_service=None),
        knowledge_library_service=None, library_service=None,
    )
    second = execute_business(
        services, "owner", "write_long_term_memory", {"content": second_content},
    )
    assert second["content"] == second_content

    records = memory_service.list_user_memories(user_id="owner")
    assert len({record.memory_id for record in records}) == 2
    assert all(record.metadata_json["fact_status"] == "active" for record in records)
    candidates = HybridRetrievalService(config=config, engine=memory_service.engine).retrieve_keyword_candidates(
        query="简洁 Transformer", user_id="owner", session_id="another_session",
        tag=config.constants.memory_tag, memory_type="important_fact_summary", limit=5,
    )
    assert {item.memory.content for item in candidates} == {first_content, second_content}


def test_failed_second_write_leaves_existing_memory_unchanged(memory_service, monkeypatch):
    """A creation failure must preserve the first record, including its active status."""
    config = memory_service.config
    write_manual_memory(
        config=config, memory_service=memory_service, embedding_service=None,
        user_id="owner", content="用户喜欢简洁回答。",
    )
    before = memory_service.list_user_memories(user_id="owner")[0].model_dump()

    def fail_create(_memory_create):
        """Simulate persistence failing before the new memory is saved."""
        raise RuntimeError("simulated memory creation failure")

    monkeypatch.setattr(memory_service, "create_memory", fail_create)
    with pytest.raises(RuntimeError, match="simulated memory creation failure"):
        write_manual_memory(
            config=config, memory_service=memory_service, embedding_service=None,
            user_id="owner", content="用户正在学习 Transformer。",
        )

    records = memory_service.list_user_memories(user_id="owner")
    assert len(records) == 1
    assert records[0].model_dump() == before
