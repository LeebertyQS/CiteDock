# -*- coding: utf-8 -*-
"""界面配色与样式表。深色 / 浅色两套，悬浮坞默认深色。"""
from __future__ import annotations

import sys

DARK = {
    "card_bg": "rgba(30, 32, 36, 242)",
    "card_border": "rgba(255, 255, 255, 30)",
    "text": "#E8E8EA",
    "text_dim": "#9C9CA6",
    "text_faint": "#70707A",
    "input_bg": "rgba(255, 255, 255, 16)",
    "input_border": "rgba(255, 255, 255, 34)",
    "input_focus": "#4C8DF6",
    "btn_bg": "rgba(255, 255, 255, 16)",
    "btn_bg_hover": "rgba(255, 255, 255, 36)",
    "btn_border": "rgba(255, 255, 255, 26)",
    "btn_text": "#D8D8DC",
    "accent": "#3D7EF0",
    "accent_text": "#FFFFFF",
    "row_hover": "rgba(255, 255, 255, 16)",
    "row_sel": "rgba(76, 141, 246, 46)",
    "hl_bg": "#7A5D00",
    "hl_fg": "#FFE9A8",
    "scroll": "rgba(255, 255, 255, 44)",
    "divider": "rgba(255, 255, 255, 24)",
    "warn": "#E0A33E",
}

LIGHT = {
    "card_bg": "rgba(252, 252, 253, 250)",
    "card_border": "rgba(0, 0, 0, 32)",
    "text": "#1E1E20",
    "text_dim": "#6B6B73",
    "text_faint": "#6E6E76",
    "input_bg": "#FFFFFF",
    "input_border": "rgba(0, 0, 0, 46)",
    "input_focus": "#2F6FE0",
    "btn_bg": "rgba(0, 0, 0, 10)",
    "btn_bg_hover": "rgba(0, 0, 0, 24)",
    "btn_border": "rgba(0, 0, 0, 28)",
    "btn_text": "#33333A",
    "accent": "#2F6FE0",
    "accent_text": "#FFFFFF",
    "row_hover": "rgba(0, 0, 0, 12)",
    "row_sel": "rgba(47, 111, 224, 34)",
    "hl_bg": "#FFE58F",
    "hl_fg": "#6B4B00",
    "scroll": "rgba(0, 0, 0, 64)",
    "divider": "rgba(0, 0, 0, 26)",
    "warn": "#B4741A",
}

FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif'

PANEL_WIDTH = 700
# 上限：英文文案比中文宽一截，面板宽度要能跟着长，但不能无限长到超出屏幕
PANEL_WIDTH_MAX = 920
BAR_HEIGHT = 56


def detect_system_theme() -> str:
    """跟随系统主题。Windows 读注册表 AppsUseLightTheme，其它平台回退深色。"""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if value else "dark"
        except Exception:
            pass
    return "dark"


def resolve_theme(theme) -> str:
    name = str(theme or "").strip().lower()
    if name in ("auto", "system", "跟随系统", "follow system"):
        return detect_system_theme()
    return "light" if name == "light" else "dark"


def palette(theme):
    return LIGHT if resolve_theme(theme) == "light" else DARK


def window_color(theme):
    """顶层窗口的**不透明**底色。

    `card_bg` 带 alpha，做窗口底色时系统深色会从底下透出来 ——
    表现就是"切成浅色了，可这个窗口还是黑的"。
    所以单独给一个实色，写进 QPalette.Window（比 QSS 的 `QDialog { background }` 可靠）。
    """
    return "#FCFCFD" if resolve_theme(theme) == "light" else "#1E2024"


def build_qss(theme, extra=""):
    c = palette(theme)
    opaque = window_color(theme)
    return f"""
* {{
    font-family: {FONT_FAMILY};
    outline: none;
}}
QWidget#card {{
    background: {c['card_bg']};
    border: 1px solid {c['card_border']};
    border-radius: 12px;
}}
QWidget#selbar {{
    background: {opaque};
    border: 1px solid {c['input_focus']};
    border-radius: 10px;
}}
QWidget#selbar QPushButton {{
    color: {c['text']};
    background: {c['btn_bg_hover']};
    border: 1px solid {c['btn_border']};
}}
QWidget#selbar QLabel#faint {{ color: {c['text_dim']}; }}
QLabel {{ color: {c['text']}; background: transparent; }}
QLabel#dim {{ color: {c['text_dim']}; }}
QLabel#faint {{ color: {c['text_faint']}; }}
QLabel#name {{ color: {c['text']}; font-size: 13px; font-weight: 500; }}
QLabel#snip {{ color: {c['text_dim']}; font-size: 12px; }}
QLabel#grip {{ color: {c['text_faint']}; font-size: 13px; }}
QLabel#stat {{ color: {c['text_faint']}; font-size: 11px; }}

QLineEdit {{
    background: {c['input_bg']};
    border: 1px solid {c['input_border']};
    border-radius: 8px;
    color: {c['text']};
    padding: 6px 10px;
    font-size: 14px;
    selection-background-color: {c['accent']};
    selection-color: {c['accent_text']};
}}
QLineEdit:focus {{ border: 1px solid {c['input_focus']}; }}

QPushButton {{
    background: {c['btn_bg']};
    border: 1px solid {c['btn_border']};
    border-radius: 7px;
    color: {c['btn_text']};
    padding: 5px 10px;
    font-size: 12px;
}}
QPushButton:hover {{ background: {c['btn_bg_hover']}; }}
QPushButton:pressed {{ background: {c['row_sel']}; }}
QPushButton:disabled {{ color: {c['text_faint']}; background: transparent; }}
QPushButton:checked {{
    background: {c['accent']};
    border: 1px solid {c['accent']};
    color: {c['accent_text']};
}}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; }}
QPushButton#ghost:hover {{ background: {c['btn_bg_hover']}; }}
QPushButton#primary {{
    background: {c['accent']};
    border: 1px solid {c['accent']};
    color: {c['accent_text']};
    font-weight: 500;
}}

QListWidget {{
    background: transparent;
    border: none;
    color: {c['text']};
}}
QListWidget::item {{ border: none; padding: 0px; }}
QListWidget::item:hover {{ background: {c['row_hover']}; }}
QListWidget::item:selected {{ background: {c['row_sel']}; }}

QFrame#divider {{ background: {c['divider']}; border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px 2px 2px 0px;
}}
QScrollBar::handle:vertical {{
    background: {c['scroll']}; border-radius: 4px; min-height: 28px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QCheckBox {{ spacing: 0px; color: {c['text']}; }}
QCheckBox:disabled {{ color: {c['text_faint']}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px;
    border: 1px solid {c['btn_border']}; background: {c['input_bg']}; }}
QCheckBox::indicator:checked {{
    background: {c['accent']}; border: 1px solid {c['accent']};
}}

QDialog {{ background: {c['card_bg']}; color: {c['text']}; }}
QScrollArea, QScrollArea > QWidget#qt_scrollarea_viewport {{
    background: transparent; border: none;
}}
QListWidget#plain {{ background: {c['input_bg']}; border: 1px solid {c['input_border']};
    border-radius: 8px; }}
QSpinBox, QComboBox {{
    background: {c['input_bg']}; border: 1px solid {c['input_border']};
    border-radius: 6px; color: {c['text']}; padding: 4px 6px;
}}
QMenu {{ background: {c['card_bg']}; border: 1px solid {c['card_border']};
    border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 5px 18px; border-radius: 5px; color: {c['text']}; }}
QMenu::item:selected {{ background: {c['row_sel']}; }}
QToolTip {{
    background: {c['card_bg']}; color: {c['text']};
    border: 1px solid {c['card_border']}; padding: 4px 6px;
}}
{extra}
"""
