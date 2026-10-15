# -*- coding: utf-8 -*-
"""安全边界层。

三条硬约束集中在这里实现，其它模块不得绕过：
1. 源文件只读 —— open_source() 拒绝任何写模式。
2. 范围白名单 —— 路径 realpath 必须落在用户指定的 roots 内，否则抛 ScopeViolation。
3. 永不覆盖 —— free_path() 为已存在的目标生成带版本后缀的新名字。
"""
from __future__ import annotations

import os
import time
from datetime import datetime


class ScopeViolation(Exception):
    """路径超出用户设定的检索范围。"""


class Guard:
    def __init__(self, roots=None, audit_file=None, audit_enabled=True):
        self._roots = []
        self.audit_file = audit_file
        self.audit_enabled = bool(audit_enabled)
        self.set_roots(roots or [])

    # ---------- 范围 ----------

    def set_roots(self, roots):
        self._roots = []
        for item in roots or []:
            if not item:
                continue
            try:
                real = os.path.realpath(item)
            except OSError:
                continue
            if os.path.isdir(real):
                self._roots.append(os.path.normcase(real))

    @property
    def roots(self):
        return list(self._roots)

    def has_roots(self):
        return bool(self._roots)

    def in_scope(self, path):
        if not self._roots:
            return False
        try:
            real = os.path.normcase(os.path.realpath(path))
        except OSError:
            return False
        for root in self._roots:
            if real == root or real.startswith(root + os.sep):
                return True
        return False

    def require_in_scope(self, path):
        if not self.in_scope(path):
            raise ScopeViolation("路径不在检索范围内：%s" % path)
        return os.path.realpath(path)

    def scope_label(self, path):
        """返回该文件所属的白名单根目录（用于界面分组显示）。"""
        try:
            real = os.path.realpath(path)
        except OSError:
            return ""
        lowered = os.path.normcase(real)
        for root in self._roots:
            if lowered == root or lowered.startswith(root + os.sep):
                return root
        return ""

    # ---------- 只读 ----------

    def check_readonly_mode(self, mode):
        if mode is None:
            return "r"
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise ValueError("源文件只读：禁止以写模式打开（mode=%r）" % mode)
        return mode

    def open_source(self, path, mode="rb", **kwargs):
        """打开源文件的唯一入口，永远只读。"""
        safe_mode = self.check_readonly_mode(mode)
        return open(path, safe_mode, **kwargs)

    # ---------- 目标 ----------

    def free_path(self, target, stamp=True):
        """目标已存在时不覆盖，改用带后缀的新文件名。"""
        if not os.path.exists(target):
            return target
        base, ext = os.path.splitext(target)
        if stamp:
            tag = datetime.now().strftime("%Y%m%d-%H%M%S")
            candidate = "%s_%s%s" % (base, tag, ext)
            if not os.path.exists(candidate):
                return candidate
        index = 2
        while True:
            candidate = "%s_v%d%s" % (base, index, ext)
            if not os.path.exists(candidate):
                return candidate
            index += 1

    # ---------- 审计 ----------

    def audit(self, action, **fields):
        if not self.audit_enabled or not self.audit_file:
            return
        parts = ["%s=%s" % (key, fields[key]) for key in sorted(fields)]
        line = "%s\t%s\t%s\n" % (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            action,
            " ".join(parts),
        )
        try:
            os.makedirs(os.path.dirname(self.audit_file), exist_ok=True)
            with open(self.audit_file, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass


def now_ts():
    return time.time()
