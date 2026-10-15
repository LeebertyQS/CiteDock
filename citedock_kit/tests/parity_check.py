# -*- coding: utf-8 -*-
"""结构守卫：保证共享模块的「真实实现只有一份」。

背景：cite-dock 曾经自带 safeguard / textutil / extract / scanner 四个副本，
现已改成转发存根（`from citedock_kit.xxx import *`），实现统一收在 citedock_kit/。
本脚本防止有人又把实现内联回去，导致安全收口重新分裂成两处。

对每个共享模块，两种状态都算合格：
  存根态 —— cite-dock 侧是 `from citedock_kit.… import *`，实现只在 citedock_kit/
  副本态 —— 两边逐字节一致（迁移过渡期的合法状态）

用法：python tests/parity_check.py
"""
from __future__ import annotations

import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
WORKSPACE = os.path.dirname(KIT)

SHARED = ("safeguard", "textutil", "extract", "scanner")
CONSUMERS = {
    "cite-dock": os.path.join(WORKSPACE, "cite-dock", "app", "core"),
}

SHIM_MARK = "from citedock_kit."


def digest(path):
    with open(path, "rb") as handle:
        return hashlib.md5(handle.read()).hexdigest()


def main():
    problems = []
    stats = {"shim": 0, "copy": 0}

    for name in SHARED:
        kit_file = os.path.join(KIT, name + ".py")
        if not os.path.isfile(kit_file):
            problems.append("citedock_kit/%s.py 缺失（真实实现必须在这里）" % name)
            continue

        for label, root in CONSUMERS.items():
            target = os.path.join(root, name + ".py")
            if not os.path.isfile(target):
                print("miss  %s/%s.py（未使用该模块，跳过）" % (label, name))
                continue
            with open(target, "r", encoding="utf-8") as handle:
                source = handle.read()

            if SHIM_MARK in source:
                stats["shim"] += 1
                print("shim  %s/%s.py  -> citedock_kit/%s.py" % (label, name, name))
            elif digest(target) == digest(kit_file):
                stats["copy"] += 1
                print("copy  %s/%s.py  与 kit 逐字节一致" % (label, name))
            else:
                problems.append(
                    "%s/%s.py 既不是存根，又与 citedock_kit/%s.py 不一致（实现分裂了）"
                    % (label, name, name)
                )

    print("\n存根 %d 个 / 副本 %d 个" % (stats["shim"], stats["copy"]))
    if problems:
        print("发现问题：")
        for item in problems:
            print("  -", item)
        return 1
    if stats["shim"] == len(SHARED):
        print("STRUCTURE OK（实现只有一份，安全收口未分裂）")
    else:
        print("STRUCTURE OK（过渡期副本状态，两边一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
