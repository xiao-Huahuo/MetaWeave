"""同步提问合同：每题独立选择或输入，前端按题 ID 提交真实回答。"""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS


class UserQuestion(BaseModel):
    """单题定义；选择题可多选，输入题只收文本，同批可包含不同题型。"""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(default="", description="本次提问内唯一的题目 ID。")
    question: str = Field(min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length, description="用户需要回答的单一问题。")
    type: Literal["select", "input"] = Field(default="select", description="select 只选择；input 只输入。")
    options: list[str] = Field(default_factory=list, description="选择题的完整选项；输入题必须为空。")
    multi_select: bool = Field(default=False, description="仅选择题可启用多选。")
    allow_text: bool = Field(default=False, description="兼容旧客户端的派生字段，仅输入题为 true。")

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_type(cls, data):
        """仅兼容旧纯输入调用；旧选择加自由输入合同仍由后续校验拒绝。"""
        if isinstance(data, dict) and "type" not in data and data.get("allow_text") and not data.get("options"):
            return {**data, "type": "input"}
        return data

    @model_validator(mode="after")
    def validate_options(self):
        """拒绝空题、重复选项，以及将选择和输入混在同一题的参数。"""
        if not self.question.strip() or any(not option.strip() for option in self.options):
            raise ValueError("问题和选项不能为空")
        if len(set(self.options)) != len(self.options):
            raise ValueError("选项不能重复")
        if self.type == "input":
            if self.options or self.multi_select:
                raise ValueError("输入题不能包含选项或启用多选，请拆成独立问题")
        elif not self.options or self.allow_text:
            raise ValueError("选择题必须提供选项且不能同时要求输入，请使用独立的输入题")
        self.allow_text = self.type == "input"
        return self


class UserQuestionAnswer(BaseModel):
    """单题回答；选择题只传选项，输入题只传文本，由服务按题型校验。"""

    model_config = ConfigDict(extra="forbid")
    selected_options: list[str] = Field(default_factory=list)
    text: str = ""


class UserQuestionSubmission(BaseModel):
    """REST 提交合同，用户和会话必须与当前等待请求完全匹配。"""

    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length)
    session_id: str = Field(min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length)
    answers: dict[str, UserQuestionAnswer]
