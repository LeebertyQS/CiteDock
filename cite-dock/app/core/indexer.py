# -*- coding: utf-8 -*-
"""SQLite FTS5 索引：建库、增量同步、统计。

索引库路径由 config.db_path() 决定。写连接只在后台线程使用，读连接在主线程使用，
靠 WAL 模式并存。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

from . import config as config_mod
from . import extract
from .scanner import iter_files
from .textutil import to_index_text

SCHEMA_VERSION = "2"

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
)

DDL = (
    "CREATE TABLE IF NOT EXISTS files ("
    "  path TEXT PRIMARY KEY,"
    "  name TEXT NOT NULL,"
    "  dir TEXT NOT NULL,"
    "  ext TEXT NOT NULL,"
    "  root TEXT NOT NULL DEFAULT '',"
    "  size INTEGER NOT NULL,"
    "  mtime REAL NOT NULL,"
    "  status TEXT NOT NULL,"
    "  indexed_at REAL NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_files_name ON files(name)",
    "CREATE INDEX IF NOT EXISTS idx_files_root ON files(root)",
    "CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5("
    "  path UNINDEXED, name, body, tokenize=\"unicode61 remove_diacritics 2\")",
    "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)",
)


def connect(db_path, readonly=False):
    if readonly:
        uri = "file:%s?mode=ro" % db_path.replace("\\", "/").replace("?", "%3f")
        conn = sqlite3.connect(uri, uri=True, timeout=10)
    else:
        conn = sqlite3.connect(db_path, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    for statement in PRAGMAS:
        conn.execute(statement)

    # 先判断是否需要重建，再跑 DDL —— 否则在老库（files 缺 root 列）上建
    # idx_files_root 会直接报 "no such column: root"。
    current = get_meta(conn, "schema_version")
    rebuilt = False
    if current is not None and current != SCHEMA_VERSION:
        # 结构升级：版本号落后
        rebuilt = True
    else:
        # 兼容更老的库：无版本号、但 files 表缺 root 列
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(files)")]
        rebuilt = bool(columns) and "root" not in columns

    if rebuilt:
        # files 与 FTS 的 docs 必须同步清，只清一张会留下孤儿。
        conn.execute("DROP TABLE IF EXISTS docs")
        conn.execute("DROP TABLE IF EXISTS files")
        conn.execute("DELETE FROM meta WHERE k IN ('last_sync', 'last_scan', 'root_count')")

    for statement in DDL:
        conn.execute(statement)
    set_meta(conn, "schema_version", SCHEMA_VERSION)
    conn.commit()
    return rebuilt


def db_ready(db_path):
    return os.path.isfile(db_path) and os.path.getsize(db_path) > 0


def get_meta(conn, key, default=None):
    try:
        row = conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
    except sqlite3.Error:
        # meta 表还没建（全新库首次 init_db 时就会走到这里）—— 等同"没有该键"
        return default
    return row["v"] if row else default


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(k, v) VALUES(?, ?)"
        " ON CONFLICT(k) DO UPDATE SET v = excluded.v",
        (key, str(value)),
    )


def _load_scan(conn):
    raw = get_meta(conn, "last_scan")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def stats(conn):
    """统计口径 —— 把"跳过"拆开，不再糊成一个数。

    旧版 `skipped = total - indexed` 实际是"取文失败数"，而真正被扫描跳过的
    （超大文件、排除类型、超限停止）完全不在统计里，用户永远不知道它们存在。
    """
    empty = {
        "total": 0, "indexed": 0, "truncated": 0, "failed": 0,
        "skipped": 0, "skipped_detail": {}, "scan_truncated": False,
        "mtime_suspect": False, "last_sync": None,
    }
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS total,"
            " COALESCE(SUM(CASE WHEN status IN ('ok','truncated') THEN 1 ELSE 0 END), 0) AS indexed,"
            " COALESCE(SUM(CASE WHEN status = 'truncated' THEN 1 ELSE 0 END), 0) AS truncated"
            " FROM files"
        ).fetchone()
        total = row["total"]
        indexed = row["indexed"]
        truncated = row["truncated"]
        last = get_meta(conn, "last_sync")
    except sqlite3.Error:
        return dict(empty)

    scan = _load_scan(conn)
    detail = {k: v for k, v in scan.items()
              if k not in ("truncated", "mtime_suspect") and isinstance(v, int)}
    return {
        "total": total,
        "indexed": indexed,
        "truncated": truncated,
        "failed": total - indexed,
        "skipped": sum(detail.values()),
        "skipped_detail": detail,
        "scan_truncated": bool(scan.get("truncated")),
        "mtime_suspect": bool(scan.get("mtime_suspect")),
        "last_sync": float(last) if last else None,
    }


def _mtime_looks_synthetic(conn, total):
    """解压/同步/批量复制过来的文件，mtime 会统一变成同一天 —— 此时"新近加权"失效。
    参数假设失效必须可见，所以这里探测出来往上报。"""
    if total < 20:
        return False
    try:
        today = conn.execute(
            "SELECT COUNT(*) AS n FROM files"
            " WHERE date(mtime, 'unixepoch', 'localtime') = date('now', 'localtime')"
        ).fetchone()["n"]
    except sqlite3.Error:
        return False
    return (today / float(total)) >= 0.7


def sync_index(conn, cfg, guard, progress=None, should_cancel=None):
    """增量同步：新增/变更/删除三路处理。返回统计字典。"""
    roots = config_mod.all_roots(cfg)
    excluded = cfg.get("exclude_dirs") or []
    globs = cfg.get("exclude_globs") or []
    max_bytes = int(cfg.get("max_file_bytes") or 2 * 1024 * 1024)
    max_chars = int(cfg.get("max_index_chars") or 400000)
    max_files = int(cfg.get("max_index_files") or 0)

    started = time.time()
    scan_stats = {}
    disk = {}
    for info in iter_files(
        roots, excluded, globs, max_bytes, guard,
        stats=scan_stats,
        extra_excludes=[config_mod.artifact_dir()],
        max_files=max_files,
    ):
        disk[info.path] = info

    old = {}
    for row in conn.execute("SELECT path, size, mtime FROM files"):
        old[row["path"]] = (row["size"], row["mtime"])

    added = [p for p in disk if p not in old]
    updated = [
        p for p in disk
        if p in old and (
            old[p][0] != disk[p].size or abs(old[p][1] - disk[p].mtime) > 0.001
        )
    ]
    removed = [p for p in old if p not in disk]

    work = added + updated
    total = len(work)
    done = 0
    ok = 0
    truncated_n = 0
    failed = 0

    for path in work:
        if should_cancel and should_cancel():
            break
        info = disk[path]
        text, error, was_truncated = extract.extract_text(
            path, info.ext, max_chars, guard=guard
        )
        if error:
            status = "skip:" + error
        elif was_truncated:
            status = "truncated"
        else:
            status = "ok"

        wrote = True
        try:
            conn.execute("DELETE FROM docs WHERE path = ?", (path,))
            conn.execute(
                "INSERT INTO files(path, name, dir, ext, root, size, mtime, status, indexed_at)"
                " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(path) DO UPDATE SET"
                "  name = excluded.name, dir = excluded.dir, ext = excluded.ext,"
                "  root = excluded.root, size = excluded.size, mtime = excluded.mtime,"
                "  status = excluded.status, indexed_at = excluded.indexed_at",
                (path, info.name, info.dir, info.ext, info.root, info.size,
                 info.mtime, status, time.time()),
            )
            if text:
                conn.execute(
                    "INSERT INTO docs(path, name, body) VALUES(?, ?, ?)",
                    (path, to_index_text(info.name), to_index_text(text)),
                )
        except sqlite3.Error:
            wrote = False

        # 计数必须与"实际写库成功"对齐：旧版在写库之前就把 ok 加了，
        # 写库失败还会让 failed 加两次。
        if not wrote:
            failed += 1
        elif error:
            failed += 1
        elif was_truncated:
            truncated_n += 1
            ok += 1
        else:
            ok += 1

        done += 1
        if done % 20 == 0:
            conn.commit()
            if progress:
                progress(done, total, info.name)

    for path in removed:
        conn.execute("DELETE FROM docs WHERE path = ?", (path,))
        conn.execute("DELETE FROM files WHERE path = ?", (path,))

    set_meta(conn, "last_sync", time.time())
    set_meta(conn, "root_count", len(roots))
    conn.commit()

    suspected = _mtime_looks_synthetic(conn, len(disk))
    scan_stats["mtime_suspect"] = 1 if suspected else 0
    set_meta(conn, "last_scan", json.dumps(scan_stats, ensure_ascii=False))
    conn.commit()

    if progress:
        progress(total, total, "")

    result = {
        "added": len(added),
        "updated": len(updated),
        "removed": len(removed),
        "failed": failed,
        "ok": ok,
        "truncated": truncated_n,
        "scanned": len(disk),
        "skipped_detail": {k: v for k, v in scan_stats.items()
                           if k not in ("truncated", "mtime_suspect")},
        "skipped_total": sum(
            v for k, v in scan_stats.items()
            if k not in ("truncated", "mtime_suspect")
        ),
        "scan_truncated": bool(scan_stats.get("truncated")),
        "scan_limit": max_files,
        "mtime_suspect": suspected,
        "seconds": round(time.time() - started, 2),
    }
    guard.audit(
        "index_sync",
        scanned=result["scanned"],
        added=result["added"],
        updated=result["updated"],
        removed=result["removed"],
        failed=result["failed"],
        truncated=result["truncated"],
        skipped=result["skipped_total"],
        scan_truncated=int(result["scan_truncated"]),
    )
    return result


def reset_db(db_path):
    """把索引库（连同 WAL 侧文件）挪到带时间戳的备份名，返回备份基名。

    调用方必须先关闭所有连接。这是索引库损坏时唯一的恢复路径 ——
    旧版没有它，用户只能自己去 %LOCALAPPDATA% 手动删文件。
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = "%s.bak-%s" % (db_path, stamp)
    moved = False
    for suffix in ("", "-wal", "-shm"):
        source = db_path + suffix
        if os.path.exists(source):
            os.replace(source, backup + suffix)
            moved = True
    return backup if moved else None


def prune_out_of_scope(conn, guard):
    """把已经不在白名单内的记录清掉（用户删掉了某个检索范围时用）。"""
    victims = []
    for row in conn.execute("SELECT path FROM files"):
        if not guard.in_scope(row["path"]):
            victims.append(row["path"])
    for path in victims:
        conn.execute("DELETE FROM docs WHERE path = ?", (path,))
        conn.execute("DELETE FROM files WHERE path = ?", (path,))
    conn.commit()
    return len(victims)
