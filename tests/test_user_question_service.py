"""同步提问回归：真实 SQLite 持久化、受控线程暂停和终态回收，不请求模型。"""

import json
from queue import Queue
from threading import Event, Thread

import pytest
from sqlmodel import SQLModel, create_engine

from agent_service.core.agent_config import AgentConfig
from agent_service.schemas.user_question import UserQuestion, UserQuestionAnswer
from agent_service.services.message.service import MessageService
from agent_service.services.user_question.service import UserQuestionService


@pytest.fixture
def service(tmp_path):
    """隔离正式消息服务和数据库，所有业务写入均走 MessageService。"""
    config = AgentConfig.load_config({"storage": {"project_root": str(tmp_path)},
                                     "limits": {"agent_stream_queue_poll_seconds": .01}},
                                    load_env=False, load_dotenv=False, ensure_directories=False, ensure_models=False)
    engine = create_engine(f"sqlite:///{tmp_path / 'questions.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    messages = MessageService(config=config, engine=engine, create_tables=False)
    instance = UserQuestionService(config=config, message_service=messages)
    yield instance
    instance.close()
    engine.dispose()


def start_question(service, *, session="s1", questions=None):
    """问题发布后图线程停在真实服务等待点，测试可通过 API 合同回答。"""
    events, results, cancel = Queue(), [], Event()

    def run():
        """记录成功与异常，避免丢失后台线程失败。"""
        try:
            results.append(json.loads(service.ask(
                questions=questions or [{"question": "选择处理方式", "options": ["阅读", "编辑"]}],
                user_id="u1", session_id=session, run_id=session, cancel_event=cancel, emit=events.put)))
        except BaseException as exc:
            results.append(exc)

    thread = Thread(target=run)
    thread.start()
    request = events.get(timeout=3)["question_request"]
    return thread, request, cancel, results, events


def answer(service, request, answers=None):
    """构造与前端一致的回答 DTO。"""
    return service.submit(request_id=request["request_id"], user_id="u1", session_id=request["session_id"],
                          answers=answers or {"q1": UserQuestionAnswer(selected_options=["阅读"])})


@pytest.mark.parametrize("question", [
    {"question": "请选择方向，并补充角色名", "options": ["其他角色"], "allow_text": True},
    {"question": "填写角色名", "allow_text": True, "multi_select": True},
    {"question": "请选择", "type": "select", "options": ["其他角色"], "allow_text": True},
    {"question": "请选择", "type": "select"},
    {"question": "填写角色名", "type": "input", "options": ["芙宁娜"]},
    {"question": "填写角色名", "type": "input", "multi_select": True},
])
def test_question_rejects_combined_choice_and_input(question):
    """复现同题允许先选择后填写的缺陷；旧合同也不能绕过题型隔离。"""
    with pytest.raises(ValueError):
        UserQuestion.model_validate(question)


@pytest.mark.parametrize("question,expected_type", [
    ({"question": "请选择", "options": ["甲", "乙"]}, "select"),
    ({"question": "填写角色名", "allow_text": True}, "input"),
    ({"question": "请选择", "type": "select", "options": ["甲", "乙"], "multi_select": True}, "select"),
    ({"question": "填写角色名", "type": "input"}, "input"),
])
def test_question_normalizes_explicit_and_legacy_pure_types(question, expected_type):
    """新题型明确返回，旧纯选择／纯输入兼容，allow_text 仅为客户端派生字段。"""
    parsed = UserQuestion.model_validate(question).model_dump()
    assert parsed["type"] == expected_type
    assert parsed["allow_text"] is (expected_type == "input")
    if expected_type == "input":
        assert parsed["options"] == [] and parsed["multi_select"] is False


def test_question_tool_exposes_nested_types_to_the_model():
    """真正绑定给模型的工具合同保留每题题型，且不再宣传同题自由输入。"""
    from agent_service.tools import ToolRegistry

    registry = ToolRegistry.with_builtin_tools()
    tool = registry._to_langchain_tool(registry.get("request_user_input"))
    schema = tool.args_schema if isinstance(tool.args_schema, dict) else tool.args_schema.model_json_schema()
    question = schema["properties"]["questions"]["items"]
    assert question["properties"]["type"]["enum"] == ["select", "input"]
    assert "type" in question["required"]
    assert "allow_text" not in question["properties"]


def test_pauses_and_persists_before_resuming(service):
    """回答前执行未完成，回答后同一请求恢复且正式消息保存问答。"""
    thread, request, cancel, results, events = start_question(service)
    try:
        assert thread.is_alive() and results == []
        assert service.list_pending(user_id="u1", session_id="s1") == [request]
        assert service.list_pending(user_id="u2", session_id="s1") == []
        result = answer(service, request)
        thread.join(3)
        assert not thread.is_alive()
        assert results == [result]
        assert result["answers"]["q1"]["selected_options"] == ["阅读"]
        assert events.get(timeout=1)["type"] == "user_question_resolved"
        rows = service.message_service.list_session_messages(user_id="u1", session_id="s1", limit=None)
        assert rows[0].metadata_json["user_question"] == result
        assert service.list_pending(user_id="u1", session_id="s1") == []
        with pytest.raises(KeyError):
            answer(service, request)
    finally:
        cancel.set()
        thread.join(3)


def test_batch_validation_does_not_resume_on_invalid_or_cross_session_answers(service):
    """漏答和跨用户／会话回答不能唤醒；合法多选与手动输入原样交还。"""
    questions = [{"id": "choose", "question": "选哪些", "type": "select", "options": ["甲", "乙"], "multi_select": True},
                 {"id": "text", "question": "填写角色名", "type": "input"}]
    thread, request, cancel, results, _ = start_question(service, questions=questions)
    try:
        assert [question["type"] for question in request["questions"]] == ["select", "input"]
        valid = {"choose": UserQuestionAnswer(selected_options=["甲", "乙"]), "text": UserQuestionAnswer(text="芙宁娜")}
        for user, session in [("u2", "s1"), ("u1", "s2")]:
            with pytest.raises(PermissionError):
                service.submit(request_id=request["request_id"], user_id=user, session_id=session, answers=valid)
        for invalid in [{}, {"choose": valid["choose"]}, {**valid, "choose": UserQuestionAnswer(selected_options=["陌生选项"])},
                        {**valid, "choose": UserQuestionAnswer(selected_options=["甲", "甲"])},
                        {**valid, "text": UserQuestionAnswer(text="  ")},
                        {**valid, "text": UserQuestionAnswer(selected_options=["甲"], text="芙宁娜")},
                        {**valid, "choose": UserQuestionAnswer(selected_options=["甲"], text="芙宁娜")},
                        {**valid, "choose": UserQuestionAnswer(selected_options=["甲"], text=" ")},
                        {**valid, "choose": UserQuestionAnswer(text="不允许") }]:
            with pytest.raises(ValueError):
                answer(service, request, invalid) if invalid else service.submit(request_id=request["request_id"], user_id="u1", session_id="s1", answers=invalid)
            assert results == [] and thread.is_alive()
        result = answer(service, request, valid)
        thread.join(3)
        assert result["answers"]["choose"]["selected_options"] == ["甲", "乙"]
        assert result["answers"]["text"]["text"] == "芙宁娜"
    finally:
        cancel.set()
        thread.join(3)


@pytest.mark.parametrize("finish", ["cancel", "timeout", "close"])
def test_all_wait_termination_paths_release_resources(service, finish):
    """超时、会话取消与应用关闭均终结等待、保存终态并释放资源。"""
    if finish == "timeout":
        service.config.limits.agent_question_timeout_seconds = .01
    thread, request, cancel, results, _ = start_question(service)
    if finish == "cancel":
        cancel.set()
    elif finish == "close":
        service.close()
    thread.join(3)
    assert not thread.is_alive()
    assert results[0]["status"] == ("timed_out" if finish == "timeout" else "cancelled")
    assert service.list_pending(user_id="u1", session_id="s1") == []
    rows = service.message_service.list_session_messages(user_id="u1", session_id="s1", limit=None)
    assert rows[0].metadata_json["user_question"]["status"] == results[0]["status"]


def test_sessions_complete_out_of_order_independently(service):
    """两个并行会话乱序回答，一个失败不会影响另一个等待者。"""
    first = start_question(service, session="first")
    second = start_question(service, session="second")
    try:
        answer(service, second[1])
        second[0].join(3)
        assert first[0].is_alive() and not first[3]
        first[2].set()
        first[0].join(3)
        assert first[3][0]["status"] == "cancelled"
        assert second[3][0]["status"] == "answered"
    finally:
        for thread, _, cancel, _, _ in [first, second]:
            cancel.set()
            thread.join(3)


def test_persistence_failure_never_acknowledges_success(service, monkeypatch):
    """保存失败必须同时释放 Agent 和 REST 的等待，不能假确认成功。"""
    thread, request, cancel, results, _ = start_question(service)

    def fail(*args, **kwargs):
        """模拟真实数据库提交失败。"""
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service.message_service, "update_message", fail)
    try:
        with pytest.raises(RuntimeError, match="database unavailable"):
            answer(service, request)
        thread.join(3)
        assert isinstance(results[0], RuntimeError)
        assert service.list_pending(user_id="u1", session_id="s1") == []
    finally:
        cancel.set()
        thread.join(3)


def test_duplicate_submission_is_rejected_while_first_answer_is_persisting(service, monkeypatch):
    """持久化期间重复投递不得覆盖答案或重复唤醒，锁内不等待数据库。"""
    thread, request, cancel, results, _ = start_question(service)
    saving, release, receipts = Event(), Event(), []
    original = service.message_service.update_message

    def blocked_save(*args, **kwargs):
        """用可控事件模拟慢数据库提交，不依赖时间碰撞。"""
        saving.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(service.message_service, "update_message", blocked_save)
    submitter = Thread(target=lambda: receipts.append(answer(service, request)))
    submitter.start()
    try:
        assert saving.wait(3)
        with pytest.raises(RuntimeError, match="回答已提交"):
            answer(service, request)
        assert thread.is_alive() and not results and not receipts
        # 同一时间仍可读取索引，证明数据库 I/O 不持有索引锁。
        assert service.list_pending(user_id="u1", session_id="s1")
        release.set()
        thread.join(3)
        submitter.join(3)
        assert len(receipts) == 1 and results == receipts
    finally:
        release.set()
        cancel.set()
        thread.join(3)
        submitter.join(3)


def test_invalid_questions_and_event_failure_leave_no_waiter(service):
    """工具参数验证及事件发布失败均不能留下永久等待请求。"""
    for questions in [[], [{"question": " "}], [{"question": "x", "options": ["x", "x"]}],
                      [{"id": "same", "question": "x", "options": ["x"]}] * 2]:
        with pytest.raises(ValueError):
            service.ask(questions=questions, user_id="u1", session_id="s1", run_id="r1", cancel_event=Event(), emit=lambda event: None)

    def fail_emit(event):
        """模拟源事件消费者失败。"""
        raise RuntimeError("event consumer failed")

    with pytest.raises(RuntimeError, match="event consumer failed"):
        service.ask(questions=[{"question": "x", "options": ["x"]}], user_id="u1", session_id="s1", run_id="r1", cancel_event=Event(), emit=fail_emit)
    assert service.list_pending(user_id="u1", session_id="s1") == []


def test_rest_contract_validation_and_cross_session_isolation(service):
    """正式 REST DTO 拒绝漏答和越权，合法请求经服务层保存后才返回 200。"""
    from types import SimpleNamespace
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from agent_service.api.rest.agent import router
    from agent_service.api.rest.deps import bind_application_services

    app = FastAPI()
    app.state.services = SimpleNamespace(agent=SimpleNamespace(user_question_service=service))
    app.include_router(router, dependencies=[Depends(bind_application_services)])
    thread, request, cancel, results, _ = start_question(service)
    path = f"/agent/questions/{request['request_id']}/answer"
    body = {"user_id": "u1", "session_id": "s1", "answers": {"q1": {"selected_options": ["阅读"], "text": ""}}}
    try:
        with TestClient(app) as client:
            assert client.get("/agent/questions", params={"user_id": "u1", "session_id": "s1"}).json()["requests"] == [request]
            assert client.post(path, json={**body, "answers": {}}).status_code == 422
            assert client.post(path, json={**body, "user_id": "u2"}).status_code == 403
            assert client.post(path, json={**body, "session_id": "s2"}).status_code == 403
            assert client.post(path, json={**body, "answers": {"q1": {"selected_options": ["阅读", "编辑"]}}}).status_code == 422
            response = client.post(path, json=body)
            assert response.status_code == 200
            assert response.json()["request"]["status"] == "answered"
            assert client.post(path, json=body).status_code == 404
        thread.join(3)
        assert results[0]["status"] == "answered"
    finally:
        cancel.set()
        thread.join(3)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_question_timeouts_must_be_bounded(value):
    """非法服务配置不能把图线程或 REST 确认变成永久等待。"""
    for name in ("agent_question_timeout_seconds", "agent_question_submit_timeout_seconds"):
        with pytest.raises(ValueError, match="有限正数"):
            AgentConfig.BusinessLimitsConfig(**{name: value})
