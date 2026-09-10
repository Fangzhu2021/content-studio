"""ORM 模型：User / Project / CanvasNode / CanvasEdge / Revision"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"
    id = Column(String(32), primary_key=True, default=new_id)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(300), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"
    id = Column(String(32), primary_key=True, default=new_id)
    name = Column(String(200), nullable=False)
    owner_id = Column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


NODE_TYPES = ("draft_input", "rewriter", "reviewer", "ai_reviewer", "transformer", "exporter")


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
