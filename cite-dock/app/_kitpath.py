# -*- coding: utf-8 -*-
"""cite-dock 与共享包 citedock_kit 之间的路径引导 + 启动自检。

四个 core 存根（safeguard / extract / textutil / scanner）在导入 citedock_kit 之前
先导入本模块。不做 pip 安装，纯路径引用。

目录假定：
    <workspace>/citedock_kit/                 共享包
    <workspace>/cite-dock/app/_kitpath.py     本文件

两个刻意的选择：

1. **sys.path 用 append 而不是 insert(0)**
   插到最前面会让 `<workspace>/` 下任何子目录名抢占模块解析 ——
   只要有人在那儿放一个叫 `app/` 或 `tests/` 的东西，`import app` 就会静默解析到错的包，
   报错还会非常离奇。`citedock_kit` 这名字足够独特，追加到末尾被抢的概率远小于前者。

2. **导入即自检**
   缺包、版本过旧、符号缺失，都在这里一次性报成人话。否则会以
   `ModuleNotFoundError` 或一层层存根帧的形式炸在深处，排查成本很高。
"""
from __future__ import annotations

import importlib
import os
import sys

WORKSPACE = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
KIT_DIR = os.path.join(WORKSPACE, "citedock_kit")

# Nuitka 打包时 citedock_kit 会被编译进 exe，磁盘上不再有兄弟目录：
# 冻结模式下跳过基于 __file__ 的路径自检，直接走冻结导入。
# 普通运行 FROZEN 为 False，行为不变。
FROZEN = getattr(sys, "frozen", False) or "__compiled__" in globals()

MIN_KIT_VERSION = (1, 1, 0)

REQUIRED_SYMBOLS = {
    "safeguard": ("Guard", "ScopeViolation"),
    "extract": ("extract_text", "read_for_copy", "sniff_decode"),
    "scanner": ("iter_files", "FileInfo"),
    "textutil": (
        "to_index_text", "from_index_text", "build_query_expr",
        "estimate_tokens", "human_size", "MARK_L", "MARK_R", "CJK_RE",
    ),
    "paths": ("data_dir", "artifact_root", "is_under", "ARTIFACT_DIR_NAME"),
}


def _fail(headline, detail="", fix=""):
    lines = [headline]
    if detail:
        lines.append("  " + detail)
    lines.append("")
    lines.append("cite-dock 依赖与它同级的共享包 citedock_kit。")
    lines.append("  预期位置：%s" % KIT_DIR)
    if fix:
        lines.append("  " + fix)
    else:
        lines.append("  若项目被移动过，请确认 citedock_kit 与 cite-dock 位于同一目录下。")
    raise ImportError("\n".join(lines))


def _parse_version(text):
    parts = []
    for chunk in str(text).split(".")[:3]:
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)


def _bootstrap():
    if not FROZEN:
        if not os.path.isfile(os.path.join(KIT_DIR, "__init__.py")):
            _fail("找不到共享包目录。", detail="缺少 %s" % KIT_DIR)

        if WORKSPACE not in sys.path:
            sys.path.append(WORKSPACE)

    try:
        kit = importlib.import_module("citedock_kit")
    except ImportError:
        raise
    except Exception as exc:  # noqa: BLE001 - 这里就是要拦住一切并报人话
        _fail("共享包导入失败。", detail="%s: %s" % (type(exc).__name__, exc))

    version = getattr(kit, "__version__", "0")
    if _parse_version(version) < MIN_KIT_VERSION:
        _fail(
            "共享包版本过旧。",
            detail="当前 %s，需要 >= %s"
            % (version, ".".join(str(n) for n in MIN_KIT_VERSION)),
            fix="请更新 citedock_kit（两边通常是一起改的）。",
        )

    missing = []
    for module_name, names in REQUIRED_SYMBOLS.items():
        try:
            module = importlib.import_module("citedock_kit." + module_name)
        except Exception as exc:  # noqa: BLE001
            missing.append("citedock_kit.%s（无法导入：%s）" % (module_name, exc))
            continue
        for symbol in names:
            if not hasattr(module, symbol):
                missing.append("citedock_kit.%s.%s" % (module_name, symbol))

    if missing:
        _fail(
            "共享包缺少 cite-dock 需要的符号，两边版本不匹配。",
            detail="\n  ".join(missing),
            fix="通常意味着 cite-dock 更新了而 citedock_kit 没跟着更新（或反之）。",
        )
    return kit


KIT = _bootstrap()
