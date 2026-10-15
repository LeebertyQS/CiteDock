# -*- coding: utf-8 -*-
"""结果列表里的行：ResultRow（检索命中）、FileMatchRow（文件内检索命中）。"""
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..core.textutil import human_size
from ..i18n import t
from ._util import _display_dir, _plain, _snippet_html, _snippet_plain, _stamp


class FileMatchRow(QWidget):
    """文件内检索的一条命中：序号 + 原文 + 复制该段。"""
    copy_requested = Signal(str)

    def __init__(self, kind, index, text, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)
        label = {
            "text": str(index),
            "jsonl": t("第 %d 条") % index,
            "docx": t("第 %d 段") % index,
            "pdf": t("第 %d 段") % index,
        }.get(kind, str(index))
        num = QLabel(label)
        num.setObjectName("faint")
        num.setFixedWidth(64)
        num.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(num, 0, Qt.AlignTop)
        content = QLabel(text)
        content.setObjectName("snip")
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(content, 1)
        button = QPushButton(t("复制该段"))
        button.setMinimumHeight(24)
        button.clicked.connect(lambda: self.copy_requested.emit(text))
        layout.addWidget(button, 0, Qt.AlignTop)

class ResultRow(QWidget):
    def __init__(self, data, pal, parent=None, guard=None, on_activate=None,
                 snippet_chars=100):
        super().__init__(parent)
        self.data = data
        self._on_activate = on_activate
        self._snippet_chars = snippet_chars
        self.setToolTip(data["path"])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 8, 6)
        layout.setSpacing(9)

        self.check = QCheckBox()
        self.check.setFixedWidth(16)
        layout.addWidget(self.check, 0, Qt.AlignTop | Qt.AlignVCenter)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(1)

        # 标签行：把"为什么命中""这条数据可信吗"直接摊开，
        # 而不是让用户从一段看起来无关的正文片段里猜。
        tags = []
        if data.get("group") == "name":
            tags.append(t("文件名命中"))
            if data.get("content_also"):
                tags.append(t("内容也命中"))
        if data.get("status") == "truncated":
            tags.append(t("正文仅索引前半段"))
        if data.get("stale"):
            tags.append(t("文件已不存在"))

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        name = QLabel()
        name.setObjectName("name")
        name.setText(_plain(data["name"], 60))
        name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        head.addWidget(name)
        if tags:
            tag = QLabel("  ".join(tags))
            tag.setObjectName("tag")
            head.addWidget(tag)
        head.addStretch(1)

        meta = QLabel()
        meta.setObjectName("faint")
        meta.setText(
            "%s  ·  %s  ·  %s"
            % (_display_dir(data, guard), human_size(data["size"]), _stamp(data["mtime"]))
        )

        snippet = QLabel()
        snippet.setObjectName("snip")
        snippet.setTextFormat(Qt.RichText)
        snippet.setWordWrap(True)
        snippet.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if data.get("stale"):
            snippet.setText(
                t('<span style="color:#E06C6C">索引里有它，但磁盘上已经不在了 —— '
                '建议重建索引，或确认文件是否被改名/移动。</span>')
            )
        else:
            snippet.setText(
                _snippet_html(_snippet_plain(data["snippet"], self._snippet_chars), pal)
            )

        column.addLayout(head)
        column.addWidget(meta)
        column.addWidget(snippet)
        layout.addLayout(column, 1)

        self.name_label = name
        self.meta_label = meta
        self.snippet_label = snippet
        # 文字可选中后，QLabel 会吃掉双击（变成“选中一个词”），
        # 这里把双击转发成原来的“打开文件”，避免回归。
        name.installEventFilter(self)
        snippet.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonDblClick and self._on_activate is not None:
            self._on_activate(self.data)
            return True
        return super().eventFilter(obj, event)
