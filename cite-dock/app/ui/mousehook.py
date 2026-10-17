# -*- coding: utf-8 -*-
"""Windows 全局低级鼠标钩子（WH_MOUSE_LL）：只观察、永远放行。

回调里只做微秒级的事（记坐标、判断是否该跳过），其余全部丢给 Qt 主线程的信号。
钩子运行在独立线程的 PeekMessage 消息循环里；主线程用看门狗做心跳检测，发现钩子
被系统静默摘掉（例如回调超时）时自动重装。
"""
from __future__ import annotations

import ctypes
import os
import queue
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from ..i18n import t

WH_MOUSE_LL = 14
WM_RBUTTONDOWN = 0x0204
WM_QUIT = 0x0012
PM_REMOVE = 0x0001
QS_ALLINPUT = 0x04FF

CF_UNICODETEXT = 13
CF_BITMAP = 2
CF_HDROP = 15
VK_CONTROL = 0x11
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002
GMEM_MOVEABLE = 0x0002

DEFAULT_EXCLUDES = [
    "windowsterminal", "cmd", "powershell", "pwsh", "mintty", "putty",
    "conhost", "wt",
]


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MsllHookStruct(ctypes.Structure):
    _fields_ = [
        ("pt", _Point),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG), ("top", wintypes.LONG),
        ("right", wintypes.LONG), ("bottom", wintypes.LONG),
    ]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _Rect),
        ("rcWork", _Rect),
        ("dwFlags", wintypes.DWORD),
    ]


_LowLevelMouseProc = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


def _configure_ctypes():
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    msg_ptr = ctypes.POINTER(wintypes.MSG)

    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, _LowLevelMouseProc, ctypes.c_void_p, wintypes.DWORD,
    ]
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.CallNextHookEx.argtypes = [
        ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
    ]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [
        msg_ptr, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, wintypes.UINT,
    ]
    user32.TranslateMessage.argtypes = [msg_ptr]
    user32.DispatchMessageW.argtypes = [msg_ptr]

    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Rect)]
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_MonitorInfo),
    ]
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    user32.OpenInputDesktop.argtypes = [
        wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    ]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    user32.GetUserObjectInformationW.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.CloseDesktop.restype = wintypes.BOOL
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]

    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.MsgWaitForMultipleObjectsEx.restype = wintypes.DWORD
    user32.MsgWaitForMultipleObjectsEx.argtypes = [
        wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    ]
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.keybd_event.restype = None
    user32.keybd_event.argtypes = [
        wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p,
    ]

    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]


_configure_ctypes()


class MouseHook(QObject):
    right_clicked = Signal(int, int)
    health_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue()
        self._thread = None
        self._proc = None
        self._excludes = set(DEFAULT_EXCLUDES)
        self._enabled = False
        self._healthy = False
        self._lock = threading.Lock()
        self._hook_handle = 0
        self._last_callback = 0.0
        self._need_reinstall = False

        self._poll = QTimer(self)
        self._poll.setInterval(50)
        self._poll.timeout.connect(self._drain)

        self._watchdog = QTimer(self)
        self._watchdog.setInterval(2000)
        self._watchdog.timeout.connect(self._check_health)

    # ---------- 公共接口 ----------

    @property
    def enabled(self):
        return self._enabled

    @property
    def healthy(self):
        return self._healthy

    def set_excludes(self, names):
        self._excludes = {
            str(name).strip().lower()
            for name in (names or [])
            if str(name).strip()
        }

    def start(self, excludes=None):
        if self._thread is not None and self._thread.is_alive():
            return True
        if excludes is not None:
            self.set_excludes(excludes)
        self._enabled = True
        self._need_reinstall = False
        self._thread = threading.Thread(target=self._hook_loop, daemon=True)
        self._thread.start()
        self._poll.start()
        self._watchdog.start()
        return True

    def stop(self):
        self._enabled = False
        self._poll.stop()
        self._watchdog.stop()
        with self._lock:
            self._need_reinstall = False
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            try:
                thread_id = getattr(thread, "ident")
                if thread_id:
                    ctypes.windll.user32.PostThreadMessageW(
                        thread_id, WM_QUIT, 0, 0
                    )
            except Exception:
                pass
            thread.join(timeout=2.0)
        self._set_healthy(False)

    def reinstall(self):
        with self._lock:
            self._need_reinstall = True

    # ---------- 钩子线程 ----------

    def _hook_loop(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._proc = _LowLevelMouseProc(self._callback)
        self._install_hook(user32, kernel32)

        msg = wintypes.MSG()
        while not self._is_stopping():
            if self._take_reinstall():
                self._uninstall_hook(user32)
                self._install_hook(user32, kernel32)
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_QUIT:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if msg.message == WM_QUIT:
                break
            # 阻塞等待下一条消息；没有消息就最多等 100ms，再回来查一次停止/重装标志。
            # ⚠️ 绝不能用 time.sleep —— WH_MOUSE_LL 是**同步**钩子：系统把鼠标事件
            # 投递到本线程队列后**等它处理完才继续**。sleep 期间事件卡在队列里，
            # 整个系统的鼠标都会被拖慢（表现就是"鼠标移动延迟漂移"）。
            user32.MsgWaitForMultipleObjectsEx(0, None, 100, QS_ALLINPUT, 0)

        self._uninstall_hook(user32)
        self._proc = None
        self._queue.put(("health", False))

    def _is_stopping(self):
        return self._thread is None or not self._enabled

    def _take_reinstall(self):
        with self._lock:
            flag = self._need_reinstall
            self._need_reinstall = False
            return flag

    def _install_hook(self, user32, kernel32):
        module = kernel32.GetModuleHandleW(None)
        handle = user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._proc, module, 0
        )
        with self._lock:
            self._hook_handle = int(handle or 0)
            self._last_callback = time.monotonic()
        self._queue.put(("health", bool(handle)))

    def _uninstall_hook(self, user32):
        with self._lock:
            handle = self._hook_handle
            self._hook_handle = 0
        if handle:
            try:
                user32.UnhookWindowsHookEx(handle)
            except Exception:
                pass

    def _callback(self, n_code, w_param, l_param):
        try:
            if n_code >= 0:
                with self._lock:
                    self._last_callback = time.monotonic()
                if w_param == WM_RBUTTONDOWN:
                    data = ctypes.cast(
                        l_param, ctypes.POINTER(_MsllHookStruct)
                    ).contents
                    if not self._should_skip():
                        self._queue.put(("right", data.pt.x, data.pt.y))
        except Exception:
            pass
        return ctypes.windll.user32.CallNextHookEx(
            None, n_code, w_param, l_param
        )

    # ---------- 过滤判定（只在右键时做，避免拖慢回调）----------

    def _should_skip(self):
        if self._is_own_window():
            return True
        if self._foreground_process_name() in self._excludes:
            return True
        if self._is_fullscreen():
            return True
        if not self._on_default_desktop():
            return True
        return False

    def _is_own_window(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return False
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(
                hwnd, ctypes.byref(pid)
            )
            return int(pid.value) == os.getpid()
        except Exception:
            return False

    def _foreground_process_name(self):
        return foreground_process_name()

    def _is_fullscreen(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return False
            rect = _Rect()
            if not ctypes.windll.user32.GetWindowRect(
                hwnd, ctypes.byref(rect)
            ):
                return False
            monitor = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(_MonitorInfo)
            if not ctypes.windll.user32.GetMonitorInfoW(
                monitor, ctypes.byref(info)
            ):
                return False
            area = info.rcMonitor
            return (
                rect.left <= area.left and rect.top <= area.top
                and rect.right >= area.right and rect.bottom >= area.bottom
            )
        except Exception:
            return False

    def _on_default_desktop(self):
        try:
            desktop = ctypes.windll.user32.OpenInputDesktop(
                0, False, 0x0100
            )
            if not desktop:
                return False
            try:
                buf = ctypes.create_unicode_buffer(64)
                needed = wintypes.DWORD()
                ok = ctypes.windll.user32.GetUserObjectInformationW(
                    desktop, 2, buf, ctypes.sizeof(buf), ctypes.byref(needed)
                )
                return bool(ok) and buf.value.lower() == "default"
            finally:
                ctypes.windll.user32.CloseDesktop(desktop)
        except Exception:
            return True

    # ---------- Qt 主线程侧 ----------

    def _drain(self):
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "right":
                self.right_clicked.emit(item[1], item[2])
            elif kind == "health":
                self._set_healthy(bool(item[1]))

    def _set_healthy(self, value):
        value = bool(value)
        if value != self._healthy:
            self._healthy = value
            self.health_changed.emit(value)

    def _check_health(self):
        if not self._enabled:
            return
        with self._lock:
            last = self._last_callback
        alive = self._thread is not None and self._thread.is_alive()
        stale = (time.monotonic() - last) > 10.0
        if not alive or stale:
            self._set_healthy(False)
            self.reinstall()


# ---------- 剪贴板探测（T10） ----------

def _clipboard_sequence():
    return int(ctypes.windll.user32.GetClipboardSequenceNumber() or 0)


def _clipboard_has_non_text():
    user32 = ctypes.windll.user32
    if not user32.OpenClipboard(None):
        return True
    try:
        return bool(
            user32.IsClipboardFormatAvailable(CF_BITMAP)
            or user32.IsClipboardFormatAvailable(CF_HDROP)
        )
    finally:
        user32.CloseClipboard()


def _clipboard_text():
    """读取剪贴板文本；打不开剪贴板时返回 None，没有文本时返回空串。"""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        return None
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _set_clipboard_text(text):
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        return
    try:
        user32.EmptyClipboard()
        data = (text or "").encode("utf-16-le") + b"\x00\x00"
        mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not mem:
            return
        ptr = kernel32.GlobalLock(mem)
        if ptr:
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(mem)
        user32.SetClipboardData(CF_UNICODETEXT, mem)
    finally:
        user32.CloseClipboard()


def _send_ctrl_c():
    user32 = ctypes.windll.user32
    user32.keybd_event(VK_CONTROL, 0, 0, None)
    user32.keybd_event(VK_C, 0, 0, None)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, None)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, None)


class SelectionProbe(QThread):
    detected = Signal(int, int, str)
    # 没拿到选区时也发一次，带上原因 —— 否则用户不知道是坏了还是没选中
    nothing = Signal(str)

    def __init__(self, x, y, wait_ms=120, parent=None):
        super().__init__(parent)
        self._x = int(x)
        self._y = int(y)
        self._wait_ms = int(wait_ms)
        self._reason = ""

    def run(self):
        text = self._probe()
        if text:
            self.detected.emit(self._x, self._y, text)
        else:
            self.nothing.emit(self._reason)

    def _probe(self):
        # 剪贴板里可能本来是图片/文件。不在本线程做文本备份还原（那会丢图）——
        # 全格式的备份/还原由主线程用 QMimeData 克隆完成（见 dock_window）。
        seq_before = _clipboard_sequence()
        _send_ctrl_c()
        time.sleep(self._wait_ms / 1000.0)
        text = _clipboard_text()
        seq_after = _clipboard_sequence()
        if seq_after == seq_before:
            self._reason = t("这个程序没有响应 Ctrl+C，读不到选区（也可能你没选中文字）")
            return ""
        if not text:
            self._reason = t("没有检测到选中的文字")
            return ""
        if len(text) > 5000:
            self._reason = t("选中的内容超过 5000 字符，已跳过（可能是不小心全选了）")
            return ""
        return text.strip()


def foreground_process_name():
    """当前前台窗口的进程名（小写，含 .exe）。

    热键路径也要用它做"终端排除" —— Ctrl+C 在终端里是中断信号，绝不能注入。
    所以抽到模块级，让钩子路径与热键路径共用同一份判定，避免两边行为漂移。
    """
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid.value))
        if not process:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wintypes.DWORD(512)
            ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
                process, 0, buf, ctypes.byref(size)
            )
            if not ok:
                return ""
            return os.path.basename(buf.value).lower()
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    except Exception:
        return ""


def is_excluded(excludes):
    """当前前台进程是否在排除列表里。"""
    name = foreground_process_name()
    if not name:
        return False
    wanted = {str(item).strip().lower() for item in (excludes or []) if str(item).strip()}
    if name in wanted:
        return True
    stem = name[:-4] if name.endswith(".exe") else name
    return stem in wanted
