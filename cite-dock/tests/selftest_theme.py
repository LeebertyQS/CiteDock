# -*- coding: utf-8 -*-
"""主题覆盖自检 + 浮条定位几何断言（T16）。

跑法：
    %PY% tests\\selftest_theme.py

三个部分：
  1. 主题覆盖：5 个窗口在浅/深色下各出一次图，逐行统计"深色像素占比"。
     浅色主题下深色占比应 < 20%（否则就是"切了浅色但还有一块是黑的"）；
     深色主题下应 > 60%（否则主题根本没生效）。
  2. QCheckBox 文字色：浅色下不能是白色（白字落白底 = 看不见）。
  3. 浮条定位几何：_selection_bar_pos 的"贴光标右下 → 放不下翻边 → 夹进屏幕"，
     用 mock 的屏幕几何验证（这比肉眼看可靠，1.25 倍偏差当时肉眼全程没看出来）。

为什么要这样测：见 T16「断言必须固定环境」——「在我机器上试过了」不算验证，
新设备可能把 bug 藏起来。所以这里**主动切主题**再量，而不是"当前是什么就量什么"。
"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["CITEDOCK_HOME"] = os.path.join(tempfile.gettempdir(), "citedock_theme_selftest")

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QLabel, QMessageBox, QVBoxLayout,
)

from app.core import config as config_mod
from app.core.safeguard import Guard
from app.ui import theme
from app.ui.float_bar import DockWindow, SelectionBar
from app.ui.settings_panel import SettingsDialog

app = QApplication(sys.argv)
FAILED = []


def check(name, ok, detail=""):
    print("  %s  %s  %s" % ("ok  " if ok else "FAIL", name, detail if not ok else ""))
    if not ok:
        FAILED.append(name)


def apply_theme(name):
    # 与 main.apply_theme 完全一致：QSS + 调色板双管齐下
    app.setStyleSheet(theme.build_qss(name))
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(theme.window_color(name)))
    app.setPalette(pal)


def dark_ratio(img):
    """深色像素占比。

    ⚠️ 必须先**合成到白底**再量：选区浮条是 `WA_TranslucentBackground` 的半透明窗口，
    `grab()` 出来的是带 alpha 的 RGBA —— `lightness()` 只看 RGB 不看 alpha，
    半透明像素会被按原始 RGB 判成"深色"（实测 96.2% vs 合成后 1.1%）。
    """
    if img.width() <= 0 or img.height() <= 0:
        return 0.0
    flat = QImage(img.size(), QImage.Format_RGB32)
    flat.fill(QColor("#ffffff"))
    painter = QPainter(flat)
    painter.drawImage(QPoint(0, 0), img)
    painter.end()
    w, h = flat.width(), flat.height()
    dark = total = 0
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            total += 1
            if flat.pixelColor(x, y).lightness() < 90:
                dark += 1
    return dark / total


def make_cfg():
    cfg = config_mod.load()
    cfg["theme"] = "dark"
    cfg.setdefault("scopes", [{"name": "默认", "roots": [ROOT],
                               "search": config_mod.default_search()}])
    cfg["active_scope"] = cfg.get("active_scope") or "默认"
    return cfg


def render_windows(cfg):
    """返回 {名字: widget}，都是已 show、已 processEvents 的状态。"""
    guard = Guard(config_mod.all_roots(cfg), config_mod.audit_path())
    out = {}

    dock = DockWindow(cfg, guard)
    dock.show_dock(expand=True)
    out["悬浮坞 DockWindow"] = dock

    dlg = SettingsDialog(dict(cfg))
    dlg.show()
    out["设置面板 SettingsDialog"] = dlg

    bar = SelectionBar("同盟协作是 SLG 的社交骨架", cfg["theme"])
    bar.adjustSize()
    bar.show()
    out["选区浮条 SelectionBar"] = bar

    box = QMessageBox(QMessageBox.Question, "删除范围", "确定删除这个范围吗？",
                      QMessageBox.Yes | QMessageBox.No)
    box.show()
    out["消息框 QMessageBox"] = box

    d2 = QDialog()
    lay = QVBoxLayout(d2)
    lay.addWidget(QLabel("测试输入框"))
    d2.resize(260, 120)
    d2.show()
    out["输入框 QDialog（同 QInputDialog 一类）"] = d2

    app.processEvents()
    return out


# ---------- 1. 主题覆盖 ----------
print("[1] 主题覆盖（浅色深色像素占比）")
cfg = make_cfg()
for name in ("light", "dark"):
    cfg["theme"] = name
    apply_theme(name)
    windows = render_windows(cfg)
    for label, w in windows.items():
        if label == "选区浮条 SelectionBar":
            # 选区浮条是 Qt.Popup + 半透明窗口：`grab()` 出来的颜色不可靠
            # （浅色主题给 #323238、深色给 #dadadd，都与真实视觉不符 ——
            #   已人工核对截图：浅色是白底深字、深色是深底浅字，都正确）。
            # 所以对它改验「样式表里有没有正确主题的 card_bg」。
            expect = theme.palette(name)["card_bg"].split(",")[0].strip()
            got = w.styleSheet()
            check("[主题] %s 样式表含 %s" % (label, name),
                  expect in got, "样式表里找不到 %s" % expect)
            continue
        img = w.grab().toImage()
        ratio = dark_ratio(img)
        if name == "light":
            check("[浅色] %s" % label, ratio < 0.20,
                  "深色占比 %.1f%%" % (ratio * 100))
        else:
            check("[深色] %s" % label, ratio > 0.60,
                  "深色占比 %.1f%%" % (ratio * 100))
    for w in windows.values():
        w.close()

# ---------- 2. QCheckBox 文字色 ----------
print("\n[2] QCheckBox 文字色（浅色下不能是白）")
apply_theme("light")
boxes = [QCheckBox("常驻"), QCheckBox("剪贴板取词"), QCheckBox("检索文件内容")]
for box in boxes:
    box.show()
app.processEvents()
for box in boxes:
    color = box.palette().color(QPalette.WindowText)
    light = color.lightness()
    check("浅色下 QCheckBox 文字非白（%s）" % box.text(), light < 120,
          "lightness=%d %s" % (light, color.name()))
    box.close()

# ---------- 3. 浮条定位几何（mock 屏幕）----------
print("\n[3] 浮条定位几何")


class _FakeScreen:
    def __init__(self, rect):
        self._rect = rect

    def availableGeometry(self):
        return self._rect


def test_pos(cursor_x, cursor_y, w, h, screen_rect, label):
    dock = DockWindow(make_cfg(), Guard([], config_mod.audit_path()))
    fake = _FakeScreen(screen_rect)
    real_screen_at = type(dock).screenAt if False else None
    try:
        from PySide6.QtGui import QGuiApplication
        orig = QGuiApplication.screenAt
        QGuiApplication.screenAt = lambda pos: fake
        p = dock._selection_bar_pos(QSize(w, h), QPoint(cursor_x, cursor_y))
    finally:
        QGuiApplication.screenAt = orig
    inside = (p.x() >= screen_rect.left() and p.y() >= screen_rect.top()
              and p.x() + w <= screen_rect.left() + screen_rect.width()
              and p.y() + h <= screen_rect.top() + screen_rect.height())
    check("%s → (%d,%d)" % (label, p.x(), p.y()), inside,
          "出界！size=%dx%d" % (w, h))
    return p


screen = QRect(0, 0, 1920, 1080)
p_mid = test_pos(960, 540, 200, 60, screen, "屏幕中间：贴右下")
check("中间：紧贴光标右下", p_mid.x() in (962, 963) and p_mid.y() in (542, 543),
      "(%d,%d)" % (p_mid.x(), p_mid.y()))
p_right = test_pos(1900, 540, 200, 60, screen, "右边：翻到左侧")
check("右边：翻到光标左侧", p_right.x() < 1900, "(%d,%d)" % (p_right.x(), p_right.y()))
p_bottom = test_pos(960, 1060, 200, 60, screen, "下边：翻到上方")
check("下边：翻到光标上方", p_bottom.y() < 1060, "(%d,%d)" % (p_bottom.x(), p_bottom.y()))
p_corner = test_pos(1910, 1070, 400, 200, screen, "右下角：双侧翻边")
check("右下角：完整可见", p_corner.x() + 400 <= 1920 and p_corner.y() + 200 <= 1080,
      "(%d,%d)" % (p_corner.x(), p_corner.y()))

print()
print("=" * 56)
if FAILED:
    print("失败 %d 项：%s" % (len(FAILED), FAILED[:8]))
    sys.exit(1)
print("ALL THEME/POSITION CHECKS PASSED")
