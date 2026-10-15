# -*- coding: utf-8 -*-
"""检索：查询构造、FTS5 命中、排序与片段高亮。

排序全部下沉到 SQL —— 旧版先用 bm25 取 3N 条、再在 Python 里按"bm25 + 新近加权"重排，
会让真正最相关的那条（bm25 排在第 3N+1 位、但加权后该排第一）**永远不出现**。
两个排序键不一致属于正确性问题，不是性能问题。
"""
from __future__ import annotations

import os
import re
import sqlite3

from .textutil import (
    MARK_L, MARK_R, build_phrase_expr, build_query_expr, from_index_text,
)

# 新近加权：30 天半衰期，最大 +1.2。表达成 SQL 才能与 bm25 一起排序。
# bm25 是负数、越小越好，所以减去 bonus（bonus 越大 → 值越负 → 排越前）。
_RECENCY = (
    "COALESCE(1.2 / (1.0 + MAX(0.0, julianday('now')"
    " - julianday(f.mtime, 'unixepoch')) / 30.0), 0.0)"
)

_BM25 = "bm25(docs, 0.0, 4.0, 1.0)"
_SORT_KEY = _BM25 + " - " + _RECENCY

# 坑：别名绝不能叫 rank —— FTS5 表有一个隐藏列就叫 rank（未加权的 bm25），
# `ORDER BY rank` 会被它抢先解析，结果文件名权重 ×4 在排序里完全失效。
# 所以别名用 match_rank，并且 ORDER BY 直接重复表达式，双保险。
BASE_SQL = (
    "SELECT f.path AS path, f.name AS name, f.dir AS dir, f.ext AS ext,"
    " f.size AS size, f.mtime AS mtime, f.status AS status,"
    " " + _BM25 + " AS match_rank,"
    " (" + _SORT_KEY + ") AS sort_key,"
    " snippet(docs, 2, ?, ?, ?, 48) AS snip,"
    " highlight(docs, 1, ?, ?) AS name_hl"
    " FROM docs JOIN files f ON f.path = docs.path"
    " WHERE docs MATCH ?"
    " ORDER BY " + _SORT_KEY + " LIMIT ?"
)

def _normalize_roots(roots):
    """把范围根路径归一化成 files.root 列里存的样子（realpath + 小写）。"""
    out = []
    for root in roots or []:
        try:
            out.append(os.path.normcase(os.path.realpath(root)))
        except OSError:
            continue
    return out


def _normalize_exts(ext_filter):
    """后缀筛选值规范化：小写、补前导点；空串表示“无扩展名”。"""
    out = []
    for ext in ext_filter or []:
        ext = (ext or "").strip().lower()
        if ext and not ext.startswith("."):
            ext = "." + ext
        out.append(ext)
    return out


def _name_only_expr(expr):
    """只检索文件名：给 FTS 表达式套上 name 列过滤。"""
    return "name : (%s)" % expr


def _compact(text):
    return re.sub(r"\s+", "", (text or "")).lower()


def _fetch_limit(limit):
    """先多取一些再分组裁剪，避免文件名段把内容段挤没。"""
    return max(limit, min(limit * 2, 500))


def _finalize_results(results, query, limit):
    """分成「文件名命中」与「内容命中」两段，裁剪到 limit 条。

    门槛：用户输入整体（去空白）作为子串出现在文件名里，才算文件名命中；
    文件名只沾零散字符的不进文件名段，且排在内容命中之后。
    """
    q = _compact(query)
    name_group = []
    content_body = []
    content_name = []
    for result in results:
        name_whole = bool(q) and q in _compact(result["name"])
        body_hit = result["match"] in ("body", "both")
        name_hit = result["match"] in ("name", "both")
        result["content_also"] = False
        if name_whole:
            result["group"] = "name"
            result["content_also"] = body_hit
            name_group.append(result)
        elif body_hit:
            result["group"] = "content"
            result["content_kind"] = "body"
            content_body.append(result)
        elif name_hit:
            result["group"] = "content"
            result["content_kind"] = "name"
            content_name.append(result)
        else:
            result["group"] = "content"
            result["content_kind"] = "other"
            content_body.append(result)
    return (name_group + content_body + content_name)[:limit]


def _run(conn, expr, limit, roots=None, ext_filter=None, name_only=False):
    """执行一条 FTS 查询。

    roots=None 表示不按范围过滤（测试/内部用）；roots 为空列表表示范围为空，返回空结果。
    name_only=True 时只匹配 name 列（content 关闭），片段用文件名替代。
    """
    if name_only:
        expr = _name_only_expr(expr)
    params = [MARK_L, MARK_R, "\u2026", MARK_L, MARK_R, expr]
    if roots is None:
        where = " WHERE docs MATCH ?"
    else:
        roots = _normalize_roots(roots)
        if not roots:
            return []
        where = " WHERE docs MATCH ? AND f.root IN (%s)" % ", ".join("?" * len(roots))
        params.extend(roots)
    exts = _normalize_exts(ext_filter)
    if exts:
        where += " AND f.ext IN (%s)" % ", ".join("?" * len(exts))
        params.extend(exts)
    params.append(limit)
    sql = BASE_SQL.replace(" WHERE docs MATCH ?", where)
    rows = conn.execute(sql, tuple(params)).fetchall()
    results = []
    for row in rows:
        name_hl = row["name_hl"] or ""
        snip_raw = row["snip"] or ""
        name_hit = MARK_L in name_hl
        body_hit = MARK_L in snip_raw
        if name_hit and body_hit:
            where = "both"
        elif name_hit:
            where = "name"
        else:
            where = "body"
        results.append({
            "path": row["path"],
            "name": row["name"],
            "dir": row["dir"],
            "ext": row["ext"],
            "size": row["size"],
            "mtime": row["mtime"],
            "status": row["status"],
            "rank": row["match_rank"],
            "sort_key": row["sort_key"],
            "match": where,
            "snippet": row["name"] if name_only else from_index_text(snip_raw),
        })
    return results


def search_with_mode(conn, query, limit=60, roots=None, match="all",
                     content=True, ext_filter=None):
    """返回 (结果列表, 命中模式)。

    match: all=AND(空结果回退 OR) / any=OR / phrase=整段短语。
    content=False 时只检索文件名（FTS 列过滤），片段改用文件名。
    """
    text = (query or "").strip()
    if not text:
        return [], ""

    if match == "any":
        expr = build_query_expr(text, "OR")
    elif match == "phrase":
        expr = build_phrase_expr(text)
    else:
        expr = build_query_expr(text, "AND")
    if not expr:
        return [], ""
    name_only = not content
    fetch = _fetch_limit(limit)

    if match == "any":
        try:
            results = _run(conn, expr, fetch, roots, ext_filter, name_only)
            return _finalize_results(results, text, limit), "OR"
        except sqlite3.OperationalError:
            return [], "OR"
    if match == "phrase":
        try:
            results = _run(conn, expr, fetch, roots, ext_filter, name_only)
            return _finalize_results(results, text, limit), "PHRASE"
        except sqlite3.OperationalError:
            return [], "PHRASE"

    # match == "all"：先 AND，一个都没命中时回退 OR（范围/后缀/内容过滤都保留）。
    try:
        results = _run(conn, expr, fetch, roots, ext_filter, name_only)
    except sqlite3.OperationalError:
        results = []
    if results:
        return _finalize_results(results, text, limit), "AND"

    expr_or = build_query_expr(text, "OR")
    if expr_or and expr_or != expr:
        try:
            results = _run(conn, expr_or, fetch, roots, ext_filter, name_only)
        except sqlite3.OperationalError:
            results = []
        if results:
            return _finalize_results(results, text, limit), "OR"
    return [], "AND"


def search(conn, query, limit=60, roots=None, match="all",
           content=True, ext_filter=None):
    """先按 AND 检索；一个都没命中时退化成 OR。"""
    return search_with_mode(
        conn, query, limit, roots, match, content, ext_filter
    )[0]


def search_or(conn, query, limit=60, roots=None, content=True, ext_filter=None):
    """直接走"命中任一关键词"。

    取词场景专用：这些关键词是从一段话里猜出来的，不是用户精确指定的，
    用 AND 卡几乎必然 0 命中，每次都要白跑一次再回退。
    """
    text = (query or "").strip()
    if not text:
        return []
    expr = build_query_expr(text, "OR")
    if not expr:
        return []
    try:
        results = _run(conn, expr, _fetch_limit(limit), roots, ext_filter, not content)
        return _finalize_results(results, text, limit)
    except sqlite3.OperationalError:
        return []
