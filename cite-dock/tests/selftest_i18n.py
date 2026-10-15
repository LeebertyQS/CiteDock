# -*- coding: utf-8 -*-
"""多语言自检。

最要紧的一条：**扫源码里所有 t("…")，检查每条都有英文词条**。
漏翻不会报错（会静默回退成中文），所以必须靠这条守卫钉住。

用法：python tests/selftest_i18n.py
"""
from __future__ import annotations

import ast
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import i18n  # noqa: E402

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]")
# 只算「汉字」，不算中文标点 —— 避免把 "、" 这种纯分隔符误判成漏翻
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

# 这些文件不参与 i18n，理由见 app/i18n.py 的模块注释
SKIP_FILES = {"keyword.py", "theme.py", "i18n.py", "_kitpath.py", "__init__.py"}

FAILURES = []


def check(name, ok, detail=""):
    if ok:
        print("  ok    %s" % name)
    else:
        print("  FAIL  %s  %s" % (name, detail))
        FAILURES.append(name)


def t_call_keys(path):
    """取出源码里所有 t("…") 的字面量 key。"""
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    keys = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    keys.append((node.lineno, arg.value))
    return keys


def module_level_t(path):
    """找出**模块级**调用 t() 的地方 —— 它会在语言选定之前把文案冻结住。

    注意：只查顶层语句，**不能钻进函数/类体**（那里的 t() 是运行时求值，没问题）。
    """
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    bad = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                    and sub.func.id == "t":
                bad.append(sub.lineno)
                break
    return bad


def unwrapped_chinese(path):
    """**反向检查**：找出含汉字、但既不是 docstring、又不是 t() 实参、
    也不是模块级 `*_KEY` 常量的字符串字面量。

    正向检查（[1]）只能发现"包了 t() 但没英文"，发现不了"压根忘了包 t()" ——
    后者更常见，而且会让那句文案永远中文。所以必须双向。

    可证伪性：临时在某个文件里加一句 `QLabel("测试文案")` → 本检查必须失败并指出位置；
    删掉后恢复通过。
    """
    tree = ast.parse(io.open(path, encoding="utf-8").read())

    t_args = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "t":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    t_args.add(id(arg))

    doc_ids = set()

    def mark_doc(body):
        if body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            doc_ids.add(id(body[0].value))

    mark_doc(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            mark_doc(node.body)

    # 模块级 `*_KEY` / `*_TEXT` 常量是翻译 key，使用时才 t()（如 STALE_SUFFIX_KEY）
    key_const = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) \
                        and (tgt.id.endswith("_KEY") or tgt.id.endswith("_TEXT")):
                    if isinstance(node.value, ast.Constant) \
                            and isinstance(node.value.value, str):
                        key_const.add(id(node.value))

    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and HAN.search(node.value):
            if id(node) in t_args or id(node) in doc_ids or id(node) in key_const:
                continue
            bad.append((node.lineno, node.value))
    return bad


def main():
    targets = []
    for folder in ("app/ui", "app/core", "app"):
        base = os.path.join(ROOT, folder)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if name.endswith(".py") and name not in SKIP_FILES and os.path.isfile(full):
                if full not in targets:
                    targets.append(full)
    main_py = os.path.join(ROOT, "app", "main.py")
    if main_py not in targets:
        targets.append(main_py)

    print("\n[0] 漏包 t() 检查（反向）")
    unwrapped = []
    for path in targets:
        for lineno, val in unwrapped_chinese(path):
            unwrapped.append("%s:%d  %s" % (os.path.basename(path), lineno, val[:36]))
    check("所有含汉字的字面量都包了 t()（或 docstring / *_KEY 常量）", not unwrapped,
          "漏包 %d 处：\n    %s" % (len(unwrapped), "\n    ".join(unwrapped[:12])))

    print("\n[1] 漏翻检查")
    missing = []
    total = 0
    for path in targets:
        for lineno, key in t_call_keys(path):
            total += 1
            if i18n.missing_english(key):
                missing.append("%s:%d  %s" % (os.path.basename(path), lineno, key[:40]))
    print("  共扫描 %d 处 t() 调用" % total)
    check("每条 t() 都有英文词条", not missing,
          "缺 %d 条：\n    %s" % (len(missing), "\n    ".join(missing[:12])))

    print("\n[2] 模块级 t() 检查")
    frozen = []
    for path in targets:
        for lineno in module_level_t(path):
            frozen.append("%s:%d" % (os.path.basename(path), lineno))
    check("没有模块级调用 t()（否则语言会被冻结）", not frozen, frozen)

    print("\n[3] 译文里不该夹中文")
    residual = {k: v for k, v in i18n.ENGLISH.items() if CJK.search(v)}
    check("英文词条不含中文", not residual, list(residual)[:6])

    print("\n[4] 往返切换")
    probes = ["取词", "检索目录", "文件名命中", "设置"]
    ok = True
    detail = ""
    for lang in ("en", "zh", "en"):
        i18n.set_language(lang)
        for text in probes:
            back = i18n.to_zh(i18n.t(text))
            if back != text:
                ok = False
                detail = "%s → %s → %s" % (text, i18n.t(text), back)
    i18n.set_language("zh")
    check("中英来回切换文案能回到原文", ok, detail)

    print("\n[5] 未知键回退")
    i18n.set_language("en")
    check("没有译文的原文回退成原样",
          i18n.t("这条没有英文") == "这条没有英文")
    i18n.set_language("zh")
    check("中文模式原样返回", i18n.t("取词") == "取词")

    print("\n" + "=" * 52)
    if FAILURES:
        print("失败 %d 项：%s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("ALL I18N CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
