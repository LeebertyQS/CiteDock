# -*- coding: utf-8 -*-
"""CiteDock 启动装配：QApplication + 悬浮坞 + 托盘 + 全局热键。"""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QSystemTrayIcon

from . import APP_TITLE, __version__
from .core import config as config_mod
from .core.safeguard import Guard
from .ui.float_bar import DockWindow
from .ui.mousehook import MouseHook
from .ui.settings_panel import SettingsDialog
from .ui.tray import DockTray, GlobalHotkey
from .ui import theme
from . import i18n
from .i18n import t


def install_offline_guard():
    """离线断言：把本进程的 socket 出口全部堵死。"""
    import socket

    def _blocked(*_args, **_kwargs):
        raise OSError(t("CiteDock 处于离线模式，已切断网络能力"))

    socket.socket = _blocked
    socket.create_connection = _blocked
    socket.create_server = _blocked
    if hasattr(socket, "socketpair"):
        socket.socketpair = _blocked


class CiteDockApp:
    def __init__(self, argv):
        self.app = QApplication(argv)
        self.app.setApplicationName("CiteDock")
        self.app.setApplicationVersion(__version__)
        self.app.setQuitOnLastWindowClosed(False)

        self.cfg = config_mod.load()
        # 语言必须在建界面之前定下来：模块级与构建期都会用到 t()
        i18n.set_language(self.cfg.get("language"))
        self._qt_translator = None
        self._apply_qt_translator()
        # 主题装到 QApplication 级（覆盖消息框等独立顶层窗口），必须在建窗口之前
        self.apply_theme()
        if self.cfg.get("offline_assert"):
            install_offline_guard()

        self.guard = Guard(
            config_mod.all_roots(self.cfg),
            config_mod.audit_path(),
            self.cfg.get("audit_enabled", True),
        )

        self.window = DockWindow(self.cfg, self.guard)
        self.window.request_settings.connect(self.open_settings)
        self.window.request_reindex.connect(self.reindex)
        self.window.request_quit.connect(self.quit)

        self.mousehook = MouseHook()
        self.mousehook.health_changed.connect(self._on_mousehook_health)
        self.mousehook.right_clicked.connect(self.window.on_global_right_click)

        self.hotkey = GlobalHotkey(self.app, self.toggle_dock)
        self.hotkey_select = GlobalHotkey(self.app, self.window.on_select_hotkey)

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = DockTray(
                self.app, self.toggle_dock, self.open_settings,
                self.reindex, self.quit, self.cfg.get("theme"),
            )
            self.tray.show()
        if self.cfg.get("mousehook_enabled"):
            self.mousehook.start(self.cfg.get("mousehook_exclude"))

    # ---------- 行为 ----------

    def toggle_dock(self):
        self.window.toggle()

    def reindex(self):
        self.window.show_dock(expand=True, focus_input=False)
        self.window.start_reindex(expand=True)

    def open_settings(self):
        self.window._suppress_hide = True
        try:
            dialog = SettingsDialog(dict(self.cfg))
            dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            accepted = dialog.exec() == QDialog.Accepted
            if dialog.rebuild_requested:
                self.cfg.update(dialog.cfg)
                config_mod.save(self.cfg)
                self.window.rebuild_db()
                return
            if accepted and dialog.saved:
                self.cfg.update(dialog.cfg)
                config_mod.save(self.cfg)
                self.guard.set_roots(config_mod.all_roots(self.cfg))
                self.window.cfg = self.cfg
                self.window.apply_theme()
                self.apply_theme()          # 主题改了要重装到 QApplication 级
                dialog.apply_theme()        # 面板自己也重套（否则要关掉重开才变）
                # 语言可能被改过：先定语言再重绘，否则重绘用的是旧语言
                i18n.set_language(self.cfg.get("language"))
                self._apply_qt_translator()
                self.window.retranslate()
                if self.tray is not None:
                    self.tray.retranslate()
                self.window.btn_pin.setChecked(bool(self.cfg.get("pin_default")))
                self.register_hotkey(notify=False)
                self._apply_mousehook()
                self.window.start_reindex(expand=True)
        finally:
            self.window._suppress_hide = False

    def _apply_mousehook(self):
        if self.cfg.get("mousehook_enabled"):
            self.mousehook.start(self.cfg.get("mousehook_exclude"))
        else:
            self.mousehook.stop()

    def _on_mousehook_health(self, healthy):
        if self.tray is None:
            return
        if self.cfg.get("mousehook_enabled"):
            self.tray.set_health(healthy)
        else:
            self.tray.set_health(True)

    def register_hotkey(self, notify=True):
        """注册两个热键：唤起坞 + 检索选中文字。

        每个**各自注册、各自回滚** —— 一个组合被别人占用，不能连带把另一个也搞丢
        （老版本是"先 unregister 再 register、失败就算了"，改坏一次就两个都没了）。
        """
        pairs = (
            ("hotkey", self.hotkey, self.cfg.get("hotkey") or "Ctrl+Alt+Space"),
            ("hotkey_select", self.hotkey_select,
             self.cfg.get("hotkey_select") or "Ctrl+Alt+D"),
        )
        failed = []
        for label, holder, sequence in pairs:
            if not holder.register(sequence):
                failed.append((label, sequence, holder.current))
        if failed and notify and self.tray is not None:
            lines = []
            for label, sequence, kept in failed:
                what = t("唤起热键") if label == "hotkey" else t("检索选中文字")
                lines.append(t("「%s」%s 注册失败（可能被其它程序占用）%s")
                             % (what, sequence,
                                (t("，已保留原来的 %s") % kept) if kept else ""))
            self.tray.showMessage(
                APP_TITLE,
                "\n".join(lines) + "\n" + t("可以在设置里换一个组合。"),
                QSystemTrayIcon.Warning,
                6000,
            )
        return not failed

    def apply_theme(self):
        """把主题装到 QApplication 级。

        消息框 / 输入框 / 托盘菜单都是**独立顶层窗口**，不会继承悬浮坞的样式表 ——
        逐个窗口套必然漏（之前就漏了 11 处，浅色模式下它们仍然是系统深色）。
        另外把窗口底色写进应用调色板：QSS 的 `QDialog { background }` 对独立顶层窗口
        不总被绘制，系统深色会透出来。
        """
        name = self.cfg.get("theme")
        self.app.setStyleSheet(theme.build_qss(name))
        pal = self.app.palette()
        pal.setColor(QPalette.Window, QColor(theme.window_color(name)))
        self.app.setPalette(pal)

    def _apply_qt_translator(self):
        """中文界面下给 Qt 自绘控件（QMessageBox 的 Yes/No 按钮等）装中文翻译。

        PySide6 默认不装 Qt 自带翻译，所以中文界面里 QMessageBox 的按钮
        仍然是英文（正文却是中文）—— 混搭很别扭。语言切回英文时把 translator 卸掉。
        """
        if self._qt_translator is not None:
            self.app.removeTranslator(self._qt_translator)
            self._qt_translator = None
        if i18n.current() == "zh":
            from PySide6.QtCore import QLibraryInfo, QTranslator
            translator = QTranslator(self.app)
            loaded = translator.load(
                "qt_zh_CN", QLibraryInfo.path(QLibraryInfo.TranslationsPath)
            )
            if loaded:
                self.app.installTranslator(translator)
                self._qt_translator = translator

    def quit(self):
        try:
            config_mod.save(self.cfg)
        except OSError:
            pass
        self.mousehook.stop()
        self.window.stop_worker()
        self.hotkey.unregister()
        if self.tray is not None:
            self.tray.hide()
        self.app.quit()

    def run(self):
        self.register_hotkey()
        self.window.show_dock()
        if not self.guard.has_roots():
            self.window.show_dock(expand=True, focus_input=False)
        else:
            # 增量索引很便宜，每次启动都对一遍，保证检索结果不会过期
            QTimer.singleShot(600, lambda: self.window.start_reindex(expand=False))
        return self.app.exec()


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    instance = CiteDockApp(argv)
    return instance.run()
