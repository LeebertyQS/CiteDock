# -*- coding: utf-8 -*-
"""多个 UI 模块共用的小工具函数与常量。

单独成文件是为了避免循环导入：dock_window 要用 selection_bar / result_row，
而它们又都要用这些 helper —— 如果 helper 塞在 dock_window 里就会
dock_window → selection_bar → dock_window 互相 import。
"""
import html
import os
import time

from ..core.textutil import MARK_L, MARK_R


LIST_MAX_HEIGHT = 330
PLACEHOLDER_HEIGHT = 48


def _stamp(mtime):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(mtime)))
    except (TypeError, ValueError, OSError):
        return "-"


def _snippet_html(text, pal):
    escaped = html.escape(text or "")
    escaped = escaped.replace(
        MARK_L,
        '<span style="background-color:%s;color:%s;">' % (pal["hl_bg"], pal["hl_fg"]),
    ).replace(MARK_R, "</span>")
    return escaped


def _plain(text, limit=90):
    text = (text or "").replace(MARK_L, "").replace(MARK_R, "")
    if len(text) > limit:
        return text[:limit] + "\u2026"
    return text


def _snippet_plain(text, limit=110):
    """按“可见字符数”截断片段，但把高亮标记原样带过去。"""
    text = text or ""
    visible = len(text) - text.count(MARK_L) - text.count(MARK_R)
    if visible <= limit:
        return text
    out = []
    seen = 0
    for char in text:
        if char in (MARK_L, MARK_R):
            out.append(char)
            continue
        if seen >= limit:
            break
        out.append(char)
        seen += 1
    return "".join(out) + "\u2026" + MARK_R


def _quote_if_needed(path):
    return '"%s"' % path if " " in path else path


def _display_dir(data, guard):
    """目录显示成相对检索范围的短路径；绝对路径留在 tooltip 里。"""
    if guard is not None:
        root = guard.scope_label(data["path"])
        if root:
            try:
                relative = os.path.relpath(data["dir"], root)
            except ValueError:
                relative = ""
            if relative and relative != ".":
                return relative.replace(os.sep, "/")
            return os.path.basename(root.rstrip(os.sep)) or root
    return _plain(data["dir"], 60)
