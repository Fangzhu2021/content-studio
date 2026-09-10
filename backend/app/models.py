"""ORM 模型：User / Project / CanvasNode / CanvasEdge / Revision"""
import uuid
from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        String, Text, func)
from sqlalchemy.dialects.postgresql import JSONB

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"
    id = Column(String(32), primary_key=True, default=new_id)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(300), nullable=False)
    # ===== P0 多用户升级新增（全部有默认值，兼容既有数据）=====
    role = Column(String(20), default="editor", index=True)   # admin/manager/editor/reviewer/viewer
    is_active = Column(Boolean, default=True)
    created_by = Column(String(32), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    token_version = Column(Integer, default=1)                 # +1 即强制下线
    monthly_call_limit = Column(Integer, nullable=True)        # 空=继承全局默认
    monthly_char_limit = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"
    id = Column(String(32), primary_key=True, default=new_id)
    name = Column(String(200), nullable=False)
    owner_id = Column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


NODE_TYPES = ("draft_input", "rewriter", "reviewer", "ai_reviewer", "transformer", "tool", "exporter")


class CanvasNode(Base):
    __tablename__ = "canvas_nodes"
    id = Column(String(32), primary_key=True, default=new_id)
    project_id = Column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(30), nullable=False)          # NODE_TYPES
    subtype = Column(String(50), default="")           # tv_script/newspaper/wechat/weibo/douyin/xiaohongshu/toutiao
    label = Column(String(120), default="")
    position_x = Column(Float, default=0.0)
    position_y = Column(Float, default=0.0)
    config = Column(JSONB, default=dict)
    status = Column(String(20), default="idle")        # idle/running/done/failed/approved
    error = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CanvasEdge(Base):
    __tablename__ = "canvas_edges"
    id = Column(String(32), primary_key=True, default=new_id)
    project_id = Column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_node_id = Column(String(32), ForeignKey("canvas_nodes.id", ondelete="CASCADE"), nullable=False)
    target_node_id = Column(String(32), ForeignKey("canvas_nodes.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Revision(Base):
    __tablename__ = "revisions"
    id = Column(String(32), primary_key=True, default=new_id)
    project_id = Column(String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(String(32), ForeignKey("canvas_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_revision_id = Column(String(32), nullable=True)   # 追溯链
    title = Column(String(500), default="")
    content = Column(Text, default="")
    format_type = Column(String(50), default="")             # draft/tv_script/...
    status = Column(String(20), default="draft")             # draft/rewritten/reviewed/approved/finalized
    model = Column(String(50), default="")                   # deepseek-chat / mock
    review_comment = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Invite(Base):
    """邀请码：注册关闭后凭码注册"""
    __tablename__ = "invites"
    id = Column(String(32), primary_key=True, default=new_id)
    code = Column(String(32), unique=True, nullable=False, index=True)
    role = Column(String(20), default="editor")
    note = Column(String(200), default="")
    created_by = Column(String(32), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    used_by = Column(String(32), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """关键操作留痕"""
    __tablename__ = "audit_logs"
    id = Column(String(32), primary_key=True, default=new_id)
    user_id = Column(String(32), nullable=True, index=True)
    username = Column(String(50), default="")
    action = Column(String(60), nullable=False, index=True)
    target_type = Column(String(30), default="")
    target_id = Column(String(32), default="")
    detail = Column(JSONB, default=dict)
    ip = Column(String(64), default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AiUsage(Base):
    """AI 调用计量（用量与成本）"""
    __tablename__ = "ai_usage"
    id = Column(String(32), primary_key=True, default=new_id)
    user_id = Column(String(32), nullable=True, index=True)
    project_id = Column(String(32), nullable=True)
    node_id = Column(String(32), nullable=True)
    kind = Column(String(30), default="")       # rewrite/transform/ai_review/condense/style_prompt
    model = Column(String(50), default="")
    prompt_chars = Column(Integer, default=0)
    output_chars = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cost_est = Column(Float, default=0.0)
    duration_ms = Column(Integer, default=0)
    ok = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    """全局设置（键值对）"""
    __tablename__ = "app_settings"
    key = Column(String(50), primary_key=True)
    value = Column(JSONB, default=dict)
