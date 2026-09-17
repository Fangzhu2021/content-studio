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
    template_key = Column(String(40), default="")   # 建项目时使用的模板：standard_v1 / ai_review_v1 / blank / custom:xxx
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
    audio_seconds = Column(Integer, default=0)   # 语音识别：音频时长（秒）
    ok = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    """全局设置（键值对）"""
    __tablename__ = "app_settings"
    key = Column(String(50), primary_key=True)
    value = Column(JSONB, default=dict)


class NodeTemplate(Base):
    """节点库（数据化）：group/kind/subtype 决定节点形态，prompt 为该节点的默认提示词"""
    __tablename__ = "node_templates"
    id = Column(String(32), primary_key=True, default=new_id)
    group = Column(String(30), default="")            # 输入/工具/AI 改写/审稿/新媒体转换/成稿导出
    kind = Column(String(30), nullable=False)         # draft_input/rewriter/.../tool/exporter
    subtype = Column(String(50), default="")
    label = Column(String(120), default="")
    icon = Column(String(16), default="")
    color = Column(String(16), default="#64748b")
    hint = Column(String(120), default="")
    sort = Column(Integer, default=100)
    default_config = Column(JSONB, default=dict)
    prompt = Column(Text, default="")
    scope = Column(String(10), default="global")      # global | user
    owner_id = Column(String(32), nullable=True)
    enabled = Column(Boolean, default=True)
    version = Column(Integer, default=1)      # 每次管理员修改 +1，用于运行台账精确溯源
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PromptTemplate(Base):
    """提示词模板：scope=global 由管理员维护，scope=user 为用户个人模板"""
    __tablename__ = "prompt_templates"
    id = Column(String(32), primary_key=True, default=new_id)
    key = Column(String(50), nullable=False, index=True)   # tv_script/newspaper/wechat/.../ai_review/condense
    name = Column(String(120), default="")
    content = Column(Text, default="")
    scope = Column(String(10), default="global")
    owner_id = Column(String(32), nullable=True)
    enabled = Column(Boolean, default=True)
    version = Column(Integer, default=1)      # 每次修改 +1
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RunLog(Base):
    """运行台账：一次节点执行一行，串起 谁/哪个项目/用了哪个模板/输入什么/产出什么"""
    __tablename__ = "run_logs"
    id = Column(String(32), primary_key=True, default=new_id)
    # 谁 / 哪个项目（冗余名称：项目删除后统计仍可查）
    user_id = Column(String(32), nullable=True, index=True)
    username = Column(String(50), default="")
    project_id = Column(String(32), nullable=True, index=True)
    project_name = Column(String(200), default="")
    # 节点
    node_id = Column(String(32), nullable=True)
    node_type = Column(String(30), default="")
    node_subtype = Column(String(50), default="")
    node_label = Column(String(120), default="")
    # 触发与结果
    trigger = Column(String(10), default="manual")   # manual / auto / retry
    status = Column(String(12), default="ok")        # ok / failed / blocked / busy
    error = Column(Text, default="")
    # 输入（只存预览，全文在 revisions）
    input_revision_id = Column(String(32), nullable=True)
    input_chars = Column(Integer, default=0)
    input_preview = Column(Text, default="")
    # 本次生效参数快照
    params = Column(JSONB, default=dict)
    # 产出
    output_revision_id = Column(String(32), nullable=True)
    output_chars = Column(Integer, default=0)
    output_preview = Column(Text, default="")
    # 用量
    model = Column(String(50), default="")
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cost_est = Column(Float, default=0.0)
    duration_ms = Column(Integer, default=0)
    retries = Column(Integer, default=0)
    queued_ms = Column(Integer, default=0)
    # 模板溯源
    template_key = Column(String(40), default="")
    node_template_id = Column(String(32), nullable=True)
    node_template_version = Column(Integer, default=0)
    prompt_source = Column(String(16), default="")     # node / global / builtin / none
    prompt_hash = Column(String(16), default="")
    prompt_template_id = Column(String(32), nullable=True)
    prompt_template_version = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class TemplateVersion(Base):
    """模板版本快照：每次修改节点库/提示词模板追加一条，便于回看当时原文"""
    __tablename__ = "template_versions"
    id = Column(String(32), primary_key=True, default=new_id)
    template_type = Column(String(10), default="")    # node / prompt
    template_id = Column(String(32), nullable=False, index=True)
    version = Column(Integer, default=1)
    snapshot = Column(JSONB, default=dict)
    changed_by = Column(String(50), default="")
    note = Column(String(200), default="")             # 新建 / 编辑 / 回滚
    created_at = Column(DateTime(timezone=True), server_default=func.now())
