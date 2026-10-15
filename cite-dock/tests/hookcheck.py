# -*- coding: utf-8 -*-
"""钩子现场诊断：告诉你「右键为什么没反应」。

用法：
    %PY% tests\\hookcheck.py

跑起来后 30 秒内到你平时用的程序里右键几下，看有没有打印 [命中]。
没打印的话，它会逐条告诉你卡在哪：
  配置没开 / 钩子没装上 / 前台是本程序 / 前台在排除列表 / 全屏 / 非默认桌面

只读，不改任何配置；用的是你自己的真实配置（所以读到什么就是什么）。
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QSystemTrayIcon   # noqa: E402

from app.core import config as config_mod                     # noqa: E402
from app.ui import mousehook                                  # noqa: E402

RUN_SECONDS = 30


def main():
    app = QApplication(sys.argv)
    cfg = config_mod.load()

    print("=" * 58)
    print("CiteDock 钩子诊断")
    print("=" * 58)
    print("数据目录      :", config_mod.data_dir())

    enabled_in_cfg = bool(cfg.get("mousehook_enabled"))
    excludes = cfg.get("mousehook_exclude") or []
    print("配置里开关    :", enabled_in_cfg, "（mousehook_enabled）")
    print("排除列表      :", excludes)
    print("等待时长      :", cfg.get("mousehook_wait_ms") or 120, "ms")

    if not enabled_in_cfg:
        print()
        print(">> 配置里钩子是**关**的 —— 右键检索本来就不会触发。")
        print("   到「设置 → 全局右键检索」把开关打开，再重启。")
        return 2

    print()
    print("-" * 58)
    print("逐条检查「这次右键会不会被跳过」：")
    print("  前台进程名        :", repr(mousehook.foreground_process_name()))
    print("  is_excluded(排除) :", mousehook.is_excluded(excludes))
    print("  （上面这两条只对**你此刻点着的窗口**有效，仅供参考）")

    hook = mousehook.MouseHook()
    hits = []
    hook.right_clicked.connect(lambda x, y: hits.append((x, y)))
    hook.health_changed.connect(lambda h: print("  [健康状态变化]", h))
    hook.start(excludes)

    for _ in range(30):
        app.processEvents()
        time.sleep(0.05)

    print()
    print("钩子状态：")
    print("  enabled           :", hook.enabled)
    print("  healthy           :", hook.healthy)
    print("  句柄              :", hex(hook._hook_handle or 0),
          "（0 表示没装上）")
    print("  线程存活          :",
          hook._thread is not None and hook._thread.is_alive())
    print("  _should_skip()    :", hook._should_skip(),
          " ← True 表示**这一瞬间**会被跳过")

    if not hook._hook_handle:
        print()
        print(">> 钩子句柄是 0 —— 系统没让装上。常见原因：")
        print("   杀软/EDR 拦了全局钩子；或进程权限异常。")
        return 3

    print()
    print("-" * 58)
    print("接下来 %d 秒：请到**你平时用的程序**里（浏览器/编辑器）右键几下。" % RUN_SECONDS)
    print("每命中一次会打印一行 [命中]。没有 [命中] 就说明钩子层没看到你的右键。")
    print("提示：别在 CiteDock 自己的窗口里右键 —— 自己的窗口会被主动跳过。")
    print("-" * 58)

    deadline = time.time() + RUN_SECONDS
    last_note = 0.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
        if hits and time.time() - last_note > 1:
            print("  [命中] 右键坐标 %r   （前台：%s）"
                  % (hits[-1], mousehook.foreground_process_name()))
            last_note = time.time()

    print()
    print("=" * 58)
    print("共命中 %d 次" % len(hits))
    if hits:
        print(">> 钩子层是通的。问题在**探测层**：右键有反应但读不到选区，")
        print("   那要看状态栏弹出的原因，或调大 mousehook_wait_ms。")
    else:
        print(">> 钩子层**没看到任何右键**。请把上面的「钩子状态」贴给我。")
        print("   另外确认：你在哪个程序里右键的？它是不是以管理员身份运行？")
        print("   （管理员权限的窗口，普通权限的钩子收不到它的输入）")

    hook.stop()
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
