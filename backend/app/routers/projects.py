"""项目 CRUD + 工作流模板一键创建"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..models import CanvasEdge, CanvasNode, Project, Revision, User
from ..ai import FORMAT_LABELS  # noqa: F401  预留
from ..schemas import ProjectCreate, ProjectUpdate

router = APIRouter()


def _node_out(n: CanvasNode) -> dict:
    return {
        "id": n.id, "type": n.type, "subtype": n.subtype, "label": n.label,
        "position": {"x": n.position_x or 0, "y": n.position_y or 0},
        "config": n.config or {}, "status": n.status or "idle", "error": n.error or "",
    }


def _edge_out(e: CanvasEdge) -> dict:
    return {"id": e.id, "source": e.source_node_id, "target": e.target_node_id}


async def _get_owned_project(db: AsyncSession, pid: str, user: User) -> Project:
    project = await db.get(Project, pid)
    if not project or project.owner_id != user.id:
        raise HTTPException(404, "项目不存在")
    return project


# 典型工作流模板：草稿 → TV/报刊改写 → 审定 → 公众号/微博/抖音 → 成稿
_TEMPLATE = [
    ("draft_input", "", "草稿输入", 80, 400, {}),
    ("rewriter", "tv_script", "TV稿改写", 360, 180, {}),
    ("rewriter", "newspaper", "报刊稿改写", 360, 600, {}),
    ("reviewer", "", "人工审定", 680, 390, {}),
    ("transformer", "wechat", "公众号", 990, 120, {}),
    ("transformer", "weibo", "微博", 990, 320, {}),
    ("transformer", "douyin", "抖音", 990, 520, {}),
    ("exporter", "wechat", "公众号成稿", 1270, 120, {}),
    ("exporter", "weibo", "微博成稿", 1270, 320, {}),
    ("exporter", "douyin", "抖音成稿", 1270, 520, {}),
]
_TEMPLATE_EDGES = [
    (0, 1), (0, 2), (1, 3), (2, 3),
    (3, 4), (3, 5), (3, 6),
    (4, 7), (5, 8), (6, 9),
]


async def build_template(db: AsyncSession, project: Project,
                         ai_review: bool = False) -> tuple[list[CanvasNode], list[CanvasEdge]]:
    nodes: list[CanvasNode] = []
    for ntype, subtype, label, x, y, cfg in _TEMPLATE:
        if ai_review and ntype == "reviewer":
            ntype, label = "ai_reviewer", "AI 审稿"
        nodes.append(CanvasNode(project_id=project.id, type=ntype, subtype=subtype,
                                label=label, position_x=x, position_y=y, config=cfg))
    db.add_all(nodes)
    await db.flush()
    edges = []
    for s, t in _TEMPLATE_EDGES:
        edges.append(CanvasEdge(project_id=project.id, source_node_id=nodes[s].id, target_node_id=nodes[t].id))
    db.add_all(edges)
    return nodes, edges


@router.get("/projects")
async def list_projects(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(Project).where(Project.owner_id == user.id).order_by(Project.updated_at.desc())
    )
    return [
        {"id": p.id, "name": p.name, "created_at": p.created_at.isoformat() if p.created_at else None}
        for p in rows.scalars()
    ]


@router.post("/projects")
async def create_project(body: ProjectCreate, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    project = Project(name=body.name, owner_id=user.id)
    db.add(project)
    await db.flush()
    if body.template:
        await build_template(db, project, ai_review=body.ai_review)
    await db.commit()
    return {"id": project.id, "name": project.name, "template": body.template, "ai_review": body.ai_review}


@router.get("/projects/{pid}")
async def project_detail(pid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    project = await _get_owned_project(db, pid, user)
    nodes = (await db.execute(select(CanvasNode).where(CanvasNode.project_id == pid))).scalars().all()
    edges = (await db.execute(select(CanvasEdge).where(CanvasEdge.project_id == pid))).scalars().all()
    return {
        "id": project.id, "name": project.name,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "nodes": [_node_out(n) for n in nodes],
        "edges": [_edge_out(e) for e in edges],
    }


@router.put("/projects/{pid}")
async def update_project(pid: str, body: ProjectUpdate, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    project = await _get_owned_project(db, pid, user)
    if body.name:
        project.name = body.name
    await db.commit()
    return {"ok": True, "name": project.name}


@router.delete("/projects/{pid}")
async def delete_project(pid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_owned_project(db, pid, user)
    await db.execute(delete(Revision).where(Revision.project_id == pid))
    await db.execute(delete(CanvasEdge).where(CanvasEdge.project_id == pid))
    await db.execute(delete(CanvasNode).where(CanvasNode.project_id == pid))
    await db.execute(delete(Project).where(Project.id == pid))
    await db.commit()
    return {"ok": True}
