# -*- coding: utf-8 -*-
"""CiteDock 引用坞 —— 本地、离线的文件检索小坞。

用法：
    python run.py             启动悬浮坞
    python run.py --selftest  仅做启动自检（构建窗口后立即退出）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SUPPORTED_PLATFORM = "win32"

# 说明：app/ui/mousehook.py 与 app/ui/tray.py 依赖 Win32 API
# （ctypes.windll / RegisterHotKey / WH_MOUSE_LL），而 app/main.py **无条件** import 它们。
# 所以在非 Windows 上，程序会崩在很深的某个帧里抛
# `AttributeError: module 'ctypes' has no attribute 'windll'` —— 完全看不出是平台问题。
# 检测必须放在**任何 app.* 导入之前**。
UNSUPPORTED_HINT = """CiteDock 目前只支持 Windows。

当前系统：%s

为什么：全局热键与选区探测（Ctrl+C 注入）用的是 Win32 API，
暂时没有其它平台的实现。检索坞本体（索引 + 搜索）是纯 Python 的，
如果你希望它在别的平台上可用，欢迎提 issue。
"""


def check_platform():
    """非 Windows 给人话后退出，返回 True 表示可以继续。"""
    if sys.platform == SUPPORTED_PLATFORM:
        return True
    message = UNSUPPORTED_HINT % sys.platform
    print(message, file=sys.stderr)
    # 双击启动时没有控制台，所以要弹窗 ——
    # 用标准库的 tkinter（有就用，没有就算了），不为这一句提示引入新依赖
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("CiteDock", message)
        root.destroy()
    except Exception:
        pass
    return False


def selftest():
    """构建完整窗口、托盘、热键与设置面板，确认没有运行期错误后立即退出。"""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from app.core import config as config_mod
    from app.core.safeguard import Guard
    from app.ui.float_bar import DockWindow
    from app.ui.settings_panel import SettingsDialog
    from app.ui.tray import DockTray, GlobalHotkey, build_icon, parse_hotkey

    app = QApplication(sys.argv)
    cfg = config_mod.load()
    guard = Guard(config_mod.all_roots(cfg), config_mod.audit_path())

    window = DockWindow(cfg, guard)
    window.show_dock()
    window._set_expanded(True)
    window.input.setText("自检关键词")
    window._run_search()
    print("UI selftest: window=%sx%s expanded=%s" % (window.width(), window.height(), window._expanded))

    assert parse_hotkey("Ctrl+Alt+Space") == (0x0002 | 0x0001, 0x20)
    assert parse_hotkey("Ctrl+Shift+F9") and parse_hotkey("Alt+1")
    assert parse_hotkey("Space") is None, "无修饰键的裸键不应通过"
    assert parse_hotkey("Ctrl+") is None, "缺少主键不应通过"

    hotkey = GlobalHotkey(app, lambda: None)
    registered = hotkey.register(cfg.get("hotkey") or "Ctrl+Alt+Space")
    print("hotkey '%s' registered: %s" % (hotkey.current, registered))
    hotkey.unregister()

    assert not build_icon("dark").isNull()
    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = DockTray(app, lambda: None, lambda: None, lambda: None, lambda: None, "dark")
        tray.show()
        print("tray: created")
    else:
        print("tray: 系统托盘不可用（仅影响托盘入口）")

    dialog = SettingsDialog(dict(cfg))
    print("settings dialog: built, roots=%d" % dialog.roots_list.count())
    dialog.deleteLater()

    print("data dir:", config_mod.data_dir())

    def finish():
        window.stop_worker()
        if tray is not None:
            tray.hide()
        window.hide()
        app.quit()

    QTimer.singleShot(700, finish)
    app.exec()
    print("UI SELFTEST PASSED")


def smoke():
    """按真实启动路径装配一遍（窗口 + 托盘 + 热键），短暂运行后退出。"""
    from PySide6.QtCore import QTimer

    from app.main import CiteDockApp

    instance = CiteDockApp(sys.argv)
    instance.register_hotkey()
    instance.window.show_dock(expand=True)
    print("smoke: window=%sx%s" % (instance.window.width(), instance.window.height()))
    print("smoke: tray=%s hotkey=%s" % (instance.tray is not None, instance.hotkey.current))
    QTimer.singleShot(1200, instance.quit)
    code = instance.app.exec()
    print("SMOKE PASSED (exit=%s)" % code)
    return code


def main():
    if not check_platform():
        return 3
    if "--selftest" in sys.argv:
        selftest()
        return 0
    if "--smoke" in sys.argv:
        return smoke()
    from app.main import main as run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
