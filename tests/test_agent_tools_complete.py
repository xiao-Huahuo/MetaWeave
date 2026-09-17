"""Agent 全工具低成本可执行性测试。

功能说明：
补齐正式注册表中此前没有直接成功路径测试的工具适配器。测试只使用临时目录、
内存替身和受控网络响应，不访问用户数据、不启动模型，也不并行运行长任务。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from agent_service.core.agent_config import AgentConfig
from agent_service.tools import ToolRegistry
from agent_service.tools.builtin import agent, business_ops, git, knowledge, knowledge_ops, library, memory, smart_forms, tasks, terminal, utility, web


class _Recorder:
    """按方法名返回预设结果并记录调用的通用服务替身。"""

    def __init__(self, results: dict[str, Any]) -> None:
        """保存各方法的固定返回值。"""

        self.results = results
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        """为服务方法生成记录调用的函数。"""

        if name not in self.results:
            raise AttributeError(name)

        def call(*args: Any, **kwargs: Any) -> Any:
            """记录参数并返回预设结果。"""

            self.calls.append((name, args, kwargs))
            result = self.results[name]
            return result(*args, **kwargs) if callable(result) else result

        return call


@pytest.fixture
def runtime(tmp_path: Path) -> SimpleNamespace:
    """创建不下载模型、不访问真实数据的最小工具运行时。"""

    config = AgentConfig.load_config(
        {
            "storage": {"base_data_dir": str(tmp_path / "data")},
            "terminal_sandbox": {"default_workspace_root": str(tmp_path)},
        },
        load_env=False,
        load_dotenv=False,
        ensure_directories=False,
        ensure_models=False,
    )
    return SimpleNamespace(
        config=config,
        user_id="tool-user",
        session_id="tool-session",
        run_id="tool-run",
        agent_access_mode="sandbox",
        long_term_memory_enabled=True,
        citation_map={},
        tool_citation_counter=0,
        network_citation_counter=0,
        memory_service=SimpleNamespace(engine=object()),
        embedding_service=SimpleNamespace(embed_text=lambda _text: [0.1]),
        settings_service=None,
        skill_service=None,
        message_service=None,
        database_engine=None,
        task_list_service=None,
        change_service=None,
        retrieval_service=None,
        child_agent_spawner=None,
        child_agent_waiter=None,
        child_agent_continuation=None,
    )


def test_all_registered_tools_build_langchain_schemas() -> None:
    """全部正式原生工具都必须能转换为模型实际绑定的 StructuredTool。"""

    registry = ToolRegistry.with_builtin_tools()
    converted = registry.to_langchain_tools()

    assert len(registry.definitions) == 106
    assert {tool.name for tool in converted} == set(registry.definitions)
    assert all(callable(definition.function) for definition in registry.definitions.values())


def test_utility_and_child_agent_tools_execute(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """工具目录、续读、Skill 和三个子 Agent 入口必须返回成功结果。"""

    message = SimpleNamespace(role="tool", tool_call_id="call-1", content="one\ntwo")
    runtime.message_service = _Recorder({"list_session_messages": [message]})
    runtime.skill_service = _Recorder({
        "list_skills": [{"name": "Demo", "skill_id": "builtin:demo", "source": "builtin", "enabled": True, "description": "demo"}],
        "read_skill_body": {"name": "Demo", "skill_id": "builtin:demo", "source": "builtin", "path": "demo/SKILL.md", "body": "Do it", "disabled": False},
    })
    runtime.child_agent_spawner = lambda **_kwargs: "spawned"
    runtime.child_agent_waiter = lambda **_kwargs: "waited"
    runtime.child_agent_continuation = lambda **_kwargs: "continued"
    monkeypatch.setattr(utility, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(agent, "get_tool_runtime", lambda: runtime)

    assert "list_available_tools" in utility.list_available_tools()
    assert json.loads(utility.read_tool_result("tool-result://call-1"))["content"] == "one\ntwo"
    assert "Demo" in utility.list_skills()
    assert "[SKILL.md]" in utility.use_skill("builtin:demo")
    assert agent.spawn_child_agent("inspect") == "spawned"
    assert agent.wait_for_child_agents(["run-1"], 1) == "waited"
    assert agent.continue_child_agent("run-1", "continue") == "continued"


def test_terminal_tool_executes_internal_command(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """终端工具适配器必须把结构化命令交给正式沙盒并序列化结果。"""

    from agent_service.services.settings.service import SettingsService
    from agent_service.services.terminal.command_sandbox import TerminalSandbox

    monkeypatch.setattr(terminal, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(SettingsService, "get_terminal_sandbox_config", lambda _self, **_kwargs: {"config": {}})
    monkeypatch.setattr(TerminalSandbox, "run", lambda _self, **_kwargs: {"ok": True, "results": []})

    result = json.loads(terminal.run_terminal_command("cmd", [{"type": "internal_command", "command": "pwd", "args": []}]))

    assert result["ok"] is True


def test_all_git_tool_adapters_execute(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """十一个 Git 工具都必须把当前用户和参数传给统一 GitService。"""

    service = _Recorder({
        "get_status": {"branch": "main"},
        "get_diff": {"diff": "diff"},
        "get_history": {"commits": []},
        "initialize_repository": {"initialized": True},
        "restore_paths": {"restored": ["a.md"]},
        "commit": {"commit": "abc"},
        "push": {"pushed": True},
        "create_branch": {"branch": "topic"},
        "add_remote": {"remote": "origin"},
        "switch_branch": {"branch": "topic"},
        "pull_fast_forward": {"updated": True},
    })
    monkeypatch.setattr(git, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(git, "_get_git_service", lambda: service)

    assert "main" in git.git_status()
    assert git.git_diff() == "diff"
    assert "commits" in git.git_history()
    assert "initialized" in git.git_init_repository()
    assert "restored" in git.git_restore_files(["a.md"])
    assert "abc" in git.git_commit_files(["a.md"], "commit")
    assert "pushed" in git.git_push_branch("main", "origin", "main", confirm=True)
    assert "topic" in git.git_create_branch("topic")
    assert "origin" in git.git_add_remote("origin", "https://example.test/repo.git")
    assert "topic" in git.git_switch_branch("topic")
    assert "updated" in git.git_pull_branch("origin", "main")


def test_memory_tools_execute_success_paths(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """检索、写入和删除长期记忆/规则的六个入口都必须可执行。"""

    recalled = SimpleNamespace(memory=SimpleNamespace(content="remembered", source_uri="notes/a.md"))
    runtime.retrieval_service = _Recorder({"retrieve_long_term_memory": [recalled], "retrieve_knowledge": [recalled]})
    runtime.memory_service = _Recorder({
        "create_memory": SimpleNamespace(memory_id="m1"),
        "find_user_memory_by_content": SimpleNamespace(memory_id="m1", content="remembered"),
        "delete_memory": True,
    })
    runtime.memory_service.engine = object()
    monkeypatch.setattr(memory, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(memory, "_supersede_prior_entries", lambda **_kwargs: None)
    monkeypatch.setattr(memory, "register_tool_citation", lambda **_kwargs: "K1")
    monkeypatch.setattr(memory, "_is_readonly_access", lambda: False)

    from agent_service.services.settings.service import SettingsService

    monkeypatch.setattr(SettingsService, "add_system_prompt_entry", lambda _self, **_kwargs: {"prompt_id": "p1"})
    monkeypatch.setattr(SettingsService, "list_system_prompt_entries", lambda _self, **_kwargs: [{"prompt_id": "p1", "content": "rule"}])
    monkeypatch.setattr(SettingsService, "delete_system_prompt_entry", lambda _self, **_kwargs: True)

    assert "remembered" in memory.get_long_term_memory("remember")
    assert "[K1]" in memory.get_knowledge_context("context")
    assert "已记住" in memory.write_long_term_memory("remembered")
    assert "已删除长期记忆" in memory.delete_long_term_memory("remembered")
    assert "p1" in memory.write_long_term_rule("rule")
    assert "已删除长期规则" in memory.delete_long_term_rule("rule")


def test_library_tools_execute_success_paths(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """图书馆查询、新增、更新和删除六个入口都必须调用统一服务。"""

    item = {"item_id": "book-1", "display_title": "Book", "item_type": "book"}
    service = _Recorder({
        "list_items": {"items": [item], "breadcrumbs": []},
        "list_tags": {"tags": [{"name": "AI", "tag_id": "tag-1"}]},
        "create_item": {"item": item},
        "create_collection": {"item": {**item, "item_type": "collection"}},
        "update_item": {"item": item},
        "delete_item": {"deleted": True, "item": item},
    })
    monkeypatch.setattr(library, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(library, "_get_library_service", lambda: service)
    monkeypatch.setattr(library, "_is_readonly_access", lambda: False)

    assert "Book" in library.list_library_items()
    assert "AI" in library.list_library_tags()
    assert "book-1" in library.add_library_book(source_path="a.md")
    assert "book-1" in library.add_library_collection("Collection")
    assert "Book" in library.update_library_item("book-1", title="Book")
    assert "book-1" in library.remove_library_item("book-1")


def test_task_and_todo_tools_execute_success_paths(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """任务清单、待办和自动化的十个工具入口都必须完成成功路径。"""

    task_list = {"title": "Plan", "status": "active", "current_item_id": "i1", "items": [{"id": "i1", "title": "Step", "status": "pending"}]}
    task_service = _Recorder({
        "get_task_list": task_list,
        "create_task_list": task_list,
        "complete_task_list_item": {**task_list, "items": [{"id": "i1", "title": "Step", "status": "completed"}]},
        "finish_task_list": {**task_list, "status": "completed"},
    })
    todo_item = {"id": "todo-1", "text": "Todo", "done": False, "dueDate": None}
    todo_service = _Recorder({
        "list_todos": [todo_item],
        "add_todo": todo_item,
        "toggle_todo": {**todo_item, "done": True},
        "edit_todo": {**todo_item, "text": "Edited"},
        "delete_todo": True,
    })
    automation_service = _Recorder({
        "create_task": {"id": "auto-1", "nextRunAt": "2026-09-03T09:00:00+08:00"},
        "get_task_by_todo_id": None,
        "delete_task_by_todo_id": False,
    })
    monkeypatch.setattr(tasks, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(tasks, "_get_task_list_service", lambda: task_service)
    monkeypatch.setattr(tasks, "_get_todo_service", lambda: todo_service)
    monkeypatch.setattr(tasks, "_get_automation_service", lambda: automation_service)
    monkeypatch.setattr(tasks, "_emit_task_list_update", lambda _value: None)

    assert "Plan" in tasks.get_task_list_status()
    assert "Current item: Step" in tasks.create_task_list("Plan", ["Step"])
    assert "Remaining items: 0" in tasks.complete_task_list_item("i1", "done")
    assert "finished" in tasks.finish_task_list("done")
    assert "Todo" in tasks.list_todos()
    assert "todo-1" in tasks.add_todo("Todo")
    assert "已创建自动化任务" in tasks.add_automation("Wake", "Run", "2026-09-03T09:00:00+08:00")
    assert "已完成" in tasks.toggle_todo("todo-1")
    assert "Edited" in tasks.edit_todo("todo-1", "Edited")
    assert "已删除待办" in tasks.delete_todo("todo-1")


def test_web_tools_execute_with_controlled_responses(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """网页搜索、图片搜索和下载必须在受控网络响应下成功。"""

    runtime.settings_service = _Recorder({"get_web_search_config": {"web_search_enabled": True, "proxy_url": "", "web_search_max_results": 1}})
    runtime.config.storage.assets_dir = tmp_path
    monkeypatch.setattr(web, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(web, "register_network_citation", lambda **_kwargs: "N1")

    class _DDGS:
        """返回一条文本和一条图片结果的 DDGS 替身。"""

        def __init__(self, **_kwargs: Any) -> None:
            """忽略连接参数。"""

        def __enter__(self) -> "_DDGS":
            """进入上下文。"""

            return self

        def __exit__(self, *_args: Any) -> None:
            """退出上下文。"""

        def text(self, *_args: Any, **_kwargs: Any) -> list[dict[str, str]]:
            """返回满足最小摘要长度的文本结果。"""

            return [{"title": "Result", "href": "https://example.test/page", "body": "x" * 200}]

        def images(self, *_args: Any, **_kwargs: Any) -> list[dict[str, str]]:
            """返回完整图片字段。"""

            return [{"title": "Image", "image": "https://example.test/a.png", "thumbnail": "https://example.test/t.png", "url": "https://example.test/page"}]

    ddgs_module = ModuleType("ddgs")
    ddgs_module.DDGS = _DDGS
    monkeypatch.setitem(sys.modules, "ddgs", ddgs_module)

    class _Response:
        """同时满足网页抓取和文件下载协议的响应替身。"""

        headers = {"Content-Type": "image/png"}

        def __enter__(self) -> "_Response":
            """进入响应上下文。"""

            return self

        def __exit__(self, *_args: Any) -> None:
            """退出响应上下文。"""

        def read(self) -> bytes:
            """返回稳定响应体。"""

            return b"png-data"

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: _Response())

    assert "[N1]" in web.web_search("query")
    assert "Markdown展示" in web.web_image_search("image")
    assert "文件已下载到本地" in web.download_file("https://example.test/a.png")


def test_missing_knowledge_file_adapters_execute(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """知识文件列表、读取、写补丁、可视化、删除、改名、目录和 URL 工具必须成功。"""

    root = tmp_path / "vault"
    root.mkdir()
    (root / "a.md").write_text("old text", encoding="utf-8")
    file_service = _Recorder({
        "list_files": [{"path": "a.md", "name": "a.md", "isDir": False}],
        "read_markdown_projection": {"path": "a.md", "content": "old text"},
        "read_file": {"content": "old text"},
        "write_file": {"path": "a.md", "size": 7},
        "delete_path": {"path": "a.md"},
        "rename_path": {"path": "b.md"},
        "create_folder": {"path": "docs"},
        "get_active_root_path": root,
    })
    settings_service = _Recorder({"ensure_user_profile": {"current_document": {"path": "a.md"}, "active_knowledge_library": {"library_id": "l1", "knowledge_dir": str(root)}}})
    runtime.settings_service = settings_service
    monkeypatch.setattr(knowledge, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(knowledge, "_build_knowledge_service", lambda: file_service)
    monkeypatch.setattr(knowledge, "_is_readonly_access", lambda: False)
    monkeypatch.setattr(knowledge, "register_tool_citation", lambda **_kwargs: "K1")
    monkeypatch.setattr(knowledge, "get_markdown_html_visualization_callback", lambda: lambda _payload: None)
    from agent_service.services.editor_context.service import editor_context_service

    editor_context_service.set_current_document({
        "user_id": runtime.user_id,
        "path": "a.md",
        "knowledge_dir": str(root),
        "library_id": "l1",
        "library_name": "Vault",
    })

    assert "a.md" in knowledge.list_knowledge_files()
    assert "old text" in knowledge.read_file("a.md")
    assert "a.md" in knowledge.patch_knowledge_file("a.md", "old", "new")
    assert "a.md" in knowledge.write_knowledge_file("a.md", "content")
    assert "visualization generated" in knowledge.show_markdown_html("Title", "<p>ok</p>")
    assert "a.md" in knowledge.delete_knowledge_file("a.md")
    assert "b.md" in knowledge.rename_knowledge_file("a.md", "b.md")
    assert "docs" in knowledge.create_knowledge_folder("docs")
    assert "a.md" in knowledge.get_current_viewing_document()
    assert "/knowledge/files/raw" in knowledge.get_knowledge_file_url("a.md")


def test_search_and_uploaded_attachment_promotion_execute(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """四库搜索与会话附件正式入库工具必须完成成功路径。"""

    from sqlmodel import Session

    from agent_service.models.attachment import SessionAttachmentRecord
    from tests.db_test_utils import create_test_engine

    class _SearchService:
        """返回单条文件库搜索结果。"""

        def search(self, **_kwargs: Any) -> dict[str, Any]:
            """返回工具需要的统一搜索结构。"""

            return {"results": [{
                "id": "file-1",
                "source": "files",
                "title": "A",
                "snippet": "content",
                "locator": "a.md",
                "matched_modes": ["fulltext"],
                "score": 1.0,
                "item": {},
            }], "total": 1}

    runtime.unified_search_service = _SearchService()
    monkeypatch.setattr(knowledge, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(knowledge, "register_tool_citation", lambda **_kwargs: "K1")
    assert "K1" in knowledge.search_knowledge("content")

    source = tmp_path / "upload.txt"
    source.write_text("upload", encoding="utf-8")
    root = tmp_path / "vault"
    root.mkdir()
    engine = create_test_engine("sqlite:///:memory:")
    runtime.database_engine = engine
    with Session(engine) as db_session:
        db_session.add(SessionAttachmentRecord(
            attachment_id="attachment-1",
            user_id=runtime.user_id,
            session_id=runtime.session_id,
            library_id="library-1",
            filename="upload.txt",
            stored_name="upload.txt",
            path=str(source),
        ))
        db_session.commit()

    def write_uploaded_file(**kwargs: Any) -> Path:
        """把附件内容写入临时知识库并返回路径。"""

        target = root / str(kwargs["filename"])
        target.write_bytes(bytes(kwargs["content"]))
        return target

    result = SimpleNamespace(status_message="indexed", files_ingested=1, chunks_created=1, files_skipped=0, skip_reason="")
    file_service = _Recorder({
        "write_uploaded_file": write_uploaded_file,
        "get_active_root_path": root,
        "ingest_single_file": result,
    })
    monkeypatch.setattr(knowledge, "_build_knowledge_service", lambda: file_service)
    monkeypatch.setattr(knowledge, "_is_readonly_access", lambda: False)

    assert "upload.txt" in knowledge.save_uploaded_attachment_to_knowledge("attachment-1")


def test_remaining_knowledge_job_adapters_execute(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """多选上下文、任务取消/重试、图谱抽取/删除/重试入口必须执行。"""

    job_manager = _Recorder({
        "get": {"job_id": "job-1", "kind": "ingestion_selected", "status": "failed", "failed_items": [{"path": "a.md"}]},
        "cancel": {"job_id": "job-1", "status": "cancelling"},
        "start": {"job_id": "job-2", "status": "running"},
    })
    knowledge_service = _Recorder({"read_frontmatter_payload_for_file": {"document_id": "doc-1"}})
    graph_service = _Recorder({"delete_document_graph": True})
    monkeypatch.setattr(knowledge_ops, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(knowledge_ops, "tool_job_manager", job_manager)
    monkeypatch.setattr(knowledge_ops, "editor_context_service", _Recorder({"get_current_document": SimpleNamespace(path="a.md", selected_paths=("a.md", "b.md"))}))
    monkeypatch.setattr(knowledge_ops, "_knowledge_service", lambda: knowledge_service)
    monkeypatch.setattr(knowledge_ops, "_graph_service", lambda: graph_service)
    monkeypatch.setattr(knowledge_ops, "_start_ingestion_job", lambda **_kwargs: json.dumps({"job_id": "job-2"}))
    monkeypatch.setattr(knowledge_ops, "_start_graph_job", lambda **_kwargs: json.dumps({"job_id": "job-3"}))
    monkeypatch.setattr(knowledge_ops, "_graph_context", lambda: ("tool-user", "l1", Path("."), {}, runtime.config))

    assert "a.md" in knowledge_ops.get_selected_knowledge_files()
    assert "cancelling" in knowledge_ops.cancel_knowledge_job("job-1")
    assert "job-2" in knowledge_ops.retry_failed_knowledge_files("job-1")
    assert "job-3" in knowledge_ops.extract_selected_file_graphs(["a.md"])
    assert "job-3" in knowledge_ops.extract_all_file_graphs()
    assert "doc-1" in knowledge_ops.delete_file_graph("a.md")
    job_manager.results["get"] = {"job_id": "job-1", "kind": "graph_selected", "status": "failed", "failed_items": [{"path": "a.md"}]}
    assert "job-3" in knowledge_ops.retry_failed_graph_extraction("job-1")


def test_skill_business_adapters_execute(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """用户 Skill 的读取、增删改、验证、路由测试和启停工具必须成功。"""

    skill = {"skill_id": "user:demo", "name": "Demo", "description": "demo", "body": "body", "enabled": True}
    skill = {**skill, "source": "user"}
    service = _Recorder({
        "read_skill_body": skill,
        "create_user_skill": skill,
        "update_user_skill": skill,
        "delete_user_skill": {"deleted": True},
        "validate_user_skill": {"valid": True},
        "test_user_skill": {"matched": True},
        "set_skill_enabled": {**skill, "enabled": False},
    })
    runtime.skill_service = service
    monkeypatch.setattr(business_ops, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(business_ops, "_service", lambda _name: service)

    assert "Demo" in business_ops.get_custom_skill("user:demo")
    assert "Demo" in business_ops.create_custom_skill("Demo", "demo", "body")
    assert "Demo" in business_ops.update_custom_skill("user:demo", name="Demo")
    assert "deleted" in business_ops.delete_custom_skill("user:demo", True)
    assert "valid" in business_ops.validate_custom_skill("user:demo")
    assert "matched" in business_ops.test_custom_skill("user:demo", "use demo")
    assert "enabled" in business_ops.set_skill_enabled("user:demo", False)


def test_remaining_smart_form_adapters_execute(runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """表格列表、完整读取、结构读取和覆盖更新工具必须成功。"""

    form = {"form_id": "form-1", "asset_dir": ".mw/forms/form-1", "form": {"title": "Form", "version": 1, "columns": [], "rows": []}}
    service = _Recorder({
        "list_forms": [form],
        "get_form": form,
        "save_form": form,
    })
    monkeypatch.setattr(smart_forms, "get_tool_runtime", lambda: runtime)
    monkeypatch.setattr(smart_forms, "_smart_form_service", lambda: service)

    assert "form-1" in smart_forms.list_smart_forms()
    assert "form-1" in smart_forms.get_smart_form("form-1")
    assert "columns" in smart_forms.get_smart_form_schema("form-1")
    assert "form-1" in smart_forms.update_smart_form("form-1", form["form"])
