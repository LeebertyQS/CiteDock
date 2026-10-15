# -*- coding: utf-8 -*-
"""系统托盘与 Windows 全局热键。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon
from ..i18n import t
from .. import i18n

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

VK_SPECIAL = {
    "SPACE": 0x20, "ENTER": 0x0D, "RETURN": 0x0D, "ESC": 0x1B, "ESCAPE": 0x1B,
    "TAB": 0x09, "BACKSPACE": 0x08, "DELETE": 0x2E, "DEL": 0x2E,
    "INSERT": 0x2D, "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21,
    "PAGEDOWN": 0x22, "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC,
    ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
}


def parse_hotkey(sequence):
    """'Ctrl+Alt+Space' -> (modifiers, virtual_key)；无法解析时返回 None。"""
    modifiers = 0
    virtual = None
    for raw in str(sequence or "").split("+"):
        key = raw.strip().upper()
        if not key:
            continue
        if key in ("CTRL", "CONTROL"):
            modifiers |= MOD_CONTROL
        elif key == "ALT":
            modifiers |= MOD_ALT
        elif key == "SHIFT":
            modifiers |= MOD_SHIFT
        elif key in ("WIN", "META", "SUPER"):
            modifiers |= MOD_WIN
        elif len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
            virtual = ord(key)
        elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
            virtual = 0x70 + int(key[1:]) - 1
        elif key in VK_SPECIAL:
            virtual = VK_SPECIAL[key]
    if virtual is None or modifiers == 0:
        return None
    return modifiers, virtual


class GlobalHotkey(QAbstractNativeEventFilter):
    """用 RegisterHotKey + 原生事件过滤器实现系统级热键，不依赖第三方库。

    每个实例占用一个独立的 hotkey id，所以可以并存多个（唤起坞 / 检索选区）。
    """

    _NEXT_ID = 0xC1DE

    def __init__(self, app, callback):
        super().__init__()
        self._app = app
        self._callback = callback
        self._id = GlobalHotkey._NEXT_ID
        GlobalHotkey._NEXT_ID += 1
        self._registered = False
        self._current = ""
        app.installNativeEventFilter(self)

    @property
    def current(self):
        return self._current

    def _register_raw(self, sequence):
        parsed = parse_hotkey(sequence)
        if not parsed:
            return False
        modifiers, virtual = parsed
        try:
            ok = ctypes.windll.user32.RegisterHotKey(
                None, self._id, modifiers | MOD_NOREPEAT, virtual
            )
        except (OSError, AttributeError):
            return False
        if not ok:
            return False
        self._registered = True
        self._current = str(sequence)
        return True

    def _unregister_raw(self):
        if not self._registered:
            return
        try:
            ctypes.windll.user32.UnregisterHotKey(None, self._id)
        except (OSError, AttributeError):
            pass
        self._registered = False

    def register(self, sequence):
        """注册热键；**失败时回滚到原来那个**。

        老版本是"先 unregister 再注册、失败就算了" —— 结果用户把热键改成一个
        被占用的组合，原来能用的那个也一起丢了。现在有唤起 + 检索两个热键，更不能这样。
        """
        if parse_hotkey(sequence) is None:
            return False
        previous = self._current
        self._unregister_raw()
        if self._register_raw(sequence):
            return True
        if previous and self._register_raw(previous):
            return False          # 明确返回失败，但旧组合已经装回去了
        self._current = ""
        return False

    def unregister(self):
        self._unregister_raw()
        self._current = ""

    def nativeEventFilter(self, event_type, message):
        try:
            kind = bytes(event_type)
        except (TypeError, ValueError):
            kind = str(event_type)
        if kind not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False
        try:
            address = message if isinstance(message, int) else int(message)
            msg = wintypes.MSG.from_address(address)
        except (TypeError, ValueError, OSError):
            return False
        if msg.message == WM_HOTKEY and int(msg.wParam) == self._id:
            self._callback()
            return True
        return False


def build_icon(theme="dark", healthy=True):
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    if not healthy:
        base = "#E0A33E"
    else:
        base = "#3D7EF0" if str(theme).lower() != "light" else "#2F6FE0"
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(base))
    painter.drawRoundedRect(QRectF(3, 3, 58, 58), 15, 15)

    pen = QPen(QColor("#FFFFFF"))
    pen.setWidthF(5.2)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(28, 28), 11.5, 11.5)
    painter.drawLine(QPointF(36.5, 36.5), QPointF(47, 47))
    painter.end()
    return QIcon(pixmap)


class DockTray(QSystemTrayIcon):
    def __init__(self, parent, on_toggle, on_settings, on_reindex, on_quit, theme="dark"):
        super().__init__(build_icon(theme), parent)
        self._theme = theme
        self.setToolTip(t("CiteDock 引用坞"))

        menu = QMenu()
        self._menu = menu
        self.act_toggle = QAction(t("显示 / 隐藏悬浮坞"), menu)
        self.act_settings = QAction(t("设置…"), menu)
        self.act_reindex = QAction(t("重建索引"), menu)
        self.act_quit = QAction(t("退出 CiteDock"), menu)
        self.act_toggle.triggered.connect(on_toggle)
        self.act_settings.triggered.connect(on_settings)
        self.act_reindex.triggered.connect(on_reindex)
        self.act_quit.triggered.connect(on_quit)
        menu.addAction(self.act_toggle)
        menu.addSeparator()
        menu.addAction(self.act_settings)
        menu.addAction(self.act_reindex)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def retranslate(self):
        """切换语言后刷新托盘菜单与提示。"""
        i18n.refresh(self, (QAction,))
        self.setToolTip(t("CiteDock 引用坞"))

    def set_health(self, healthy):
        self.setIcon(build_icon(self._theme, healthy=healthy))
        self.setToolTip(
            t("CiteDock 引用坞") if healthy
            else t("CiteDock 引用坞 —— 全局钩子异常，正在尝试恢复")
        )

    def _on_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.act_toggle.trigger()
