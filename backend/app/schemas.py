"""Pydantic 请求/响应模型"""
from typing import Optional

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=100)


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str

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


class ReviewIn(BaseModel):
    status: str                          # approved / draft(打回)
    comment: str = ""
