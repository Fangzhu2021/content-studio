"""PDF 版面解析：按版块（文章）提取稿件内容

流程：
1) PyMuPDF 取每个文本块的字号、坐标与文字；
2) 合并「同栏 + 同字号 + 纵向相邻」的块（PDF 常把一行的标题/一段正文拆成多个块）；
3) 以**按字数加权**的众数字号作为正文字号（比取中位数更稳，避免标题多时被带偏）；
   字号明显大于正文且较短的块判为标题；
4) 按 页 → 栏 → 纵坐标 排序，标题块与其后同栏正文块合并成一篇稿件；
5) 还原 PDF 取词造成的断字与断行。

扫描图片版 PDF 取不到文字，会明确提示需要 OCR。
"""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf  # PyMuPDF

MIN_BLOCK_CHARS = 6          # 过短的块视为噪声（页码、栏头）
TITLE_HARD_MAX = 60          # 标题块字符上限
TITLE_SIZE_RATIO = 1.12      # 标题字号 ≥ 正文字号的倍数


def _clean(text: str) -> str:
    t = text.replace("\u3000", " ").replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", t)          # 中文之间不留空格
    # 行内换行续接：上一行以中文/数字/标点结尾，下一行以中文/数字/标点开头时并入同一行
    t = re.sub(r"(?<=[\u4e00-\u9fff0-9，、；：。！？）】”])\n(?=[\u4e00-\u9fff0-9，、；：。！？、（【“‘])", "", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


def _raw_blocks(page) -> list[dict]:
    out = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        lines, sizes = [], []
        for line in blk.get("lines", []):
            line_text = "".join(span.get("text", "") for span in line.get("spans", []))
            if line_text.strip():
                lines.append(line_text)
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    sizes.append(round(span.get("size", 0), 1))
        text = _clean("\n".join(lines))   # 每个块都要清洗：还原断字与行内换行
        if not text:
            continue
        x0, y0, x1, y1 = blk["bbox"]
        out.append({"text": text, "size": max(sizes) if sizes else 0.0,
                    "x": x0, "y": y0, "x1": x1, "y1": y1})
    return out


def _column_of(b: dict, width: float) -> int:
    ratio = ((b["x"] + b["x1"]) / 2) / (width or 595)
    return 0 if ratio < 0.38 else (1 if ratio < 0.66 else 2)


def _merge_adjacent(blocks: list[dict]) -> list[dict]:
    """合并同栏、同字号、纵向相邻的块（标题换行、段落被拆块等）"""
    if not blocks:
        return []
    blocks = sorted(blocks, key=lambda b: (b["column"], b["y"], b["x"]))
    merged: list[dict] = []
    for b in blocks:
        if merged:
            last = merged[-1]
            gap = b["y"] - last["y1"]
            same_size = abs((b["size"] or 0) - (last["size"] or 0)) < 0.6
            limit = max(2.2 * (last["size"] or 10), 14)
            if last["column"] == b["column"] and same_size and -2 <= gap <= limit:
                last["text"] = _clean(last["text"] + "\n" + b["text"])
                last["y1"] = max(last["y1"], b["y1"])
                last["x1"] = max(last["x1"], b["x1"])
                continue
        merged.append(dict(b))
    for b in merged:
        b["chars"] = len(re.sub(r"\s", "", b["text"]))
    return [b for b in merged if b["chars"] >= MIN_BLOCK_CHARS]


def _body_size(blocks: list[dict]) -> float:
    """按字数加权的众数字号 = 正文字号（标题通常字数少，不会占优）"""
    weight: dict[float, int] = {}
    for b in blocks:
        key = round(b["size"], 1)
        weight[key] = weight.get(key, 0) + b["chars"]
    if not weight:
        return 0.0
    return max(weight.items(), key=lambda kv: kv[1])[0]


def extract_blocks(path: str | Path) -> dict:
    """返回 {pages, total_chars, blocks:[{index,page,title,text,chars,column,y}]}"""
    doc = pymupdf.open(str(path))
    try:
        articles: list[dict] = []
        for pno in range(doc.page_count):
            page = doc[pno]
            width = page.rect.width or 595
            raw = _raw_blocks(page)
            for b in raw:
                b["column"] = _column_of(b, width)
            blocks = _merge_adjacent(raw)
            body_size = _body_size(blocks)

            for b in blocks:
                b["is_title"] = (
                    body_size > 0
                    and b["size"] >= body_size * TITLE_SIZE_RATIO
                    and b["chars"] <= TITLE_HARD_MAX
                )
            blocks.sort(key=lambda b: (b["column"], b["y"]))

            current: dict | None = None
            for b in blocks:
                same_col = current is not None and current["column"] == b["column"]
                if b["is_title"]:
                    current = {"page": pno + 1, "column": b["column"], "title": b["text"],
                               "body": [], "y": b["y"]}
                    articles.append(current)
                elif same_col:
                    current["body"].append(b["text"])
                else:
                    current = {"page": pno + 1, "column": b["column"], "title": "",
                               "body": [b["text"]], "y": b["y"]}
                    articles.append(current)

        result = []
        for a in articles:
            body = "\n".join(t for t in a["body"] if t)
            text = (a["title"] + "\n" + body).strip() if a["title"] else body.strip()
            if len(re.sub(r"\s", "", text)) < MIN_BLOCK_CHARS:
                continue
            result.append({
                "index": len(result), "page": a["page"], "column": a["column"],
                "title": a["title"], "text": text,
                "chars": len(re.sub(r"\s", "", text)), "y": a["y"],
            })
        total = sum(b["chars"] for b in result)
        return {"pages": doc.page_count, "total_chars": total, "blocks": result}
    finally:
        doc.close()


def merge_blocks(blocks: list[dict], indexes: list[int]) -> tuple[str, str]:
    """把选中的版块合并成稿件文本；返回 (标题, 正文)"""
    picked = [b for b in blocks if b["index"] in set(indexes)]
    if not picked:
        return "", ""
    parts, title = [], ""
    for b in picked:
        if not title and b.get("title"):
            title = b["title"]
        head = f"【第{b['page']}版 · 版块{b['index'] + 1}"
        if b.get("title"):
            head += f"：{b['title']}"
        head += "】"
        parts.append(f"{head}\n{b['text'].strip()}")
    return title, "\n\n".join(parts)
