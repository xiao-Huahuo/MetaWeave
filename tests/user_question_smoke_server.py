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
        questions = [{"id": "q1", "type": "select", "question": "如何处理这份资料？", "options": ["阅读并总结", "保留原文"]}]
        conditional = "条件追问" in prompt
        if conditional:
            questions = [{"id": "q1", "type": "select", "question": "接下来做什么？", "options": ["比较角色机制", "结束任务"]}]
        if "多题" in prompt:
            questions += [{"id": "q2", "type": "select", "question": "需要哪些输出内容？", "options": ["摘要", "引用", "待办"], "multi_select": True},
                          {"id": "q3", "type": "input", "question": "请输入角色名。"}]
        elif "多选" in prompt:
            questions[0]["multi_select"] = True
        elif "输入" in prompt:
            questions = [{"id": "q1", "type": "input", "question": "请输入角色名。"}]
        if "长选项" in prompt:
            questions[0]["question"] = "接下来把《原神》的多资料对照推向哪个方向？"
            questions[0]["options"] = [
                "深化议题 A：《日月前事》与法涅斯／四影——纳入 BWIKI 白夜国馆藏另 4 卷，核实常世大神与伊斯塔露的身份和真实出处",
                "加固议题 B：知识地图口径对照——把报告转引的外部来源取入库，逐条核对公开资料与一手原文",
                "改为讨论角色机制，下一题填写角色名",
                "到此结束，不再展开",
            ]
        table = "\n\n| 资料 | 依据 | 对照结果 |\n| --- | --- | --- |\n| 技能与命座 | 游戏内原文 | 保留机制与适配条件 |\n| 社区观点 | 明确作者与时间 | 区分体验和可核验事实 |"
        if "宽表" in prompt:
            headings = [f"队伍适配条件{i}" for i in range(1, 11)]
            table = "\n\n| " + " | ".join(headings) + " |\n| " + " | ".join(["---"] * 10) + " |\n| " + " | ".join(["原文依据与角色机制"] * 10) + " |"
        message = AIMessage(content="请先选择处理方式。" + table, tool_calls=[{"id": "call_question", "name": "request_user_input", "args": {"questions": questions}}])
        yield {"agent": {"messages": [message], "trace": []}}
        action = self.tool_node({**inputs, "messages": [message]})
        yield {"action": action}
        result = json.loads(action["messages"][0].content)
        if conditional and result["status"] == "answered" and result["answers"]["q1"]["selected_options"] == ["比较角色机制"]:
            role_message = AIMessage(content="还需要你提供角色名。", tool_calls=[{
                "id": "call_role_input", "name": "request_user_input",
                "args": {"questions": [{"id": "role", "type": "input", "question": "请输入角色名。"}]},
            }])
            yield {"agent": {"messages": [role_message], "trace": []}}
            role_action = self.tool_node({**inputs, "messages": [role_message]})
            yield {"action": role_action}
            result = json.loads(role_action["messages"][0].content)
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
