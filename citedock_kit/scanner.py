# -*- coding: utf-8 -*-
"""目录遍历与过滤：只在白名单根目录内、按排除规则挑出可索引文件。"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass

from .paths import ARTIFACT_DIR_NAME


@dataclass
class FileInfo:
    path: str
    name: str
    dir: str
    ext: str
    size: int
    mtime: float
    root: str


def _globbed(name, globs):
    lowered = name.lower()
    for pattern in globs:
        if fnmatch.fnmatch(lowered, pattern.lower()):
            return True
    return False


def iter_files(roots, exclude_dirs, exclude_globs, max_bytes, guard,
               progress=None, stats=None, extra_excludes=None, max_files=0):
    """生成 FileInfo 序列。所有路径都会再经过 guard.in_scope 二次校验。

    stats       调用方传入的 dict，就地累加被丢弃的计数（让"跳过"变得可见）：
                excluded_glob / too_large / hidden / symlink / out_of_scope /
                unreadable / artifact / truncated(0|1)
    extra_excludes  需要无条件排除的绝对目录，如家族统一产物根
    max_files       >0 时最多产出这么多个文件；超出即停止扫描并置 truncated=1。
                    这是防"误把 C:\\ 加进范围"的兜底，调用方必须把 truncated 报给用户。
    """
    excluded_dirs = {str(d).lower() for d in (exclude_dirs or [])}
    excluded_dirs.add(ARTIFACT_DIR_NAME.lower())
    globs = list(exclude_globs or [])
    hard_excludes = [os.path.normcase(os.path.realpath(p)) for p in (extra_excludes or [])]
    counters = stats if stats is not None else {}
    seen = set()
    scanned = 0
    produced = 0

    def bump(key):
        counters[key] = counters.get(key, 0) + 1

    def under_hard_exclude(path):
        try:
            lowered = os.path.normcase(os.path.realpath(path))
        except OSError:
            return False
        return any(
            lowered == base or lowered.startswith(base + os.sep)
            for base in hard_excludes
        )

    for root in roots or []:
        try:
            real_root = os.path.realpath(root)
        except OSError:
            continue
        if not os.path.isdir(real_root):
            continue

        for current, dirnames, filenames in os.walk(real_root, followlinks=False):
            dirnames[:] = [
                d for d in dirnames
                if d.lower() not in excluded_dirs and not d.startswith(".")
            ]
            for filename in filenames:
                full = os.path.join(current, filename)
                if os.path.islink(full):
                    bump("symlink")
                    continue
                if under_hard_exclude(full):
                    bump("artifact")
                    continue
                if not guard.in_scope(full):
                    bump("out_of_scope")
                    continue
                if _globbed(filename, globs):
                    bump("excluded_glob")
                    continue
                base, ext = os.path.splitext(filename)
                if base.startswith(".") and ext == "":
                    bump("hidden")
                    continue
                try:
                    stat = os.stat(full)
                except OSError:
                    bump("unreadable")
                    continue
                if not stat.st_size or stat.st_size > max_bytes:
                    bump("too_large")
                    continue
                key = os.path.normcase(full)
                if key in seen:
                    continue
                if max_files and produced >= max_files:
                    counters["truncated"] = 1
                    return
                seen.add(key)
                produced += 1
                scanned += 1
                if progress and scanned % 500 == 0:
                    progress(scanned, current)
                yield FileInfo(
                    path=full,
                    name=filename,
                    dir=current,
                    ext=ext.lower(),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    root=os.path.normcase(real_root),
                )
