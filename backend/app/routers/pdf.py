"""PDF 版面提取：上传 PDF → 按版块解析 → 选用版块生成稿件（供下游节点使用）"""
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import log as audit_log
from ..db import get_db
from ..deps import get_current_user
from ..models import CanvasNode, Revision, User
from ..paths import UPLOAD_ROOT
from ..pdf_tools import extract_blocks, merge_blocks
from ..schemas import PdfSelectIn

router = APIRouter()

MAX_MB = 40
PDF_KIND = "pdf_extract"


def _node_uploads_dir(node: CanvasNode) -> Path:
    d = UPLOAD_ROOT / node.project_id / node.id
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _owned_pdf_node(db: AsyncSession, nid: str, user: User) -> CanvasNode:
    node = await db.get(CanvasNode, nid)
    if not node:
        raise HTTPException(404, "节点不存在")
    from ..models import Project
    project = await db.get(Project, node.project_id)
    if not project or project.owner_id != user.id:
        raise HTTPException(404, "项目不存在")
    if not (node.type == "tool" and node.subtype == PDF_KIND):
        raise HTTPException(400, "该节点不是 PDF 版面提取节点")
    return node


def _blocks_brief(blocks: list[dict]) -> list[dict]:
    out = []
    for b in blocks:
        out.append({
            "index": b["index"], "page": b["page"], "title": b.get("title", ""),
            "chars": b["chars"], "column": b["column"], "y": b["y"],
            "preview": re.sub(r"\s+", " ", b["text"])[:120],
        })
    return out


@router.post("/nodes/{nid}/pdf")
async def upload_pdf(nid: str, file: UploadFile = File(...),
                     user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    node = await _owned_pdf_node(db, nid, user)
    name = (file.filename or "upload.pdf")
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "只支持 PDF 文件")
    safe = re.sub(r"[^\w\u4e00-\u9fa5.\-]", "_", name)[:120]
    dest = _node_uploads_dir(node) / safe
    size = 0
    with dest.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_MB * 1024 * 1024:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(400, f"文件过大（上限 {MAX_MB}MB）")
            f.write(chunk)

    try:
        result = extract_blocks(dest)
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"PDF 解析失败：{exc}")

    if result["total_chars"] < 50:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "未从该 PDF 识别到文字（可能是扫描图片版）。需要 OCR 才能提取，请联系管理员。")

    cfg = dict(node.config or {})
    cfg["pdf"] = {
        "filename": safe, "size": size, "pages": result["pages"],
        "total_chars": result["total_chars"], "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "blocks": result["blocks"], "selected": [],
    }
    node.config = cfg
    await db.commit()
    await audit_log(db, action="pdf_upload", user=user, target_type="node", target_id=nid,
                    detail={"file": safe, "pages": result["pages"], "blocks": len(result["blocks"])})
    return {"filename": safe, "size": size, "pages": result["pages"],
            "total_chars": result["total_chars"], "blocks": _blocks_brief(result["blocks"])}


@router.get("/nodes/{nid}/pdf")
async def pdf_status(nid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    node = await _owned_pdf_node(db, nid, user)
    info = (node.config or {}).get("pdf")
    if not info:
        return {"uploaded": False}
    return {"uploaded": True, "filename": info.get("filename"), "size": info.get("size"),
            "pages": info.get("pages"), "total_chars": info.get("total_chars"),
            "selected": info.get("selected", []), "blocks": _blocks_brief(info.get("blocks", []))}


@router.post("/nodes/{nid}/pdf/select")
async def select_blocks(nid: str, body: PdfSelectIn,
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    node = await _owned_pdf_node(db, nid, user)
    info = (node.config or {}).get("pdf")
    if not info or not info.get("blocks"):
        raise HTTPException(400, "请先上传 PDF 文件")
    blocks = info["blocks"]
    valid = {b["index"] for b in blocks}
    indexes = [i for i in (body.indexes or []) if i in valid]
    if not indexes:
        raise HTTPException(400, "请至少选择一个版块")

    title, content = merge_blocks(blocks, indexes)
    latest = (await db.execute(
        select(Revision).where(Revision.node_id == nid).order_by(Revision.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if latest and latest.status == "draft":
        latest.title, latest.content, latest.format_type = title, content, "pdf_extract"
        rev = latest
    else:
        rev = Revision(project_id=node.project_id, node_id=nid, title=title, content=content,
                       format_type="pdf_extract", status="draft")
        db.add(rev)

    cfg = dict(node.config or {})
    cfg["pdf"] = {**info, "selected": indexes}
    node.config = cfg
    await db.commit()
    await db.refresh(rev)
    await audit_log(db, action="pdf_select", user=user, target_type="node", target_id=nid,
                    detail={"blocks": indexes, "chars": len(content)})
    return {"revision_id": rev.id, "title": title, "chars": len(content), "selected": indexes,
            "content": content}


@router.delete("/nodes/{nid}/pdf")
async def remove_pdf(nid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    node = await _owned_pdf_node(db, nid, user)
    cfg = dict(node.config or {})
    cfg.pop("pdf", None)
    node.config = cfg
    await db.commit()
    shutil.rmtree(_node_uploads_dir(node), ignore_errors=True)
    await audit_log(db, action="pdf_remove", user=user, target_type="node", target_id=nid)
    return {"ok": True}
