# -*- coding: utf-8 -*-
"""运行期路径与写盘约定。

数据目录规则（三个项目统一）：
    默认 %LOCALAPPDATA%/<app_name>，可用环境变量覆盖；
    测试时一律用 %TEMP%，不污染用户目录。

原子写：
    先写同目录下的临时文件，再 os.replace 到目标。
    注意 os.replace 是「覆盖」语义 —— 调用前必须先用
    safeguard.Guard.free_path() 拿到一个不冲突的目标名。
"""
from __future__ import annotations

import os
import tempfile


def data_dir(app_name, env_var=None):
    """返回（并创建）该项目的运行期数据目录。"""
    override = os.environ.get(env_var) if env_var else None
    if override:
        path = override
    else:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, app_name)
    os.makedirs(path, exist_ok=True)
    return path


def file_in(folder, name):
    return os.path.join(folder, name)


def atomic_write_text(target, text, encoding="utf-8", newline=""):
    """原子写文本。target 必须是调用方已经确认过不冲突的路径。"""
    folder = os.path.dirname(os.path.abspath(target)) or "."
    os.makedirs(folder, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding=encoding, newline=newline,
        dir=folder, prefix=".tmp-", suffix=".part", delete=False,
    )
    temp_path = handle.name
    try:
        with handle:
            handle.write(text)
        os.replace(temp_path, target)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return target


def sibling_of(module_file, *names):
    """按当前文件位置找兄弟目录，方便项目用 sys.path 引用本包。"""
    here = os.path.dirname(os.path.abspath(module_file))
    return os.path.join(here, *names)


# ---------------------------------------------------------------------------
# 家族统一产物根
# ---------------------------------------------------------------------------
# 三个项目都往这里写产物（检索坞没有产物，压缩坞写摘要与锚点，路由写锚点缓存）。
# 各项目的扫描器无条件排除它 —— 否则产物会被自己索引，形成"产物再喂给产物"的回灌，
# 压缩场景下会造成语义逐层衰减（文件不涨，质量悄悄烂掉）。
ARTIFACT_DIR_NAME = "_output"


def artifact_root(workspace):
    return os.path.join(workspace, ARTIFACT_DIR_NAME)


def is_under(path, folder):
    """path 是否等于 folder 或位于其下（都用 realpath 比较，大小写不敏感）。"""
    try:
        target = os.path.normcase(os.path.realpath(path))
        base = os.path.normcase(os.path.realpath(folder))
    except OSError:
        return False
    return target == base or target.startswith(base + os.sep)
