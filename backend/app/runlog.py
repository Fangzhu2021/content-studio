"""运行台账公共工具：删除项目时保留统计、清空内容预览；模板变更留版本快照。"""
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import NodeTemplate, PromptTemplate, RunLog, TemplateVersion


async def clear_project_previews(db: AsyncSession, project_id: str, project_name: str = "") -> None:
    """项目被删除：台账保留（谁/何时/哪个节点/耗时/成败），但清空输入输出预览与参数快照。

    不删除行，因此"模板使用量、人均调用、成功率"等统计仍然连续。
    """
    values = {"input_preview": "", "output_preview": "", "params": {},
              "project_id": None, "input_revision_id": None, "output_revision_id": None}
    if project_name:
        values["project_name"] = project_name
    await db.execute(update(RunLog).where(RunLog.project_id == project_id).values(**values))


async def clear_user_previews(db: AsyncSession, user_id: str, username: str = "") -> None:
    """用户被删除：同上，保留统计口径，清空内容预览。"""
    values = {"input_preview": "", "output_preview": "", "params": {}}
    if username:
        values["username"] = username
    await db.execute(update(RunLog).where(RunLog.user_id == user_id).values(**values))


def node_template_snapshot(t: NodeTemplate) -> dict:
    return {"group": t.group, "kind": t.kind, "subtype": t.subtype, "label": t.label,
            "icon": t.icon, "color": t.color, "hint": t.hint, "sort": t.sort,
            "enabled": bool(t.enabled), "default_config": t.default_config or {},
            "prompt_len": len(t.prompt or "")}


def prompt_template_snapshot(t: PromptTemplate) -> dict:
    return {"key": t.key, "name": t.name, "content_len": len(t.content or ""),
            "content_md5": __import__("hashlib").md5((t.content or "").encode("utf-8")).hexdigest(),
            "enabled": bool(t.enabled), "scope": t.scope}


async def save_template_version(db: AsyncSession, *, template_type: str, template_id: str, version: int,
                                snapshot: dict, changed_by: str = "", note: str = "") -> TemplateVersion:
    row = TemplateVersion(template_type=template_type, template_id=template_id, version=int(version),
                          snapshot=snapshot or {}, changed_by=changed_by, note=(note or "")[:200])
    db.add(row)
    return row
