"""灌库任务跨库回归：使用真实设置、文件和索引清理，逐文件运行且不加载模型。"""

from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from agent_service.core.agent_config import AgentConfig
from agent_service.models.user_settings import UserKnowledgeLibrary
from agent_service.services.knowledge_ingestion_job import service as job_module
from agent_service.services.knowledge_library import KnowledgeLibraryService
from agent_service.services.settings.mcp_settings import selected_library
from agent_service.services.settings.service import SettingsService
from tests.db_test_utils import create_test_engine


@pytest.fixture
def libraries(tmp_path: Path):
    """提供两个拥有同名文件的真实知识库，记录向量与图谱的清理归属。"""

    config = AgentConfig.load_config(
        {"storage": {"project_root": str(tmp_path), "knowledge_dir": str(tmp_path / "A")}},
        load_env=False, load_dotenv=False, ensure_directories=False, ensure_models=False,
    )
    engine = create_test_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    deleted = []
    graph_deleted = []
    memory = SimpleNamespace(
        engine=engine,
        delete_memories_for_source=lambda **kwargs: deleted.append(kwargs) or 1,
    )
    graph = SimpleNamespace(delete_document_graph=lambda **kwargs: graph_deleted.append(kwargs) or 1)
    settings = SettingsService(config=config, memory_service=memory)
    library = KnowledgeLibraryService(
        config=config, memory_service=memory, settings_service=settings,
        knowledge_graph_service=graph, embedding_service=SimpleNamespace(),
    )
    ids = {}
    roots = {}
    for name in ("A", "B"):
        root = tmp_path / name
        root.mkdir(exist_ok=True)
        (root / "note.md").write_text(f"# {name}", encoding="utf-8")
        profile = settings.update_knowledge_dir(user_id="u1", knowledge_dir=str(root))
        ids[name] = profile["active_library_id"]
        roots[name] = root
    settings.update_knowledge_dir(user_id="u1", knowledge_dir=str(roots["A"]))
    jobs = job_module.KnowledgeIngestionJobService(
        engine=engine, config=config, knowledge_library_service=library, autostart=False,
    )
    try:
        yield SimpleNamespace(
            config=config, engine=engine, memory=memory, graph=graph, settings=settings,
            library=library, jobs=jobs, ids=ids, roots=roots,
            deleted=deleted, graph_deleted=graph_deleted,
        )
    finally:
        jobs.stop()
        engine.dispose()


@pytest.mark.parametrize("outcome", ["queued_cancel", "running_cancel", "failed", "shutdown"])
def test_cleanup_remains_in_submitted_library_after_switch(libraries, outcome: str) -> None:
    """切库后等待取消、运行取消、失败与关闭清理都不能触碰 B 库索引。"""

    env = libraries
    job = env.jobs.submit(user_id="u1", paths=["note.md"])[0]
    assert job["library_id"] == env.ids["A"]
    if outcome != "queued_cancel":
        env.jobs._claim_next()
    env.settings.update_knowledge_dir(user_id="u1", knowledge_dir=str(env.roots["B"]))
    if outcome in {"queued_cancel", "running_cancel"}:
        env.jobs.cancel(job_id=job["job_id"], user_id="u1")
    elif outcome == "failed":
        env.jobs._finish_failed(job_id=job["job_id"], message="test failure")
    else:
        env.jobs._processes[job["job_id"]] = SimpleNamespace(is_alive=lambda: False)
        env.jobs.stop()
    owner = env.settings.build_knowledge_owner_id(user_id="u1", library_id=env.ids["A"])
    assert env.deleted and all(call["user_id"] == owner for call in env.deleted)
    assert env.graph_deleted and all(call["library_id"] == env.ids["A"] for call in env.graph_deleted)
    assert env.settings.ensure_user_profile(user_id="u1")["active_library_id"] == env.ids["B"]
    assert selected_library.get() is None


def test_worker_pins_original_library_without_changing_active_setting(libraries, monkeypatch) -> None:
    """子进程入口必须显式绑定原库，完成后释放上下文且保留 B 为当前库。"""

    env = libraries
    job = env.jobs.submit(user_id="u1", paths=["note.md"])[0]
    env.settings.update_knowledge_dir(user_id="u1", knowledge_dir=str(env.roots["B"]))
    import agent_service.services.knowledge_library as library_module
    import agent_service.services.knowledge_graph as graph_module
    import agent_service.services.memory.longterm_memory_service as memory_module

    monkeypatch.setattr(AgentConfig, "load_config", lambda **kwargs: env.config)
    monkeypatch.setattr(memory_module, "LongTermMemoryService", lambda **kwargs: env.memory)
    monkeypatch.setattr(library_module, "KnowledgeLibraryService", lambda **kwargs: env.library)
    monkeypatch.setattr(graph_module, "KnowledgeGraphService", lambda **kwargs: env.graph)
    seen = []

    def ingest(**kwargs):
        """在入口内读取真实档案与文件，验证 worker 的任务作用域。"""

        profile = env.settings.ensure_user_profile(user_id=kwargs["user_id"])
        source = Path(profile["knowledge_dir"]) / kwargs["path"]
        seen.append((profile["active_library_id"], source.read_text(encoding="utf-8")))
        return SimpleNamespace(to_dict=lambda: {"files_ingested": 1})

    monkeypatch.setattr(env.library, "ingest_single_file", ingest)
    events = Queue()
    job_module._run_ingestion_worker("u1", job["library_id"], "note.md", events)
    event = events.get_nowait()
    assert event["type"] == "done", event
    assert seen == [(env.ids["A"], "# A")]
    assert selected_library.get() is None
    assert env.settings.ensure_user_profile(user_id="u1")["active_library_id"] == env.ids["B"]


def test_missing_original_library_never_cleans_current_library(libraries) -> None:
    """原库配置被删除时保留取消终态，禁止改为清理当前 B 库。"""

    env = libraries
    job = env.jobs.submit(user_id="u1", paths=["note.md"])[0]
    env.settings.update_knowledge_dir(user_id="u1", knowledge_dir=str(env.roots["B"]))
    with Session(env.engine) as db:
        db.delete(db.get(UserKnowledgeLibrary, env.ids["A"]))
        db.commit()
    cancelled = env.jobs.cancel(job_id=job["job_id"], user_id="u1")
    assert cancelled["status"] == "cancelled"
    assert env.deleted == []
    assert env.graph_deleted == []
    assert selected_library.get() is None


def test_submit_uses_one_library_snapshot(libraries, monkeypatch) -> None:
    """档案返回期间切库也不能将 A 的文件目录与 B 的任务 ID 拼接。"""

    env = libraries
    original = env.settings.ensure_user_profile
    switched = False

    def profile_then_switch(*, user_id: str) -> dict:
        """精确地把切库安排在第一个档案快照读取之后。"""

        nonlocal switched
        profile = original(user_id=user_id)
        if not switched:
            switched = True
            env.settings.update_knowledge_dir(user_id=user_id, knowledge_dir=str(env.roots["B"]))
        return profile

    monkeypatch.setattr(env.settings, "ensure_user_profile", profile_then_switch)
    job = env.jobs.submit(user_id="u1", paths=["note.md"])[0]
    assert job["library_id"] == env.ids["A"]
    assert original(user_id="u1")["active_library_id"] == env.ids["B"]


def test_scheduler_passes_persisted_library_to_process(libraries, monkeypatch) -> None:
    """调度器必须把持久化的库 ID 传入 spawn 子进程，而不是只传相对路径。"""

    env = libraries
    env.jobs.submit(user_id="u1", paths=["note.md"])
    job = env.jobs._claim_next()
    events = Queue()
    events.put({"type": "done", "result": {"files_ingested": 1}})
    captured = {}

    def process(**kwargs):
        """记录跨进程序列化参数，模拟已经完成且正确回收的进程。"""

        captured.update(kwargs)
        return SimpleNamespace(start=lambda: None, is_alive=lambda: False,
                               join=lambda **kwargs: None, exitcode=0)

    monkeypatch.setattr(job_module.multiprocessing, "get_context", lambda mode: SimpleNamespace(
        Queue=lambda: SimpleNamespace(get_nowait=events.get_nowait, close=lambda: None),
        Process=process,
    ))
    env.jobs._run_claimed_job(job)
    assert captured["args"][:3] == ("u1", env.ids["A"], "note.md")
    assert env.jobs.get_job(job_id=job["job_id"], user_id="u1")["status"] == "finished"
