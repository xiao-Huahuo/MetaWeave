"""同步提问合同：Agent 指定问题与选项，前端按题 ID 提交真实回答。"""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from agent_service.core.agent_config import DEFAULT_BUSINESS_LIMITS


class UserQuestion(BaseModel):
    """单题定义；多选和自由输入必须由 Agent 显式启用。"""

    model_config = ConfigDict(extra="forbid")
    id: str = ""
    question: str = Field(min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length)
    options: list[str] = Field(default_factory=list)
    multi_select: bool = False
    allow_text: bool = False

    @model_validator(mode="after")
    def validate_options(self):
        """拒绝空题目、重复选项和没有任何回答入口的问题。"""
        if not self.question.strip() or any(not option.strip() for option in self.options):
            raise ValueError("问题和选项不能为空")
        if len(set(self.options)) != len(self.options):
            raise ValueError("选项不能重复")
        if not self.options and not self.allow_text:
            raise ValueError("问题至少需要一个选项或允许手动输入")
        return self


class UserQuestionAnswer(BaseModel):
    """单题回答；选项文字原样返回，手动输入与选项一起提交。"""

    model_config = ConfigDict(extra="forbid")
    selected_options: list[str] = Field(default_factory=list)
    text: str = ""


class UserQuestionSubmission(BaseModel):
    """REST 提交合同，用户和会话必须与当前等待请求完全匹配。"""

    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length)
    session_id: str = Field(min_length=DEFAULT_BUSINESS_LIMITS.nonempty_min_length)
    answers: dict[str, UserQuestionAnswer]
