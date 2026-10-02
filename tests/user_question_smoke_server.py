"""浏览器验收专用服务：确定性图代替 LLM，使用真实 AgentCore、工具节点、REST 与 SQLite。

仅运行测试时启动：python -m uvicorn tests.user_question_smoke_server:app --port 8002。
数据库位于 TemporaryDirectory，lifespan 关闭等待者、调度器及连接后清理。
"""

from contextlib import asynccontextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from langchain_core.messages import AIMessage, HumanMessage
from sqlmodel import SQLModel

from agent_service.agent_core import AgentCore
from agent_service.agent_core.nodes.tool_call import ToolCallNode
from agent_service.api.rest.agent import router
from agent_service.api.rest.deps import bind_application_services
from agent_service.core.agent_config import AgentConfig
from agent_service.core.db.engine import get_database_engine
from agent_service.schemas.message import MessageCreate
from agent_service.services.message.service import MessageService
from agent_service.tools import ToolExecutor, ToolRegistry


class TestScheduler:
    """确定性测试图不调用模型，仍提供应用关闭所需的生命周期接口。"""

    def shutdown(self):
        """此测试调度器没有线程或模型资源。"""


class QuestionGraph:
    """发布真实工具调用；ToolCallNode 返回前不会执行后续回答节点。"""

    def __init__(self, config):
        """复用正式注册表与工具执行器。"""
        self.tool_node = ToolCallNode(config=config, tool_executor=ToolExecutor(registry=ToolRegistry.with_builtin_tools()))

    def get_graph(self):
        """提供 AgentCore 初始化图形导出的最小图结构。"""
        return SimpleNamespace(nodes={"__start__": object(), "agent": object(), "action": object(), "__end__": object()}, edges=[])

    def stream(self, inputs, **kwargs):
        """按测试提示选择问题，仅将真实提交的回答传给最后一个节点。"""
        prompt = inputs["messages"][-1].content
        questions = [{"id": "q1", "question": "如何处理这份资料？", "options": ["阅读并总结", "保留原文"]}]
        if "多题" in prompt:
            questions += [{"id": "q2", "question": "需要哪些输出内容？", "options": ["摘要", "引用", "待办"], "multi_select": True},
                          {"id": "q3", "question": "还有哪些需要保留的细节？", "allow_text": True}]
        elif "多选" in prompt:
            questions[0]["multi_select"] = True
        elif "输入" in prompt:
            questions = [{"id": "q1", "question": "请填写你希望保留的内容。", "allow_text": True}]
        message = AIMessage(content="请先选择处理方式。", tool_calls=[{"id": "call_question", "name": "request_user_input", "args": {"questions": questions}}])
        yield {"agent": {"messages": [message], "trace": []}}
        action = self.tool_node({**inputs, "messages": [message]})
        yield {"action": action}
        result = json.loads(action["messages"][0].content)
        if result["status"] == "answered":
            yield {"agent": {"messages": [AIMessage(content="已收到回答，继续处理：" + json.dumps(result["answers"], ensure_ascii=False))], "trace": []}}


class SmokeAgent(AgentCore):
    """仅跳过模型与检索前置流程；正式流运行器和工具节点保持真实。"""

    def stream_session_prompt(self, *, prompt, user_id, session_id, **kwargs):
        """保存真实用户消息后，在正常图线程及取消生命周期内运行。"""
        self.message_service.create_message(MessageCreate(user_id=user_id, session_id=session_id, role="user", content=prompt))
        yield from self._stream_events(messages=[HumanMessage(content=prompt)], user_id=user_id, session_id=session_id,
                                       message_service=self.message_service, turn_started_at=perf_counter())


@asynccontextmanager
async def lifespan(app):
    """所有测试资源由应用拥有并在关闭时回收。"""
    with TemporaryDirectory(prefix="mw-questions-") as directory:
        root = Path(directory)
        config = AgentConfig.load_config({"storage": {"project_root": str(root), "base_data_dir": str(root / "runtime")}},
                                        load_env=False, load_dotenv=False, ensure_models=False)
        engine = get_database_engine(config)
        SQLModel.metadata.create_all(engine)
        messages = MessageService(config=config, engine=engine, create_tables=False)
        agent = SmokeAgent(config=config, graph=QuestionGraph(config), message_service=messages, task_scheduler=TestScheduler())
        app.state.services = SimpleNamespace(agent=agent, message_service=messages)
        try:
            yield
        finally:
            agent.close()
            engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(router, dependencies=[Depends(bind_application_services)])


@app.get("/agent/question-smoke/status")
def status(user_id: str, session_id: str):
    """验收时直接检查正式消息表中的问答及恢复后的输出。"""
    messages = app.state.services.message_service.list_session_messages(user_id=user_id, session_id=session_id, limit=None)
    return {"questions": [message.metadata_json["user_question"] for message in messages if "user_question" in message.metadata_json],
            "final": [message.content for message in messages if message.role == "assistant" and "已收到回答" in message.content]}
