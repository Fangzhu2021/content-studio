"""节点库与提示词模板：读取（所有登录用户）+ 我的个人模板"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import log as audit_log
from ..db import get_db
from ..deps import get_current_user
from ..models import PromptTemplate, User
from ..schemas import MyPromptIn
from ..templates import effective_nodes, effective_prompts

router = APIRouter()


@router.get("/templates")
async def get_templates(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """前端节点库与提示词默认值：内置定义作兜底，数据库配置优先"""
    return {
        "nodes": await effective_nodes(db, user),
        "prompts": await effective_prompts(db, user),
    }


def _mine_out(t: PromptTemplate) -> dict:
    return {"id": t.id, "key": t.key, "name": t.name, "content": t.content, "enabled": bool(t.enabled),
            "updated_at": t.updated_at.isoformat() if t.updated_at else None}


@router.get("/my/prompt-templates")
async def my_prompts(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(PromptTemplate).where(PromptTemplate.scope == "user", PromptTemplate.owner_id == user.id)
        .order_by(PromptTemplate.updated_at.desc())
    )).scalars().all()
    return [_mine_out(t) for t in rows]


@router.post("/my/prompt-templates")
async def create_my_prompt(body: MyPromptIn, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    if not body.content.strip():
        raise HTTPException(400, "提示词内容不能为空")
    t = PromptTemplate(key=body.key or "custom", name=body.name or "我的模板", content=body.content,
                       scope="user", owner_id=user.id, enabled=True)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    await audit_log(db, action="my_prompt_create", user=user, target_type="prompt_template", target_id=t.id,
                    detail={"key": t.key, "name": t.name})
    return _mine_out(t)


@router.delete("/my/prompt-templates/{tid}")
async def delete_my_prompt(tid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    t = await db.get(PromptTemplate, tid)
    if not t or t.scope != "user" or t.owner_id != user.id:
        raise HTTPException(404, "模板不存在")
    await db.execute(delete(PromptTemplate).where(PromptTemplate.id == tid))
    await db.commit()
    await audit_log(db, action="my_prompt_delete", user=user, target_type="prompt_template", target_id=tid)
    return {"ok": True}
