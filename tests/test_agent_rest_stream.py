"""验证 Agent SSE 早期异常、终止和事件生产者资源回收。

使用真实线程与受控事件验证 REST 流封装，不启动模型或网络端口。
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from agent_service.api.rest import agent as agent_rest


@pytest.mark.parametrize("partial", [False, True])
def test_agent_stream_reports_generator_failure_before_done(partial) -> None:
    """上下文构建或中途输出失败必须产生可见错误，不能只留下心跳/空终态。"""

    def events():
        """模拟在第一次或第二次取事件时发生的实际业务异常。"""

        if partial:
            yield {"node": "agent", "content": "already delivered"}
        raise RuntimeError("private-context-detail")

    frames = list(agent_rest._to_sse(events()))
    data = [frame for frame in frames if frame.startswith("data:")]
    assert data[-1] == "data: [DONE]\n\n"
    payloads = [json.loads(frame.removeprefix("data: ")) for frame in data[:-1]]
    assert len(payloads) == (2 if partial else 1)
    assert payloads[-1]["node"] == "error"
    assert payloads[-1]["content"]
    assert payloads[-1]["error"] == "internal server error"
    assert "private-context-detail" not in "".join(frames)


def test_agent_stream_disconnect_closes_source_and_joins_heartbeat(monkeypatch) -> None:
    """客户端关闭后 source 由生产线程关闭，两条流专属线程均退出。"""

    release, source_closed, consumer_closed = threading.Event(), threading.Event(), threading.Event()
    stream_threads = []

    def spawn(*args, **kwargs):
        """记录封装真正创建的两个线程，测试不依赖全局线程名称。"""

        thread = threading.Thread(*args, **kwargs)
        stream_threads.append(thread)
        return thread

    monkeypatch.setattr(agent_rest, "threading", SimpleNamespace(Event=threading.Event, Thread=spawn))

    class Source:
        """第二个事件受控阻塞，允许在 generator 正在生产时关闭 consumer。"""

        def __init__(self):
            self.index = 0

        def __iter__(self):
            return self

        def __next__(self):
            self.index += 1
            if self.index == 1:
                return {"node": "agent", "content": "first"}
            if self.index == 2:
                assert release.wait(2)
                return {"node": "agent", "content": "late"}
            raise StopIteration

        def close(self):
            """观察只有 source owner 能安全执行的回收。"""

            source_closed.set()

    stream = agent_rest._to_sse(Source())
    assert "first" in next(stream)

    def close_consumer():
        """让主测试线程有机会释放正在等待的生产者。"""

        stream.close()
        consumer_closed.set()

    closer = threading.Thread(target=close_consumer, daemon=True)
    closer.start()
    try:
        release.set()
        closer.join(timeout=2)
        assert consumer_closed.is_set()
        assert source_closed.wait(1)
        assert len(stream_threads) == 2
        assert all(not thread.is_alive() for thread in stream_threads)
    finally:
        release.set()
        closer.join(timeout=2)
        for thread in stream_threads:
            thread.join(timeout=2)
