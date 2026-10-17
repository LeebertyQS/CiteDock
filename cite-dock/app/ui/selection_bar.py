# -*- coding: utf-8 -*-
"""选区浮条：在光标处弹出，提供 检索 / 填词 / 复制 三个动作。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..i18n import t
from . import theme
from ._util import _plain


class SelectionBar(QWidget):
    """选区浮条：在光标处弹出，点别处自动消失（Qt.Popup）。"""
    search_requested = Signal(str)
    fill_requested = Signal(str)
    copy_requested = Signal(str)

    def __init__(self, text, theme_name="dark", parent=None):
        super().__init__(parent)
        self._text = text
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("selbar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)
        preview = QLabel(t("「%s」") % _plain(text, 20))
        preview.setObjectName("faint")
        layout.addWidget(preview)
        self.btn_search = QPushButton(t("用引用坞检索这段"))
        self.btn_fill = QPushButton(t("只填关键词"))
        self.btn_copy = QPushButton(t("复制这段"))
        for button in (self.btn_search, self.btn_fill, self.btn_copy):
            button.setMinimumHeight(26)
            layout.addWidget(button)
        self.btn_search.clicked.connect(
            lambda: self.search_requested.emit(self._text)
        )
        self.btn_fill.clicked.connect(
            lambda: self.fill_requested.emit(self._text)
        )
        self.btn_copy.clicked.connect(
            lambda: self.copy_requested.emit(self._text)
        )
        self.setStyleSheet(theme.build_qss(theme_name))
