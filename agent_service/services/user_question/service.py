"""同步提问服务。

AgentCore 拥有本服务；图执行线程独占问题状态及 MessageService 数据库写入。
REST 只投递回答并等待持久化确认，内存索引仅定位活跃等待者，不承担业务持久化。
取消、超时、关闭及异常都会终结请求并释放索引；锁内只操作内存。
"""

from concurrent.futures import Future
from dataclasses import dataclass, field
import json
import logging
from threading import Event, Lock
from time import monotonic
from typing import Any, Callable
from uuid import uuid4

from pydantic import TypeAdapter

from agent_service.schemas.message import MessageCreate, MessageUpdate
from agent_service.schemas.user_question import UserQuestion, UserQuestionAnswer

logger = logging.getLogger(__name__)


@dataclass
class PendingQuestion:
    """单次调用的等待信号和回答投递槽，由提问的图线程最终回收。"""

    payload: dict[str, Any]
    wake: Event = field(default_factory=Event)
    submission: tuple[dict[str, UserQuestionAnswer], Future] | None = None


class UserQuestionService:
    """使用原有会话消息表保存问题和回答，不创建独立连接池或后台线程。"""

    def __init__(self, *, config, message_service=None):
        """绑定应用配置和正式消息服务，内存锁只保护等待者索引。"""
        self.config = config
        self.message_service = message_service
        self._lock = Lock()
        self._pending: dict[str, PendingQuestion] = {}
        self._closed = Event()

    def list_pending(self, *, user_id: str, session_id: str) -> list[dict[str, Any]]:
        """恢复仍在执行的请求；跨用户、跨会话请求不会泄露。"""
        with self._lock:
            payloads = [entry.payload for entry in self._pending.values()
                        if entry.payload["user_id"] == user_id and entry.payload["session_id"] == session_id]
        return json.loads(json.dumps(payloads))

    def submit(self, *, request_id: str, user_id: str, session_id: str,
               answers: dict[str, UserQuestionAnswer]) -> dict[str, Any]:
        """校验并原子投递一次回答，持久化成功后才向客户端确认。"""
        with self._lock:
            entry = self._pending.get(request_id)
            if entry is None:
                raise KeyError("提问已结束或不存在")
            if entry.payload["user_id"] != user_id or entry.payload["session_id"] != session_id:
                raise PermissionError("不能回答其他用户或会话的问题")
            if entry.submission is not None:
                raise RuntimeError("回答已提交")
            self._validate_answers(entry.payload["questions"], answers)
            receipt = Future()
            entry.submission = (answers, receipt)
        entry.wake.set()
        return receipt.result(timeout=self.config.limits.agent_question_submit_timeout_seconds)

    @staticmethod
    def _validate_answers(questions: list[dict], answers: dict[str, UserQuestionAnswer]) -> None:
        """拒绝漏题、非法选项或多选，以及与独立题型不符的回答。"""
        if set(answers) != {question["id"] for question in questions}:
            raise ValueError("请回答所有问题")
        for question in questions:
            answer = answers[question["id"]]
            selected = answer.selected_options
            if question["type"] == "input":
                if selected or not answer.text.strip():
                    raise ValueError("输入题只能提交非空文本")
                continue
            if len(set(selected)) != len(selected) or not set(selected).issubset(question["options"]):
                raise ValueError("回答含无效或重复选项")
            if not question["multi_select"] and len(selected) > 1:
                raise ValueError("本题只能单选")
            if answer.text:
                raise ValueError("选择题不能同时提交文本，请使用独立的输入题")
            if not selected:
                raise ValueError("请回答所有问题")

    def ask(self, *, questions: list[dict], user_id: str, session_id: str, run_id: str,
            cancel_event: Event, emit: Callable[[dict], None], message_service=None) -> str:
        """阻塞当前图节点，收到回答并保存后返回工具结果，期间不发起模型调用。"""
        if self._closed.is_set():
            raise RuntimeError("提问服务已关闭")
        messages = message_service or self.message_service
        parsed = TypeAdapter(list[UserQuestion]).validate_python(questions)
        if not parsed:
            raise ValueError("至少需要一个问题")
        for index, question in enumerate(parsed):
            question.id = question.id.strip() or f"q{index + 1}"
        if len({question.id for question in parsed}) != len(parsed):
            raise ValueError("问题 ID 不能重复")
        payload = {"request_id": f"question_{uuid4().hex}", "user_id": user_id,
                   "session_id": session_id, "run_id": run_id, "status": "pending",
                   "questions": [question.model_dump() for question in parsed]}
        entry = PendingQuestion(payload)
        message_id = None
        receipt = None
        if messages is not None:
            message_id = messages.create_message(MessageCreate(
                user_id=user_id, session_id=session_id, role="system",
                content=json.dumps(payload, ensure_ascii=False),
                metadata_json={"user_question": payload},
            )).message_id
        with self._lock:
            self._pending[payload["request_id"]] = entry
        deadline = monotonic() + self.config.limits.agent_question_timeout_seconds
        result = {**payload}
        try:
            emit({"type": "user_question", "node": "user_question", "content": "", "question_request": payload})
            while True:
                with self._lock:
                    submission = entry.submission
                    if submission is None and (cancel_event.is_set() or self._closed.is_set() or monotonic() >= deadline):
                        self._pending.pop(payload["request_id"], None)
                        result["status"] = "cancelled" if cancel_event.is_set() or self._closed.is_set() else "timed_out"
                        break
                if submission is not None:
                    answers, receipt = submission
                    result.update(status="answered", answers={key: answer.model_dump() for key, answer in answers.items()})
                    break
                entry.wake.wait(timeout=min(self.config.limits.agent_stream_queue_poll_seconds, max(0, deadline - monotonic())))
            self._persist(message_id, result, messages)
            with self._lock:
                self._pending.pop(payload["request_id"], None)
            emit({"type": "user_question_resolved", "node": "user_question", "content": "", "question_request": result})
            if receipt is not None:
                receipt.set_result(result)
            return json.dumps(result, ensure_ascii=False)
        except BaseException as exc:
            result["status"] = "failed"
            try:
                self._persist(message_id, result, messages)
            except Exception as persist_error:
                # 数据库异常文本可能包含完整问答参数，只记录类型和请求标识。
                logger.error("提问终态保存失败 | request=%s error_type=%s", payload["request_id"], type(persist_error).__name__)
            with self._lock:
                submission = entry.submission
            if submission is not None and not submission[1].done():
                submission[1].set_exception(exc)
            raise
        finally:
            with self._lock:
                self._pending.pop(payload["request_id"], None)

    def _persist(self, message_id: str | None, result: dict, messages) -> None:
        """图线程更新同一条正式事件日志，回答内容跨重启保留。"""
        if message_id is not None:
            updated = messages.update_message(message_id, MessageUpdate(
                content=json.dumps(result, ensure_ascii=False), metadata_json={"user_question": result}))
            if updated is None:
                raise RuntimeError("提问会话记录已删除")

    def close(self) -> None:
        """应用关闭时唤醒所有等待者，由各自的图线程持久化取消并清理。"""
        self._closed.set()
        with self._lock:
            entries = list(self._pending.values())
        for entry in entries:
            entry.wake.set()
