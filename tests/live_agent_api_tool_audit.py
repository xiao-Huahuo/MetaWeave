"""通过真实 Agent HTTP/SSE API 逐项验收工具。

使用说明：
先运行 ``configure`` 通过终端隐式输入模型密钥，再用 ``run`` 执行 case 文件。
脚本只把脱敏状态写入 runtime 账本；已经通过的工具默认永久跳过。
"""

from __future__ import annotations

import argparse
import getpass
import http.client
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8002"
USER_ID = "api-tool-audit"
LEDGER_PATH = ROOT / "runtime" / "agent_tool_api_ledger.json"
ERROR_MARKERS = (
    "执行失败",
    "internal server error",
    "not bound to request",
    "not initialized",
    "http 503",
)


def _request_json(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    """调用真实 HTTP API 并解析 JSON 响应。"""

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(
        f"{BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def configure() -> None:
    """从隐藏输入读取密钥并通过真实设置 API 保存审计用户模型配置。"""

    api_key = getpass.getpass("DeepSeek API key: ").strip()
    if not api_key:
        raise SystemExit("API key is required")
    _request_json("PUT", "/settings/llm/config", {
        "user_id": USER_ID,
        "api_key": api_key,
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-v4-flash",
        "small_api_key": api_key,
        "small_base_url": "https://api.deepseek.com",
        "small_model_name": "deepseek-v4-flash",
    })
    print("configured=true")


def setup() -> None:
    """创建隔离知识库目录并通过正式设置/编辑上下文 API 绑定审计用户。"""

    vault = ROOT / "runtime" / "agent_tool_api_vault"
    vault.mkdir(parents=True, exist_ok=True)
    _request_json("PUT", "/settings/profile/knowledge-dir", {
        "user_id": USER_ID,
        "knowledge_dir": str(vault),
        "name": "Agent API Audit",
    })
    _request_json("PUT", "/agent/editor-context/current-document", {
        "user_id": USER_ID,
        "path": "audit.md",
        "name": "audit.md",
        "knowledge_dir": str(vault),
        "library_id": "",
        "library_name": "Agent API Audit",
        "selected_paths": ["audit.md"],
    })
    _request_json("PUT", "/settings/terminal/sandbox", {
        "user_id": USER_ID,
        "config": {"enabled": True},
    })
    _request_json("PUT", "/settings/web-search/config", {
        "user_id": USER_ID,
        "proxy_url": "",
        "web_search_enabled": True,
        "web_search_max_results": 1,
    })
    remote = ROOT / "runtime" / "agent_tool_api_remote.git"
    if not (remote / "HEAD").is_file():
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    if (vault / ".git").is_dir():
        branches = subprocess.run(
            ["git", "-C", str(vault), "branch", "--format=%(refname:short)"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.splitlines()
        if "api-audit-branch" in branches and "main" not in branches:
            subprocess.run(["git", "-C", str(vault), "branch", "main", "api-audit-branch"], check=True)
        if not (vault / "audit.md").exists() and not (vault / "audit-renamed.md").exists():
            restored = subprocess.run(
                ["git", "-C", str(vault), "show", "HEAD:audit.md"],
                check=True,
                capture_output=True,
            ).stdout
            (vault / "audit.md").write_bytes(restored)
    (vault / "restore-me.txt").write_text("restore through Agent API", encoding="utf-8")
    graph_source = vault / "audit-renamed.md"
    if graph_source.is_file():
        graph_source.write_text(
            "# MetaWeave API Audit\n\nMetaWeave uses the DeepSeek API. "
            "The DeepSeek API powers Agent tool verification.\n",
            encoding="utf-8",
        )
    print("setup=true")


def setup_child() -> None:
    """通过正式设置 API 启用 DSH 子 Agent，并输出脱敏运行时状态。"""

    _request_json("PUT", "/settings/profile/ingestion", {
        "user_id": USER_ID,
        "dsh_coding_agent_enabled": True,
    })
    payload = _request_json("GET", f"/settings/sdks/dsh/management?user_id={USER_ID}")
    print(json.dumps({
        "status": payload.get("status"),
        "installed": payload.get("installed"),
        "ready": payload.get("ready"),
    }, ensure_ascii=False))


def setup_vision() -> None:
    """通过正式设置 API 单独启用本地识图，不启用 OCR 额外负载。"""

    payload = _request_json("PUT", "/settings/profile/ingestion", {
        "user_id": USER_ID,
        "ocr_enabled": False,
        "vision_understanding_enabled": True,
    })
    print(json.dumps({
        "ocr_enabled": payload.get("ocr_enabled"),
        "vision_understanding_enabled": payload.get("vision_understanding_enabled"),
    }, ensure_ascii=False))


def repair_child() -> None:
    """通过正式管理 API 修复 DSH Runtime，并等待明确终态。"""

    started = _request_json("POST", "/settings/sdks/dsh/repair", {"user_id": USER_ID})
    seen_working = started.get("status") not in {"ready", "failed"}
    print(f"repair_started={started.get('status')}")
    for _ in range(480):
        payload = _request_json("GET", f"/settings/sdks/dsh/management?user_id={USER_ID}")
        seen_working = seen_working or payload.get("status") not in {"ready", "failed"}
        if payload.get("status") in {"ready", "failed"} and seen_working:
            print(json.dumps({
                "status": payload.get("status"),
                "message": payload.get("message"),
                "installed": payload.get("installed"),
            }, ensure_ascii=False))
            if payload.get("status") != "ready":
                raise SystemExit(1)
            return
        time.sleep(0.5)
    raise TimeoutError("DSH repair did not reach a terminal state")


def cleanup() -> None:
    """清除审计用户凭据、功能开关和临时会话，不删除验收账本。"""

    _request_json("PUT", "/settings/llm/config", {
        "user_id": USER_ID,
        "api_key": "",
        "base_url": "",
        "model_name": "",
        "small_api_key": "",
        "small_base_url": "",
        "small_model_name": "",
    })
    _request_json("PUT", "/settings/profile/ingestion", {
        "user_id": USER_ID,
        "ocr_enabled": False,
        "vision_understanding_enabled": False,
        "dsh_coding_agent_enabled": False,
    })
    _request_json("PUT", "/settings/web-search/config", {
        "user_id": USER_ID,
        "proxy_url": "",
        "web_search_enabled": False,
    })
    deleted = _request_json("DELETE", f"/sessions?user_id={USER_ID}")
    print(json.dumps({"credentials_cleared": True, **deleted}, ensure_ascii=False))


def _load_ledger() -> dict[str, Any]:
    """读取可恢复账本；不存在时创建空结构。"""

    if not LEDGER_PATH.is_file():
        return {"user_id": USER_ID, "passed": {}, "failed": {}}
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _save_ledger(ledger: dict[str, Any]) -> None:
    """原子保存不含密钥和完整模型上下文的工具状态。"""

    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = LEDGER_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(LEDGER_PATH)


def _create_session(tool_name: str) -> str:
    """为单个工具创建隔离的真实 Agent 会话。"""

    session = _request_json("POST", "/sessions", {
        "user_id": USER_ID,
        "session_name": f"API tool audit: {tool_name}",
    })
    return str(session["session_id"])


def _upload_attachment(session_id: str, *, image: bool) -> dict[str, Any]:
    """通过真实 multipart API 上传审计附件。"""

    boundary = "----MetaWeaveAgentApiAudit"
    filename = "audit.png" if image else "audit.txt"
    content_type = "image/png" if image else "text/plain"
    content = (
        (ROOT / "tests" / "测试文件" / "普通图片.png").read_bytes()
        if image
        else b"Agent API attachment audit\nsecond line\n"
    )
    fields = [
        ("user_id", USER_ID.encode("utf-8"), None, None),
        ("session_id", session_id.encode("utf-8"), None, None),
        ("file", content, filename, content_type),
    ]
    chunks: list[bytes] = []
    for name, value, upload_name, upload_type in fields:
        chunks.append(f"--{boundary}\r\n".encode())
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if upload_name:
            disposition += f'; filename="{upload_name}"'
        chunks.append(f"{disposition}\r\n".encode())
        if upload_type:
            chunks.append(f"Content-Type: {upload_type}\r\n".encode())
        chunks.append(b"\r\n" + value + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    connection = http.client.HTTPConnection("127.0.0.1", 8002, timeout=60)
    connection.request(
        "POST",
        "/agent/attachments/upload",
        body=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    connection.close()
    if response.status >= 400:
        raise RuntimeError(f"HTTP {response.status}: {payload}")
    return dict(payload["attachment"])


def _prepare_case(
    tool_name: str,
    arguments: dict[str, Any],
    prepare: str,
    session_id: str = "",
) -> tuple[str, dict[str, Any]]:
    """通过真实 REST API 为需要状态的工具创建同会话前置数据。"""

    if prepare == "wait_graph_job":
        time.sleep(15)
    if prepare == "tool_result":
        imported = _request_json("POST", "/sessions/import", {
            "user_id": USER_ID,
            "session_name": f"API tool audit: {tool_name}",
            "messages": [{
                "role": "tool",
                "content": "first line\nsecond line",
                "tool_call_id": "audit-tool-call",
            }],
        })
        return str(imported["session_id"]), arguments
    session_id = session_id or _create_session(tool_name)
    if prepare in {"task_list", "task_list_completed"}:
        created = _request_json("POST", f"/sessions/{session_id}/task-list", {
            "title": "API audit task list",
            "items": ["first item"],
        })
        item_id = str(created["task_list"]["items"][0]["id"])
        arguments = {**arguments, "item_id": item_id}
        if prepare == "task_list_completed":
            _request_json("POST", f"/sessions/{session_id}/task-list/complete-item", {
                "item_id": item_id,
                "completion_summary": "prepared",
            })
    if prepare in {"text_attachment", "image_attachment"}:
        attachment = _upload_attachment(session_id, image=prepare == "image_attachment")
        attachment_id = str(attachment["attachment_id"])
        if tool_name == "read_file":
            arguments = {**arguments, "path": f"attachment://{attachment_id}"}
        else:
            arguments = {**arguments, "attachment": attachment_id}
    return session_id, arguments


def _resolve_arguments(value: Any, ledger: dict[str, Any]) -> Any:
    """把依赖前序 API 结果的占位符替换为账本中的真实资源 ID。"""

    if isinstance(value, dict):
        return {key: _resolve_arguments(item, ledger) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_arguments(item, ledger) for item in value]
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    if value == "$REMOTE_PATH":
        return str((ROOT / "runtime" / "agent_tool_api_remote.git").resolve())
    if value == "$VAULT_PATH":
        return str((ROOT / "runtime" / "agent_tool_api_vault").resolve())
    if value == "$GRAPH_NODE_ID":
        for _ in range(60):
            graph = _request_json("GET", f"/knowledge/graph?user_id={USER_ID}")
            nodes = graph.get("nodes") or []
            if nodes:
                return str(nodes[0]["id"])
            time.sleep(2)
        raise RuntimeError("Knowledge graph did not produce a node")
    if value in {"$TRASH_ID_RESTORE", "$TRASH_ID_DELETE"}:
        wanted = "audit-folder" if value == "$TRASH_ID_RESTORE" else "restore-me.txt"
        for metadata_path in (ROOT / "runtime" / "trash" / USER_ID).glob("*/**/metadata.json"):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("original_relative_path") == wanted:
                return str(metadata["trash_id"])
        raise RuntimeError(f"Trash fixture not found: {wanted}")
    sources = {
        "$TODO_ID": ("add_todo", r"todo_[0-9a-f]+"),
        "$LIBRARY_ID": ("add_library_collection", r"lib_[0-9a-f]+"),
        "$FEEDBACK_ID": ("create_user_feedback", r"fb_[0-9a-f]+"),
        "$SMART_FORM_ID": ("create_smart_form", r"sf_[0-9a-f]+"),
        "$INGEST_JOB_ID": ("ingest_selected_knowledge_files", r'"job_id":\s*"([^"]+)"'),
        "$GRAPH_JOB_ID": ("extract_selected_file_graphs", r'"job_id":\s*"([^"]+)"'),
        "$CHILD_RUN_ID": ("spawn_child_agent", r'"run_id":\s*"([^"]+)"'),
    }
    tool_name, pattern = sources[value]
    preview = str(ledger["passed"][tool_name]["content_preview"])
    match = re.search(pattern, preview)
    if match is None:
        raise RuntimeError(f"Cannot resolve {value} from {tool_name}")
    return match.group(1) if match.lastindex else match.group(0)


def _stream_tool(
    tool_name: str,
    arguments: dict[str, Any],
    instruction: str = "",
    prepare: str = "",
    session_id: str = "",
) -> list[dict[str, Any]]:
    """让真实模型经 Agent SSE 循环调用指定工具并返回全部 trace。"""

    session_id, arguments = _prepare_case(tool_name, arguments, prepare, session_id)
    prompt = (
        "这是自动化 API 工具验收。你必须且只能调用一次工具 "
        f"`{tool_name}`，参数严格使用以下 JSON："
        f"{json.dumps(arguments, ensure_ascii=False)}。"
        "不要改用其他工具，不要只解释；工具返回后只回复 DONE。"
        f"{instruction}"
    )
    request = Request(
        f"{BASE_URL}/agent/stream",
        data=json.dumps({
            "prompt": prompt,
            "user_id": USER_ID,
            "session_id": session_id,
            "agent_mode": "react",
            "agent_access_mode": "full_access",
        }, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    traces: list[dict[str, Any]] = []
    with urlopen(request, timeout=300) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line.removeprefix("data: "))
            context_request = event.get("context_request")
            if isinstance(context_request, dict):
                traces.append({
                    "event": "audit_context",
                    "tool_names": list(context_request.get("tool_names") or []),
                })
            for trace in event.get("trace") or []:
                if isinstance(trace, dict):
                    traces.append(trace)
            if event.get("error"):
                traces.append({"event": "stream_error", "raw_content": str(event["error"])})
    traces.append({"event": "audit_session", "session_id": session_id})
    return traces


def run_case(case: dict[str, Any], ledger: dict[str, Any]) -> str:
    """执行一个尚未通过的工具 case，并立即更新账本。"""

    tool_name = str(case["tool"])
    if tool_name in ledger["passed"]:
        return "skipped"
    traces = _stream_tool(
        tool_name,
        _resolve_arguments(dict(case.get("arguments") or {}), ledger),
        str(case.get("instruction") or ""),
        str(case.get("prepare") or ""),
        (
            str(ledger["passed"]["spawn_child_agent"].get("session_id") or "")
            if case.get("prepare") == "child_session"
            else ""
        ),
    )
    matching = [
        trace for trace in traces
        if trace.get("event") == "tool_call_end" and trace.get("tool_name") == tool_name
    ]
    if matching:
        raw_content = str(matching[-1].get("raw_content") or "")
    else:
        bound = any(
            tool_name in (trace.get("tool_names") or [])
            for trace in traces
            if trace.get("event") == "audit_context"
        )
        raw_content = f"tool_call_end not observed; target_bound={bound}"
    tool_result = matching[-1].get("tool_result") if matching else None
    child_terminal_error = ""
    if tool_name == "spawn_child_agent" and matching:
        run_id_match = re.search(r'"run_id":\s*"([^"]+)"', raw_content)
        session_id = next((str(trace.get("session_id")) for trace in traces if trace.get("session_id")), "")
        if run_id_match and session_id:
            for _ in range(240):
                children = _request_json("GET", f"/agent/children?session_id={session_id}")["children"]
                child = next((item for item in children if item.get("run_id") == run_id_match.group(1)), None)
                status_value = str((child or {}).get("status") or "")
                if status_value in {"completed", "failed", "stopped"}:
                    if status_value != "completed":
                        child_terminal_error = str((child or {}).get("error") or status_value)
                    break
                time.sleep(0.5)
            else:
                child_terminal_error = "child did not reach a terminal state"
    failed = (
        not matching
        or bool(isinstance(tool_result, dict) and tool_result.get("failed"))
        or any(marker in raw_content.casefold() for marker in ERROR_MARKERS)
        or any(str(expected) not in raw_content for expected in case.get("expect") or [])
        or bool(child_terminal_error)
    )
    summary = {
        "session_id": next((str(trace.get("session_id")) for trace in traces if trace.get("session_id")), ""),
        "content_preview": raw_content[:500],
    }
    if child_terminal_error:
        summary["child_terminal_error"] = child_terminal_error[:500]
    if failed:
        ledger["failed"][tool_name] = summary
        status = "failed"
    else:
        ledger["passed"][tool_name] = summary
        ledger["failed"].pop(tool_name, None)
        status = "passed"
    _save_ledger(ledger)
    return status


def run(case_path: Path, only: str = "", phase: str = "") -> None:
    """串行执行 case 文件，自动跳过已经通过的工具。"""

    cases = json.loads(case_path.read_text(encoding="utf-8"))
    ledger = _load_ledger()
    for case in cases:
        if only and case.get("tool") != only:
            continue
        if phase and case.get("phase") != phase:
            continue
        status = run_case(case, ledger)
        print(f"{case['tool']}={status}")
    print(f"passed={len(ledger['passed'])} failed={len(ledger['failed'])}")


def status() -> None:
    """输出真实注册表中尚未取得 API 通过证据的工具。"""

    ledger = _load_ledger()
    registered = [str(item["name"]) for item in _request_json("GET", "/agent/tools")["tools"]]
    missing = [name for name in registered if name not in ledger["passed"]]
    print(f"registered={len(registered)} passed={len(ledger['passed'])} failed={len(ledger['failed'])} missing={len(missing)}")
    print("\n".join(missing))


def inspect_session(session_id: str) -> None:
    """输出指定审计会话的脱敏角色、工具调用名和正文预览。"""

    messages = _request_json("GET", f"/sessions/{session_id}/messages?user_id={USER_ID}")
    for message in messages:
        calls = [str(item.get("name") or "") for item in message.get("tool_calls") or []]
        print(json.dumps({
            "role": message.get("role"),
            "tool_calls": calls,
            "content": str(message.get("content") or "")[:300],
        }, ensure_ascii=False))
    children = _request_json("GET", f"/agent/children?session_id={session_id}")
    print(json.dumps({"children": children.get("children")}, ensure_ascii=False)[:8000])


def recheck_child() -> None:
    """按真实终态纠正曾被过早记为通过的 spawn 记录。"""

    ledger = _load_ledger()
    entry = ledger["passed"].get("spawn_child_agent")
    if not isinstance(entry, dict):
        return
    session_id = str(entry.get("session_id") or "")
    run_id_match = re.search(r'"run_id":\s*"([^"]+)"', str(entry.get("content_preview") or ""))
    children = _request_json("GET", f"/agent/children?session_id={session_id}")["children"]
    child = next((item for item in children if run_id_match and item.get("run_id") == run_id_match.group(1)), None)
    if str((child or {}).get("status") or "") != "completed":
        ledger["failed"]["spawn_child_agent"] = {
            **entry,
            "child_terminal_error": str((child or {}).get("error") or "child not completed")[:500],
        }
        ledger["passed"].pop("spawn_child_agent", None)
        _save_ledger(ledger)
        print("spawn_child_agent=reclassified_failed")


def main() -> None:
    """解析命令行并执行配置或真实 API 验收。"""

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("configure")
    subparsers.add_parser("setup")
    subparsers.add_parser("setup-child")
    subparsers.add_parser("setup-vision")
    subparsers.add_parser("repair-child")
    subparsers.add_parser("cleanup")
    subparsers.add_parser("status")
    inspect_parser = subparsers.add_parser("inspect-session")
    inspect_parser.add_argument("session_id")
    subparsers.add_parser("recheck-child")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("case_file", type=Path)
    run_parser.add_argument("--only", default="")
    run_parser.add_argument("--phase", default="")
    args = parser.parse_args()
    if args.command == "configure":
        configure()
    elif args.command == "setup":
        setup()
    elif args.command == "setup-child":
        setup_child()
    elif args.command == "setup-vision":
        setup_vision()
    elif args.command == "repair-child":
        repair_child()
    elif args.command == "cleanup":
        cleanup()
    elif args.command == "status":
        status()
    elif args.command == "inspect-session":
        inspect_session(args.session_id)
    elif args.command == "recheck-child":
        recheck_child()
    else:
        run(args.case_file, args.only, args.phase)


if __name__ == "__main__":
    main()
