# -*- coding: utf-8 -*-
"""CiteDock 配置读写。

数据目录优先级：环境变量 CITEDOCK_HOME > %LOCALAPPDATA%/CiteDock。
所有运行期数据（config.json / index.db / audit.log）都落在这里，不污染用户目录。
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import time

from .._kitpath import KIT, WORKSPACE
from ..i18n import t

APP_NAME = "CiteDock"

CONFIG_VERSION = 2

DEFAULT_EXCLUDE_DIRS = [
    ".git", ".svn", ".hg", ".workbuddy", "node_modules", "__pycache__",
    "build", "dist", "out", ".venv", "venv", "env", ".idea", ".vs",
    ".vscode", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".next", ".nuxt", ".cache", "System Volume Information", "$RECYCLE.BIN",
    # 家族统一产物根：三个项目的产物都落在这里，绝不能反过来被索引
    "_output",
]

DEFAULT_EXCLUDE_GLOBS = [
    "*.exe", "*.dll", "*.so", "*.dylib", "*.lib", "*.obj", "*.o", "*.a",
    "*.zip", "*.7z", "*.rar", "*.tar", "*.gz", "*.bz2", "*.xz",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.bmp", "*.ico", "*.svg",
    "*.mp3", "*.wav", "*.flac", "*.mp4", "*.mov", "*.avi", "*.mkv",
    "*.ttf", "*.otf", "*.woff", "*.woff2", "*.eot",
    "*.pyc", "*.pyo", "*.pyd", "*.class", "*.bin", "*.dat", "*.pak",
    "*.db", "*.sqlite", "*.sqlite3", "*.lock", "*.min.js", "*.min.css",
    "*.map", "*.tmp", "*.bak", "*.swp",
]

DEFAULT_TEXT_EXTS = [
    ".txt", ".md", ".markdown", ".mdx", ".rst", ".log", ".json", ".jsonl",
    ".ndjson", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".csv", ".tsv", ".xml", ".html", ".htm", ".css", ".scss", ".less",
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
    ".py", ".pyi", ".java", ".kt", ".kts", ".c", ".h", ".cc", ".cpp", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".m", ".mm", ".scala",
    ".sql", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".gradle",
    ".properties", ".tex", ".srt", ".vtt", ".mmd", ".lua", ".r", ".pl",
    ".dart", ".groovy", ".erl", ".ex", ".exs", ".fs", ".vb", ".asm",
]

DEFAULT_SEARCH = {
    "content": True,
    "match": "all",
    "ext_filter": [],
    "limit": 60,
    "snippet_chars": 100,
}


DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "scopes": [],
    "active_scope": "",
    "exclude_dirs": list(DEFAULT_EXCLUDE_DIRS),
    "exclude_globs": list(DEFAULT_EXCLUDE_GLOBS),
    "text_exts": list(DEFAULT_TEXT_EXTS),
    "max_file_bytes": 2 * 1024 * 1024,
    "max_index_chars": 400000,
    "max_index_files": 50000,
    "copy_total_chars": 200000,
    "hotkey": "Ctrl+Alt+Space",
    "hotkey_select": "Ctrl+Alt+D",
    "pin_default": False,
    "auto_grab_clipboard": True,
    "theme": "auto",
    "language": "auto",
    "window_pos": None,
    "window_pinned": False,
    "output_dir": None,
    "audit_enabled": True,
    "offline_assert": False,
    "mousehook_enabled": False,
    "mousehook_exclude": [
        "WindowsTerminal", "cmd", "powershell", "pwsh", "mintty", "putty",
        "conhost", "wt",
    ],
    "mousehook_wait_ms": 120,
}


class ConfigError(ValueError):
    """配置结构不合法时抛出，消息直接对用户可见。"""


def data_dir() -> str:
    env = os.environ.get("CITEDOCK_HOME")
    if env:
        path = env
    else:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(data_dir(), "config.json")


def db_path() -> str:
    return os.path.join(data_dir(), "index.db")


def artifact_dir() -> str:
    """家族统一产物根：<workspace>/_output。

    三个项目都往这里写产物。扫描时无条件排除它（名字匹配 + 绝对路径双保险）——
    否则产物会被自己索引，检索命中自己的产物、再喂回整理器，形成回灌；
    压缩场景下更隐蔽：摘要的摘要的摘要，文件不涨但语义逐层衰减。
    """
    return KIT.paths.artifact_root(WORKSPACE)


def audit_path() -> str:
    return os.path.join(data_dir(), "audit.log")


def default_config() -> dict:
    return copy.deepcopy(DEFAULT_CONFIG)


def default_search() -> dict:
    return copy.deepcopy(DEFAULT_SEARCH)


def all_roots(cfg: dict) -> list:
    """所有检索范围的所有根（并集，去重、保序）。

    G-1：guard 与索引永远基于这个并集，绝不能只用当前选中范围的根。
    """
    roots = []
    seen = set()
    for scope in cfg.get("scopes") or []:
        if not isinstance(scope, dict):
            continue
        for root in scope.get("roots") or []:
            if not root:
                continue
            try:
                key = os.path.normcase(os.path.realpath(root))
            except OSError:
                key = os.path.normcase(root)
            if key in seen:
                continue
            seen.add(key)
            roots.append(root)
    return roots


def active_scope(cfg: dict):
    """返回当前活动范围对象；悬空或没有范围时返回 None。"""
    name = cfg.get("active_scope")
    for scope in cfg.get("scopes") or []:
        if isinstance(scope, dict) and scope.get("name") == name:
            return scope
    return None


def active_roots(cfg: dict) -> list:
    """当前活动范围的根列表（原样返回，未做 realpath 归一化）。"""
    scope = active_scope(cfg)
    return list(scope.get("roots") or []) if scope else []


def search_setting(cfg: dict, key: str, default=None):
    """读当前活动范围的检索设置；活动范围不存在时回落到全局默认。"""
    scope = active_scope(cfg)
    search = scope.get("search") if scope else None
    if isinstance(search, dict) and key in search:
        return search[key]
    return DEFAULT_SEARCH.get(key, default)


def _backup_old_config(path: str) -> str:
    """迁移前把旧 config 另存为 config.json.bak-<时间戳>，失败可回退。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = "%s.bak-%s" % (path, stamp)
    if os.path.isfile(path):
        shutil.copy2(path, backup)
    return backup


def _migrate(cfg: dict, path: str) -> dict:
    """旧格式（顶层 watch_roots）一次性迁移到 v2 scopes 结构并写回。"""
    old_roots = list(cfg.get("watch_roots") or [])
    old_limit = cfg.get("search_limit")
    _backup_old_config(path)

    scopes = []
    if old_roots:
        search = default_search()
        if old_limit is not None:
            search["limit"] = old_limit
        scopes = [{"name": t("默认"), "roots": old_roots, "search": search}]

    cfg["config_version"] = CONFIG_VERSION
    cfg["scopes"] = scopes
    cfg["active_scope"] = scopes[0]["name"] if scopes else ""
    cfg.pop("watch_roots", None)
    cfg.pop("search_limit", None)
    save(cfg)
    return cfg


def _validate(cfg: dict) -> bool:
    """v2 结构校验。返回 True 表示修复了 active_scope（调用方应写回）。"""
    scopes = cfg.get("scopes")
    if scopes is None:
        scopes = []
        cfg["scopes"] = scopes
    if not isinstance(scopes, list):
        raise ConfigError(t("scopes 必须是数组"))

    seen = set()
    for index, scope in enumerate(scopes):
        if not isinstance(scope, dict):
            raise ConfigError(t("第 %d 个检索范围不是对象") % (index + 1))
        name = scope.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(t("第 %d 个检索范围的名字为空") % (index + 1))
        name = name.strip()
        if len(name) > 12:
            raise ConfigError(t("检索范围名「%s」超过 12 字符") % name)
        if name in seen:
            raise ConfigError(t("检索范围名「%s」重复") % name)
        seen.add(name)
        roots = scope.get("roots")
        if not isinstance(roots, list) or not any(roots):
            raise ConfigError(t("检索范围「%s」没有检索目录（roots 为空）") % name)

    names = [scope.get("name") for scope in scopes if isinstance(scope, dict)]
    active = cfg.get("active_scope")
    if active in names:
        return False
    fallback = names[0] if names else ""
    if active:
        print(
            t("提示：active_scope「%s」不存在，已回退到「%s」")
            % (active, fallback or t("（无）")),
            file=sys.stderr,
        )
    cfg["active_scope"] = fallback
    return True


def load() -> dict:
    path = config_path()
    user = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                user = data
        except (OSError, ValueError):
            pass
    cfg = default_config()
    cfg.update(user)
    if user.get("config_version") != CONFIG_VERSION and "watch_roots" in user:
        cfg = _migrate(cfg, path)
    elif _validate(cfg):
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    path = config_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(cfg, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
