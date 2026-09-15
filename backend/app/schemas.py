"""Pydantic 请求/响应模型"""
from typing import Optional

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=8, max_length=100)
    invite_code: str = ""          # 注册关闭时必填


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=100)


class InviteCreate(BaseModel):
    role: str = "editor"
    expires_days: int = 7
    note: str = ""


class UserOut(BaseModel):
    id: str
    username: str
    role: str = "editor"

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    token: str
    user: UserOut


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    template: bool = False
    ai_review: bool = False    # True: 模板中的「人工审定」替换为「AI 审稿」


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)


class NodePosition(BaseModel):
    x: float
    y: float


class NodeCreate(BaseModel):
    type: str
    subtype: str = ""
    label: str = ""
    position: NodePosition
    config: dict = {}


class NodeUpdate(BaseModel):
    position: Optional[NodePosition] = None
    config: Optional[dict] = None
    label: Optional[str] = None


class EdgeCreate(BaseModel):
    source: str
    target: str


class ContentIn(BaseModel):
    title: str = ""
    content: str = ""


class ExecuteIn(BaseModel):
    revision_id: Optional[str] = None    # 指定输入 Revision（transform/exporter 选稿）
    action: Optional[str] = None         # reviewer: approve/reject
    comment: Optional[str] = None        # 审定意见
    trigger: Optional[str] = None        # 台账口径: manual(手动) / auto(一键执行) / retry(重试)


class ReviewIn(BaseModel):
    status: str                          # approved / draft(打回)
    comment: str = ""


class AdminUserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    monthly_call_limit: Optional[int] = None


class AdminPasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=100)


class AdminProjectTransfer(BaseModel):
    owner_username: str


class AdminSettingsIn(BaseModel):
    registration_open: Optional[bool] = None
    default_monthly_call_limit: Optional[int] = None
    global_monthly_budget_yuan: Optional[float] = None
    max_concurrency_global: Optional[int] = None
    max_concurrency_user: Optional[int] = None
    max_queue_wait_seconds: Optional[int] = None
    # ---- AI 服务（系统设置里可改，保存即生效）----
    ai_api_key: Optional[str] = None        # 空串/null = 清除并回落 backend/.env
    ai_base_url: Optional[str] = None       # OpenAI 兼容地址，留空 = 用默认
    ai_default_model: Optional[str] = None  # 全站默认档位：standard / reasoner


class AiTestIn(BaseModel):
    model: Optional[str] = None             # 不传则用当前默认档位


class NodeTemplateIn(BaseModel):
    group: str = ""
    kind: str
    subtype: str = ""
    label: str = ""
    icon: str = ""
    color: str = "#64748b"
    hint: str = ""
    sort: int = 100
    default_config: dict = {}
    prompt: str = ""


class NodeTemplateUpdate(BaseModel):
    group: Optional[str] = None
    label: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    hint: Optional[str] = None
    sort: Optional[int] = None
    default_config: Optional[dict] = None
    prompt: Optional[str] = None
    enabled: Optional[bool] = None


class PromptTemplateIn(BaseModel):
    key: str
    name: str = ""
    content: str


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    enabled: Optional[bool] = None


class MyPromptIn(BaseModel):
    key: str
    name: str = ""
    content: str


class PdfSelectIn(BaseModel):
    indexes: list[int] = []
