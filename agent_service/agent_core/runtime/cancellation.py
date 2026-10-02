"""Agent 会话取消状态管理。

``CancellationRuntime`` 统一注册、触发、查询和清理每个 session 的线程事件，避免
AgentCore 自己维护散落字典和锁。
"""

from __future__ import annotations

import threading


class CancellationRuntime:
    """线程安全地管理当前进程中的会话取消事件。"""

    def __init__(self) -> None:
        """创建空事件表和保护锁。"""

        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def register(self, session_id: str) -> threading.Event:
        """为一轮运行创建并登记新的取消事件。"""

        event = threading.Event()
        with self._lock:
            self._events[session_id] = event
        return event

    def cancel(self, session_id: str) -> bool:
        """触发已登记会话的取消事件，未运行时返回 False。"""

        with self._lock:
            event = self._events.get(session_id)
        if event is None:
            return False
        event.set()
        return True

    def clear(self, session_id: str, owner_event: threading.Event | None = None) -> None:
        """在运行结束后移除会话事件。"""

        with self._lock:
            if owner_event is None or self._events.get(session_id) is owner_event:
                self._events.pop(session_id, None)

    def cancel_all(self) -> None:
        """Signal owned turns before shutting down MCP connections or model workers."""
        with self._lock:
            events = list(self._events.values())
        for event in events:
            event.set()
