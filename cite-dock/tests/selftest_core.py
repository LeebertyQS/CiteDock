# -*- coding: utf-8 -*-
"""CiteDock 核心层自检。

覆盖：索引口径（新增/更新/截断/跳过分类）、检索（AND/OR 回退/宽松）、
排序一致性、产物根排除、文件数上限、安全边界（越界/只读/源文件未改动）、索引库重建。

用法：python tests/selftest_core.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SANDBOX = os.path.join(tempfile.gettempdir(), "citedock_selftest")

DOCS = {
    "简历-销售岗.md": "# 简历\n\n目标岗位：外企销售管培。经历：极氪汽车销售实习，负责门店线索跟进与试驾邀约。\n",
    "异环-开放世界拆解.md": "异环的开放世界设计：城市探索、载具系统、二次元角色养成。核心循环是探索-战斗-养成。\n",
    "三谋-slg拆解.md": "三国谋定天下属于 SLG 品类，强调同盟协作、赛季制、资源争夺与行军路线规划。\n",
    "sub/readme.txt": "这里放一些杂项笔记，用来验证中文子串检索是否生效：迷宫生成算法、WFC 波函数坍缩。\n",
    "memo/meeting.md": "Weekly sync about the open world prototype and the level design pipeline.\n",
}

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("  ok    %s" % name)
    else:
        print("  FAIL  %s  %s" % (name, detail))
        FAILURES.append(name)


def use_home(tag):
    """每次换一个隔离的数据目录，避免子测试之间互相污染。"""
    home = os.path.join(SANDBOX, "_data_" + tag)
    os.environ["CITEDOCK_HOME"] = home
    os.makedirs(home, exist_ok=True)
    return home


def build_corpus():
    if os.path.isdir(SANDBOX):
        shutil.rmtree(SANDBOX)
    docs = os.path.join(SANDBOX, "docs")
    for relative, text in DOCS.items():
        target = os.path.join(docs, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text)
    return docs


os.environ["CITEDOCK_HOME"] = os.path.join(SANDBOX, "_data")
DOCS_DIR = build_corpus()

from app.core import config as config_mod                      # noqa: E402
from app.core import indexer, keyword, search                  # noqa: E402
from app.core.safeguard import Guard, ScopeViolation           # noqa: E402

before_bytes = {}
for _base, _dirs, _files in os.walk(DOCS_DIR):
    for _name in _files:
        _full = os.path.join(_base, _name)
        with open(_full, "rb") as _fh:
            before_bytes[_full] = _fh.read()


def make_cfg(docs, **overrides):
    cfg = config_mod.default_config()
    cfg["scopes"] = [{"name": "默认", "roots": [docs], "search": config_mod.default_search()}]
    cfg["active_scope"] = "默认"
    cfg.update(overrides)
    return cfg


# ===========================================================================
print("\n[0] 配置模型：scopes 迁移与校验")
# ===========================================================================
use_home("migrate")
old_path = config_mod.config_path()
with open(old_path, "w", encoding="utf-8") as fh:
    json.dump({
        "watch_roots": ["X:/dir-a", "X:/dir-b"],
        "search_limit": 30,
        "window_pos": [100, 200],
        "pin_default": True,
        "hotkey": "Ctrl+Alt+Space",
    }, fh, ensure_ascii=False)
cfg_mig = config_mod.load()
check("迁移后 config_version=2", cfg_mig.get("config_version") == 2, cfg_mig.get("config_version"))
check("迁移后生成 1 个默认范围", len(cfg_mig.get("scopes") or []) == 1, cfg_mig.get("scopes"))
scope0 = (cfg_mig.get("scopes") or [{}])[0]
check("默认范围装进两个根",
      scope0.get("roots") == ["X:/dir-a", "X:/dir-b"], scope0.get("roots"))
check("search.limit 迁移自 search_limit", scope0.get("search", {}).get("limit") == 30, scope0.get("search"))
check("window_pos/pin_default 未丢",
      cfg_mig.get("window_pos") == [100, 200] and cfg_mig.get("pin_default") is True)
backups = [p for p in os.listdir(os.path.dirname(old_path)) if p.startswith("config.json.bak-")]
check("迁移出现备份文件", bool(backups), backups)
check("配置顶层不再存在 watch_roots", "watch_roots" not in cfg_mig)
before = open(config_mod.config_path(), "rb").read()
config_mod.load()
after = open(config_mod.config_path(), "rb").read()
check("再跑一次配置字节不变", before == after)

bad_cases = [
    ("重名", {"config_version": 2, "scopes": [
        {"name": "A", "roots": ["D:/a"], "search": {}},
        {"name": "A", "roots": ["D:/b"], "search": {}}], "active_scope": "A"}),
    ("空 roots", {"config_version": 2, "scopes": [
        {"name": "A", "roots": [], "search": {}}], "active_scope": "A"}),
    ("名字过长", {"config_version": 2, "scopes": [
        {"name": "这是一个超过十二个字符的名字", "roots": ["D:/a"], "search": {}}], "active_scope": "A"}),
]
for tag, bad in bad_cases:
    use_home("bad_" + tag)
    bad_path = config_mod.config_path()
    os.makedirs(os.path.dirname(bad_path), exist_ok=True)
    with open(bad_path, "w", encoding="utf-8") as fh:
        json.dump(bad, fh, ensure_ascii=False)
    raised = False
    try:
        config_mod.load()
    except config_mod.ConfigError as exc:
        raised = True
        print("      报错:", exc)
    check("坏配置(%s)加载期报明确错误" % tag, raised)

use_home("dangling")
dang_path = config_mod.config_path()
os.makedirs(os.path.dirname(dang_path), exist_ok=True)
with open(dang_path, "w", encoding="utf-8") as fh:
    json.dump({"config_version": 2, "scopes": [
        {"name": "A", "roots": ["D:/a"], "search": {}}], "active_scope": "B"}, fh, ensure_ascii=False)
cfg_dang = config_mod.load()
check("active_scope 悬空回退到第一个范围", cfg_dang.get("active_scope") == "A", cfg_dang.get("active_scope"))


# ===========================================================================
print("\n[1] 基础索引与增量")
# ===========================================================================
use_home("basic")
cfg = make_cfg(DOCS_DIR)
guard = Guard(config_mod.all_roots(cfg), config_mod.audit_path())
conn = indexer.connect(config_mod.db_path())
indexer.init_db(conn)

result = indexer.sync_index(conn, cfg, guard)
print("  index:", {k: result[k] for k in ("added", "updated", "removed", "failed", "ok")})
check("首次索引收录全部文件", result["added"] == len(DOCS), result["added"])
check("无取文失败", result["failed"] == 0, result["failed"])
check("无超限跳过", result["skipped_total"] == 0, result["skipped_detail"])

again = indexer.sync_index(conn, cfg, guard)
check("二次同步零变更",
      again["added"] == 0 and again["updated"] == 0 and again["removed"] == 0,
      (again["added"], again["updated"], again["removed"]))


# ===========================================================================
print("\n[2] 检索")
# ===========================================================================
for query in ["异环", "SLG 拆解", "迷宫生成", "销售", "极氪", "open world"]:
    hits = search.search(conn, query, limit=5)
    check("命中 %-12s -> %d" % (query, len(hits)), bool(hits))

check("无关词零命中", not search.search(conn, "不存在的关键词zzz"))

multi = search.search(conn, "游戏策划 开放世界", limit=10)
check("AND 未命中时回退 OR 有结果", bool(multi), len(multi))
check("宽松检索（取词场景）有结果",
      bool(search.search_or(conn, "游戏策划 开放世界", limit=10)))
check("单关键词走 AND 模式",
      search.search_with_mode(conn, "异环", limit=5)[1] == "AND")
check("命中来源标记合法",
      bool(multi) and all(h.get("match") in ("name", "body", "both") for h in multi))

first = [h["path"] for h in search.search(conn, "销售 管培", limit=10)]
second = [h["path"] for h in search.search(conn, "销售 管培", limit=10)]
check("同查询结果顺序可复现（排序已下沉 SQL）", first == second, (first, second))

# 回归守卫：ORDER BY 一旦写回 `rank`，会被 FTS5 的隐藏列抢走，
# 文件名权重 ×4 就静默失效 —— 用原始 SQL 顺序的"排序键必须单调"把它钉住。
raw = search._run(conn, search.build_query_expr("拆解", "AND"), 10)
keys = [h["sort_key"] for h in raw]
check("排序键单调（说明 ORDER BY 用的是加权 bm25）",
      bool(keys) and keys == sorted(keys), keys)


# ===========================================================================
print("\n[3] 超限与分类统计")
# ===========================================================================
use_home("limits")
limit_dir = os.path.join(SANDBOX, "limits")
os.makedirs(limit_dir, exist_ok=True)
with open(os.path.join(limit_dir, "small.md"), "w", encoding="utf-8") as fh:
    fh.write("这是一个很短的文件。\n")
with open(os.path.join(limit_dir, "long.md"), "w", encoding="utf-8") as fh:
    fh.write("超长正文测试。" * 400)          # 约 8.4 KB：过单文件上限，但正文被截断
with open(os.path.join(limit_dir, "huge.md"), "w", encoding="utf-8") as fh:
    fh.write("x" * 20000)                     # 20 KB：整体超限，整份跳过

cfg3 = make_cfg(limit_dir, max_file_bytes=10000, max_index_chars=300)
guard3 = Guard(config_mod.all_roots(cfg3), config_mod.audit_path())
conn3 = indexer.connect(config_mod.db_path())
indexer.init_db(conn3)
r3 = indexer.sync_index(conn3, cfg3, guard3)
print("  index:", r3["scanned"], r3["truncated"], r3["skipped_detail"])

check("超大文件被计数而非静默丢弃",
      r3["skipped_detail"].get("too_large") == 1, r3["skipped_detail"])
check("超限跳过总数可读", r3["skipped_total"] >= 1, r3["skipped_total"])
check("正文截断被计数", r3["truncated"] == 1, r3["truncated"])

st3 = indexer.stats(conn3)
check("stats 拆出 truncated", st3["truncated"] == 1, st3["truncated"])
check("stats 拆出 skipped 明细", st3["skipped"] >= 1, st3["skipped"])
check("stats 不再把取文失败混进 skipped", st3["failed"] == 0, st3["failed"])
check("已索引数量含被截断的", st3["indexed"] == r3["scanned"], (st3["indexed"], r3["scanned"]))


# ===========================================================================
print("\n[4] 文件数上限（防误加 C:\\ 的兜底）")
# ===========================================================================
use_home("cap")
cap_dir = os.path.join(SANDBOX, "cap")
os.makedirs(cap_dir, exist_ok=True)
for i in range(6):
    with open(os.path.join(cap_dir, "f%d.md" % i), "w", encoding="utf-8") as fh:
        fh.write("文件 %d 内容。\n" % i)

cfg4 = make_cfg(cap_dir, max_index_files=3)
guard4 = Guard(config_mod.all_roots(cfg4), config_mod.audit_path())
conn4 = indexer.connect(config_mod.db_path())
indexer.init_db(conn4)
r4 = indexer.sync_index(conn4, cfg4, guard4)
check("达到文件数上限即停止", r4["scanned"] == 3, r4["scanned"])
check("上限触发被标记（不静默）", r4["scan_truncated"] is True, r4["scan_truncated"])


# ===========================================================================
print("\n[5] 产物根排除")
# ===========================================================================
use_home("artifact")
art_dir = os.path.join(SANDBOX, "artifact")
nested = os.path.join(art_dir, "_output")
os.makedirs(nested, exist_ok=True)
with open(os.path.join(art_dir, "normal.md"), "w", encoding="utf-8") as fh:
    fh.write("正常文档，应当被索引。\n")
with open(os.path.join(nested, "compressed_会话_20261014.md"), "w", encoding="utf-8") as fh:
    fh.write("这是压缩产物，绝不能被索引，否则会被当成原文再压缩一遍。\n")

cfg5 = make_cfg(art_dir)
guard5 = Guard(config_mod.all_roots(cfg5), config_mod.audit_path())
conn5 = indexer.connect(config_mod.db_path())
indexer.init_db(conn5)
indexer.sync_index(conn5, cfg5, guard5)
names = [row["name"] for row in conn5.execute("SELECT name FROM files")]
print("  indexed:", names)
check("普通文档已索引", "normal.md" in names, names)
check("_output 下的产物被排除",
      not any(n.startswith("compressed_") for n in names), names)
check("产物内容搜不到", not search.search(conn5, "压缩产物"))


# ===========================================================================
print("\n[5b] 根归属与 schema 版本")
# ===========================================================================
use_home("rootattr")
root_a = os.path.join(SANDBOX, "rootA")
root_b = os.path.join(SANDBOX, "rootB")
os.makedirs(root_a, exist_ok=True)
os.makedirs(root_b, exist_ok=True)
fa = os.path.join(root_a, "a.md")
fb = os.path.join(root_b, "b.md")
with open(fa, "w", encoding="utf-8") as fh:
    fh.write("同盟玩法 A 内容。\n")
with open(fb, "w", encoding="utf-8") as fh:
    fh.write("同盟玩法 B 内容。\n")

cfg_r = config_mod.default_config()
cfg_r["scopes"] = [
    {"name": "A", "roots": [root_a], "search": config_mod.default_search()},
    {"name": "B", "roots": [root_b], "search": config_mod.default_search()},
]
cfg_r["active_scope"] = "A"
guard_r = Guard(config_mod.all_roots(cfg_r), config_mod.audit_path())
conn_r = indexer.connect(config_mod.db_path())
indexer.init_db(conn_r)
indexer.sync_index(conn_r, cfg_r, guard_r)

rows_r = conn_r.execute("SELECT path, root FROM files ORDER BY path").fetchall()
exp_roots = {
    os.path.normcase(os.path.realpath(fa)): os.path.normcase(os.path.realpath(root_a)),
    os.path.normcase(os.path.realpath(fb)): os.path.normcase(os.path.realpath(root_b)),
}
got_roots = {os.path.normcase(os.path.realpath(r["path"])): r["root"] for r in rows_r}
check("每个文件归属正确的根", got_roots == exp_roots, (got_roots, exp_roots))

count_before = conn_r.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
cfg_r["active_scope"] = "B"
indexer.sync_index(conn_r, cfg_r, guard_r)
count_after = conn_r.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
check("切范围不改变索引数量", count_before == count_after == 2, (count_before, count_after))
check("meta 写入 schema_version", indexer.get_meta(conn_r, "schema_version") == indexer.SCHEMA_VERSION)

# 模拟旧库（无 root 列、schema_version 落后）→ 升级时同步清空 files+docs 再重建
# 旧库本来就没有 idx_files_root，先删掉它才能删 root 列（否则 SQLite 报索引依赖该列）
conn_r.execute("DROP INDEX IF EXISTS idx_files_root")
conn_r.execute("ALTER TABLE files DROP COLUMN root")
indexer.set_meta(conn_r, "schema_version", "1")
conn_r.commit()
indexer.init_db(conn_r)
check("schema 升级清空 files+docs 重建",
      conn_r.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"] == 0)
indexer.sync_index(conn_r, cfg_r, guard_r)
hits_r = search.search(conn_r, "同盟玩法", limit=10)
check("旧库升级后检索结果与升级前一致",
      len(hits_r) == 2 and {h["name"] for h in hits_r} == {"a.md", "b.md"},
      [h["name"] for h in hits_r])
conn_r.close()


# ===========================================================================
print("\n[5c] 检索按范围过滤（进 SQL）")
# ===========================================================================
use_home("scopefilter")
scope_x = os.path.join(SANDBOX, "scopefilterX")
scope_y = os.path.join(SANDBOX, "scopefilterY")
os.makedirs(scope_x, exist_ok=True)
os.makedirs(scope_y, exist_ok=True)
with open(os.path.join(scope_x, "x.md"), "w", encoding="utf-8") as fh:
    fh.write("同盟玩法 X 版本。\n")
with open(os.path.join(scope_y, "y.md"), "w", encoding="utf-8") as fh:
    fh.write("同盟玩法 Y 版本。\n")

cfg_s = config_mod.default_config()
cfg_s["scopes"] = [
    {"name": "X", "roots": [scope_x], "search": config_mod.default_search()},
    {"name": "Y", "roots": [scope_y], "search": config_mod.default_search()},
]
cfg_s["active_scope"] = "X"
guard_s = Guard(config_mod.all_roots(cfg_s), config_mod.audit_path())
conn_s = indexer.connect(config_mod.db_path())
indexer.init_db(conn_s)
indexer.sync_index(conn_s, cfg_s, guard_s)
hits_x = search.search(conn_s, "同盟玩法", roots=config_mod.active_roots(cfg_s))
check("范围 X 只搜到自己的文件", [h["name"] for h in hits_x] == ["x.md"], [h["name"] for h in hits_x])
cfg_s["active_scope"] = "Y"
hits_y = search.search(conn_s, "同盟玩法", roots=config_mod.active_roots(cfg_s))
check("范围 Y 只搜到自己的文件", [h["name"] for h in hits_y] == ["y.md"], [h["name"] for h in hits_y])
conn_s.close()

use_home("postfilter")
cur_dir = os.path.join(SANDBOX, "cur")
bulk_dir = os.path.join(SANDBOX, "bulk")
os.makedirs(cur_dir, exist_ok=True)
os.makedirs(bulk_dir, exist_ok=True)
with open(os.path.join(cur_dir, "cur.md"), "w", encoding="utf-8") as fh:
    fh.write("正文里出现同盟玩法。\n")
for i in range(70):
    with open(os.path.join(bulk_dir, "同盟玩法-%d.md" % i), "w", encoding="utf-8") as fh:
        fh.write("同盟玩法 bulk %d。\n" % i)
cfg_p = config_mod.default_config()
cfg_p["scopes"] = [
    {"name": "cur", "roots": [cur_dir], "search": config_mod.default_search()},
    {"name": "bulk", "roots": [bulk_dir], "search": config_mod.default_search()},
]
cfg_p["active_scope"] = "cur"
guard_p = Guard(config_mod.all_roots(cfg_p), config_mod.audit_path())
conn_p = indexer.connect(config_mod.db_path())
indexer.init_db(conn_p)
indexer.sync_index(conn_p, cfg_p, guard_p)
hits_p = search.search(conn_p, "同盟玩法", limit=1, roots=config_mod.active_roots(cfg_p))
check("事后过滤未发生：当前范围唯一命中能出现（limit=1）",
      [h["name"] for h in hits_p] == ["cur.md"], [h["name"] for h in hits_p])
check("全局确有 60+ 条同名命中",
      len(search.search(conn_p, "同盟玩法", limit=100, roots=config_mod.all_roots(cfg_p))) >= 70)
conn_p.close()

use_home("manyroots")
cfg_m = config_mod.default_config()
cfg_m["scopes"] = [{"name": "M", "roots": ["D:/r%d" % i for i in range(100)],
                    "search": config_mod.default_search()}]
cfg_m["active_scope"] = "M"
conn_m = indexer.connect(config_mod.db_path())
indexer.init_db(conn_m)
ok_many = True
try:
    hits_m = search.search(conn_m, "不存在关键词", roots=config_mod.active_roots(cfg_m))
    ok_many = hits_m == []
except sqlite3.Error:
    ok_many = False
check("范围含 100 个根时仍正常", ok_many)
conn_m.close()


# ===========================================================================
print("\n[5d] 检索选项：content / match / ext_filter")
# ===========================================================================
use_home("contentext")
cdir = os.path.join(SANDBOX, "contentext")
os.makedirs(cdir, exist_ok=True)
for cname, cbody in [
    ("同盟玩法.md", "这是正文内容。\n"),
    ("普通.md", "同盟玩法在正文里。\n"),
    ("同盟玩法.txt", "txt 正文。\n"),
]:
    with open(os.path.join(cdir, cname), "w", encoding="utf-8") as fh:
        fh.write(cbody)
cfg_ce = config_mod.default_config()
cfg_ce["scopes"] = [{"name": "CE", "roots": [cdir], "search": config_mod.default_search()}]
cfg_ce["active_scope"] = "CE"
guard_ce = Guard(config_mod.all_roots(cfg_ce), config_mod.audit_path())
conn_ce = indexer.connect(config_mod.db_path())
indexer.init_db(conn_ce)
indexer.sync_index(conn_ce, cfg_ce, guard_ce)
roots_ce = config_mod.active_roots(cfg_ce)
hits_all = search.search(conn_ce, "同盟玩法", roots=roots_ce, content=True)
check("content=true 命中文件名+正文",
      {h["name"] for h in hits_all} == {"同盟玩法.md", "普通.md", "同盟玩法.txt"},
      [h["name"] for h in hits_all])
hits_name = search.search(conn_ce, "同盟玩法", roots=roots_ce, content=False)
check("content=false 只命中文件名",
      {h["name"] for h in hits_name} == {"同盟玩法.md", "同盟玩法.txt"},
      [h["name"] for h in hits_name])
hits_ext = search.search(conn_ce, "同盟玩法", roots=roots_ce, content=False,
                         ext_filter=[".txt"])
check("ext_filter 与 content=false 叠加",
      [h["name"] for h in hits_ext] == ["同盟玩法.txt"],
      [h["name"] for h in hits_ext])
conn_ce.close()

use_home("matchmodes")
mdir = os.path.join(SANDBOX, "matchmodes")
os.makedirs(mdir, exist_ok=True)
for mname, mbody in [
    ("m_all.md", "同盟系统与玩法设计。\n"),
    ("m_phrase.md", "同盟玩法完整出现。\n"),
    ("m_any.md", "只有同盟两个字。\n"),
]:
    with open(os.path.join(mdir, mname), "w", encoding="utf-8") as fh:
        fh.write(mbody)
cfg_mm = config_mod.default_config()
cfg_mm["scopes"] = [{"name": "MM", "roots": [mdir], "search": config_mod.default_search()}]
cfg_mm["active_scope"] = "MM"
guard_mm = Guard(config_mod.all_roots(cfg_mm), config_mod.audit_path())
conn_mm = indexer.connect(config_mod.db_path())
indexer.init_db(conn_mm)
indexer.sync_index(conn_mm, cfg_mm, guard_mm)
roots_mm = config_mod.active_roots(cfg_mm)
h_phrase = search.search(conn_mm, "同盟 玩法", roots=roots_mm, match="phrase")
h_all = search.search(conn_mm, "同盟 玩法", roots=roots_mm, match="all")
h_any = search.search(conn_mm, "同盟 玩法", roots=roots_mm, match="any")
check("phrase 只命中连续短语",
      {h["name"] for h in h_phrase} == {"m_phrase.md"}, [h["name"] for h in h_phrase])
check("all 命中同时含两词",
      {h["name"] for h in h_all} == {"m_all.md", "m_phrase.md"}, [h["name"] for h in h_all])
check("any 命中任一词",
      {h["name"] for h in h_any} == {"m_all.md", "m_phrase.md", "m_any.md"},
      [h["name"] for h in h_any])
check("三种匹配模式结果确实不同",
      len({frozenset(h["name"] for h in x) for x in (h_phrase, h_all, h_any)}) == 3)
conn_mm.close()


# ===========================================================================
print("\n[5e] 文件名分组与质量门槛")
# ===========================================================================
use_home("t08")
tdir = os.path.join(SANDBOX, "t08")
os.makedirs(tdir, exist_ok=True)
for tname, tbody in [
    ("三谋-SLG同盟玩法分析.md", "普通正文。\n"),
    ("同盟与玩法对比.md", "普通正文。\n"),
    ("正文精确命中.md", "同盟玩法在正文里。\n"),
    ("同盟玩法完整.md", "同盟玩法也在正文里。\n"),
]:
    with open(os.path.join(tdir, tname), "w", encoding="utf-8") as fh:
        fh.write(tbody)
cfg_t = config_mod.default_config()
cfg_t["scopes"] = [{"name": "T8", "roots": [tdir], "search": config_mod.default_search()}]
cfg_t["active_scope"] = "T8"
guard_t = Guard(config_mod.all_roots(cfg_t), config_mod.audit_path())
conn_t = indexer.connect(config_mod.db_path())
indexer.init_db(conn_t)
indexer.sync_index(conn_t, cfg_t, guard_t)
hits_t = search.search(conn_t, "同盟 玩法", roots=config_mod.active_roots(cfg_t),
                       match="any", limit=20)
by_name = {h["name"]: h for h in hits_t}
order = [h["name"] for h in hits_t]
check("正例：文件名整体命中进文件名段",
      by_name.get("三谋-SLG同盟玩法分析.md", {}).get("group") == "name", order)
check("反例：文件名零散字符不进文件名段",
      by_name.get("同盟与玩法对比.md", {}).get("group") == "content", order)
check("内容精确命中排在文件名零散命中之前",
      order.index("正文精确命中.md") < order.index("同盟与玩法对比.md"), order)
check("文件名+内容都命中标注内容也命中",
      by_name.get("同盟玩法完整.md", {}).get("content_also") is True, order)
check("同一文件不重复出现", len(order) == len(set(order)), order)
name_count = sum(1 for h in hits_t if h.get("group") == "name")
check("文件名段整体排在最前",
      all(h.get("group") == "name" for h in hits_t[:name_count]), order)
conn_t.close()


# ===========================================================================
print("\n[6] 安全边界")
# ===========================================================================
violated = False
try:
    guard.require_in_scope(os.path.join(tempfile.gettempdir(), "outside.txt"))
except ScopeViolation:
    violated = True
check("越界路径被拦截", violated)

try:
    guard.open_source(os.path.join(DOCS_DIR, "简历-销售岗.md"), "w")
    check("写模式被拒绝", False)
except ValueError:
    check("写模式被拒绝", True)

after_bytes = {}
for _base, _dirs, _files in os.walk(DOCS_DIR):
    for _name in _files:
        _full = os.path.join(_base, _name)
        with open(_full, "rb") as _fh:
            after_bytes[_full] = _fh.read()
check("源文件全程未被改动", before_bytes == after_bytes)

existing = os.path.join(DOCS_DIR, "简历-销售岗.md")
check("free_path 不覆盖已有文件", guard.free_path(existing) != existing)


# ===========================================================================
print("\n[7] 取词")
# ===========================================================================
words = keyword.keywords_from_text(
    "帮我看看异环的开放世界载具系统是怎么设计的，顺便对比一下三谋的同盟玩法")
print("  keywords:", words)
check("抽到有意义的词", any("异环" in w or "同盟" in w for w in words), words)
check("滤掉功能词", not any(w in ("帮我", "看看", "怎么") for w in words), words)


# ===========================================================================
print("\n[8] 索引库重建")
# ===========================================================================
conn.close()
use_home("basic")
backup = indexer.reset_db(config_mod.db_path())
check("重建索引库产生备份", bool(backup) and os.path.exists(backup), backup)
check("重建后原库已让位", not os.path.exists(config_mod.db_path()))
conn = indexer.connect(config_mod.db_path())
indexer.init_db(conn)
check("重建后可正常建库", indexer.stats(conn)["total"] == 0)
conn.close()

shutil.rmtree(SANDBOX, ignore_errors=True)

print("\n" + "=" * 52)
if FAILURES:
    print("失败 %d 项：%s" % (len(FAILURES), ", ".join(FAILURES)))
    sys.exit(1)
print("ALL CORE CHECKS PASSED")
