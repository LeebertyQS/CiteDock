# -*- coding: utf-8 -*-
"""给悬浮坞造一批中文样例语料，跑真实检索并截图，用于外观与功能自查。

用法：python tests/shot.py [输出目录]
所有产物只落在 %TEMP%，不会碰用户目录里的源文件。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SANDBOX = os.path.join(tempfile.gettempdir(), "citedock_demo")
os.environ["CITEDOCK_HOME"] = os.path.join(SANDBOX, "_data")

CORPUS_DIR = os.path.join(SANDBOX, "vault")
DATA_DIR = os.path.join(SANDBOX, "_data")

SAMPLES = {
    "游戏策划/异环-开放世界设计拆解.md": (
        "# 异环 开放世界设计拆解\n\n"
        "异环的核心体验是城市探索 + 载具系统 + 二次元角色养成。\n"
        "开放世界的地图密度决定了探索节奏，载具系统承担大范围位移。\n"
        "玩法循环：探索 -> 遭遇 -> 战斗 -> 养成 -> 解锁新区域。\n"
    ),
    "游戏策划/三谋-SLG同盟玩法分析.md": (
        "# 三国谋定天下 SLG 拆解\n\n"
        "同盟协作是 SLG 的社交骨架，赛季制负责节奏重置。\n"
        "资源争夺与行军路线规划构成了中期的策略深度。\n"
        "游戏策划视角看，付费点集中在加速与武将养成。\n"
    ),
    "游戏策划/求职方向梳理.md": (
        "# 游戏策划求职方向梳理\n\n"
        "目标岗位：游戏策划（系统 / 数值 / 关卡）。\n"
        "作品集要包含玩法拆解文档、关卡草案、以及可玩的原型。\n"
        "拆解案例暂定《异环》与《三国谋定天下》。\n"
    ),
    "求职/简历-销售岗-2027届.md": (
        "# 简历\n\n"
        "目标岗位：外企销售 / 市场 / 商务管培生。\n"
        "经历：极氪汽车销售实习，负责门店线索跟进与试驾邀约。\n"
    ),
    "求职/极氪门店实习总结.md": (
        "# 极氪门店销售实习总结\n\n"
        "三个月的门店实习里，我负责到店客户的接待、试驾邀约与线索跟进。\n"
        "留资转化率从 12% 提升到 19%。\n"
    ),
    "大学/婚姻法-课程笔记.md": (
        "# 婚姻法课程笔记\n\n"
        "夫妻共同财产的认定、离婚财产分割、以及子女抚养权的判定标准。\n"
    ),
    "大学/数字媒体-课程作业.md": (
        "# 数字媒体课程作业\n\n"
        "交互叙事的分支结构设计，以及界面动效对信息层级的影响。\n"
    ),
    "法考/民法-要点速记.md": (
        "# 民法要点速记\n\n"
        "民事法律行为的效力、善意取得、诉讼时效的中断与中止。\n"
    ),
    "notes/meeting-notes.md": (
        "# Meeting notes\n\n"
        "Weekly sync about the open world prototype and the level design pipeline.\n"
        "TODO: prepare the token budget report for the agent workflow.\n"
    ),
    "游戏策划/长文档-全量记录.md": (
        "# 长文档\n\n" + "这一段用来触发正文截断标记，验证超限必须可见。\n" * 60
    ),
    "求职/待删除-旧版本.md": (
        "# 待删除的旧版本\n\n这个文件在建立索引之后会被删掉，用来验证失效结果会被标出来。\n"
    ),
}


def build_corpus():
    if os.path.isdir(SANDBOX):
        shutil.rmtree(SANDBOX)
    for relative, text in SAMPLES.items():
        target = os.path.join(CORPUS_DIR, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)
    os.makedirs(DATA_DIR, exist_ok=True)


def write_config(theme):
    import json

    config = {
        "config_version": 2,
        "scopes": [
            {"name": "默认", "roots": [CORPUS_DIR],
             "search": {"content": True, "match": "all", "ext_filter": [],
                        "limit": 60, "snippet_chars": 100}},
        ],
        "active_scope": "默认",
        "hotkey": "Ctrl+Alt+Space",
        "auto_grab_clipboard": False,
        "theme": theme,
        "pin_default": True,
        "exclude_dirs": [".git", "node_modules", "__pycache__"],
        "exclude_globs": ["*.png", "*.jpg", "*.exe", "*.zip"],
        # 调小正文上限，让"正文仅索引前半段"的标记能出现在截图里
        "max_index_chars": 300,
    }
    path = os.path.join(DATA_DIR, "config.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)


def capture(out_dir, query="游戏策划 开放世界", suffix=""):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from app.core import config as config_mod
    from app.core import indexer
    from app.core.safeguard import Guard
    from app.ui.float_bar import DockWindow

    app = QApplication.instance() or QApplication(sys.argv)
    cfg = config_mod.load()
    guard = Guard(config_mod.all_roots(cfg), config_mod.audit_path())

    conn = indexer.connect(config_mod.db_path())
    indexer.init_db(conn)
    stats = indexer.sync_index(conn, cfg, guard)
    print("indexed:", stats)
    conn.close()

    # 建完索引再删一个文件 —— 验证"文件已不存在"的失效标记确实会出现
    victim = os.path.join(CORPUS_DIR, "求职", "待删除-旧版本.md")
    if os.path.exists(victim):
        os.remove(victim)
        print("removed after indexing:", victim)

    window = DockWindow(cfg, guard)
    window.show_dock(expand=True, focus_input=False)
    window.btn_pin.setChecked(True)

    written = []

    def run_query():
        window.input.setText(query)
        window._run_search()
        QTimer.singleShot(420, shoot)

    def shoot():
        name = "citedock_%s%s.png" % (cfg.get("theme", "dark"), suffix)
        target = os.path.join(out_dir, name)
        window.grab().save(target)
        written.append(target)
        print("saved:", target, "size=%sx%s" % (window.width(), window.height()))

        compact = "citedock_%s%s_compact.png" % (cfg.get("theme", "dark"), suffix)
        compact_path = os.path.join(out_dir, compact)
        window._set_expanded(False)
        QTimer.singleShot(220, lambda: shoot_compact(compact_path))

    def shoot_compact(target):
        window.grab().save(target)
        written.append(target)
        print("saved:", target, "size=%sx%s" % (window.width(), window.height()))
        app.quit()

    QTimer.singleShot(260, run_query)
    app.exec()
    return written


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else SANDBOX
    theme = sys.argv[2] if len(sys.argv) > 2 else "dark"
    query = sys.argv[3] if len(sys.argv) > 3 else "游戏策划 开放世界"
    suffix = sys.argv[4] if len(sys.argv) > 4 else ""
    os.makedirs(out_dir, exist_ok=True)
    build_corpus()
    write_config(theme)
    shots = capture(out_dir, query=query, suffix=suffix)
    for path in shots:
        assert os.path.isfile(path) and os.path.getsize(path) > 4000, path
    print("SHOTS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
