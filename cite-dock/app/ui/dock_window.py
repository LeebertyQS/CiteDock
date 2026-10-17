# -*- coding: utf-8 -*-
"""悬浮坞主窗口（从 float_bar.py 拆分而来）。

检索条 + 结果列表 + 复制引用动作。DragFrame / ScopeCombo 是它的内部件；
结果行、选区浮条、后台线程分别在 result_row / selection_bar / workers 里。
"""
from __future__ import annotations

import html
import os
import re
import time

from PySide6.QtCore import (
    QEvent, QMimeData, QPoint, QProcess, QSize, Qt, QThread, QTimer, QUrl, Signal,
)
from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton,
    QVBoxLayout, QWidget,
)

from ..core import config as config_mod
from ..core import extract, indexer, keyword, search
from ..core.textutil import human_size, MARK_L, MARK_R
from . import mousehook, theme
from ..i18n import t
from .. import i18n

from ._util import (
    LIST_MAX_HEIGHT, PLACEHOLDER_HEIGHT, _display_dir, _plain,
    _quote_if_needed, _snippet_html, _snippet_plain, _stamp,
)
from .result_row import FileMatchRow, ResultRow
from .selection_bar import SelectionBar
from .workers import CopyWorker, IndexWorker


_PUNCT_ONLY = re.compile(r"^[\s\W_]+$")


def _clone_mime(src):
    """深克隆剪贴板 mimeData —— 文本/图片/文件全格式一并存下，供探测后还原。"""
    m = QMimeData()
    if src is not None:
        for fmt in src.formats():
            m.setData(fmt, src.data(fmt))
    return m


def _coalesce_segments(segments):
    """展示层合并孤行标点：纯标点的碎片行（「.」「,」「{」「}」）并进相邻段。

    只动展示，不动提取器（citedock_kit 是通用件）—— PDF 提取出的孤行直接
    显示成一行很难看。开头没上一段的先暂存、拼到下一段开头。
    """
    out = []
    hold = []
    for index, text in segments:
        text = (text or "").strip()
        if not text:
            continue
        if len(text) <= 3 and _PUNCT_ONLY.match(text):
            if out:
                out[-1] = (out[-1][0], out[-1][1] + text)
            else:
                hold.append(text)
            continue
        if hold:
            text = "".join(hold) + text
            hold = []
        out.append((index, text))
    if hold and out:
        out[-1] = (out[-1][0], out[-1][1] + "".join(hold))
    return out


class DragFrame(QFrame):
    """卡片本体：空白处按住即可拖动整个窗口。"""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._window = window
        self._offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._offset = (
                event.globalPosition().toPoint()
                - self._window.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._offset is not None and event.buttons() & Qt.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._offset is not None:
            self._offset = None
            self._window.remember_pos()
            event.accept()
            return
        super().mouseReleaseEvent(event)

class ScopeCombo(QComboBox):
    popup_opened = Signal()
    popup_closed = Signal()

    def showPopup(self):
        self.popup_opened.emit()
        super().showPopup()

    def hidePopup(self):
        self.popup_closed.emit()
        super().hidePopup()

class DockWindow(QWidget):
    request_settings = Signal()
    request_reindex = Signal()
    request_quit = Signal()

    def __init__(self, cfg, guard, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.guard = guard
        self._conn = None
        self._rows = []
        self._expanded = False
        self._pinned = bool(cfg.get("window_pinned", cfg.get("pin_default")))
        self._suppress_hide = False
        self._shown_at = 0.0
        self._worker = None
        self._copy_worker = None
        self._schema_upgraded = False
        self._probe = None
        self._sel_bar = None
        self._file_mode = False
        self._file_data = None
        self._file_segments = []
        self._file_kind = "text"
        self._loose_search = False

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(theme.PANEL_WIDTH)
        self.setWindowTitle(t("CiteDock 引用坞"))

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(220)
        self._debounce.timeout.connect(self._run_search)

        self._build_ui()
        self._reload_scope_combo()
        self.apply_theme()
        self._open_conn()
        self.btn_pin.setChecked(self._pinned)

    # ---------------- 构建 ----------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.card = DragFrame(self)
        outer.addWidget(self.card)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(7)

        grip = QLabel("\u28ff")
        grip.setObjectName("grip")
        grip.setFixedWidth(12)
        grip.setCursor(Qt.SizeAllCursor)
        grip.setToolTip(t("按住拖动；双击切换常驻"))
        top.addWidget(grip)

        self.input = QLineEdit()
        self.input.setPlaceholderText(t("输入关键词检索本地文件；或先复制一段话，再点「取词」"))
        self.input.setClearButtonEnabled(True)
        self.input.setMinimumHeight(32)
        self.input.textChanged.connect(lambda _: self._on_text_edited())
        self.input.returnPressed.connect(self._run_search)
        self.input.installEventFilter(self)
        top.addWidget(self.input, 1)

        self.btn_grab = QPushButton(t("取词"))
        self.btn_grab.setToolTip(t("从剪贴板提取关键词并检索"))
        self.btn_grab.clicked.connect(lambda: self.grab_clipboard(False))

        self.btn_pin = QPushButton(t("常驻"))
        self.btn_pin.setCheckable(True)
        self.btn_pin.setToolTip(t("开启后置顶显示、失焦也不隐藏"))
        self.btn_pin.toggled.connect(self._on_pin_toggled)

        self.btn_settings = QPushButton(t("设置"))
        self.btn_settings.clicked.connect(self.request_settings.emit)

        self.btn_hide = QPushButton(t("收起"))
        self.btn_hide.clicked.connect(self._on_hide_clicked)

        for button in (self.btn_grab, self.btn_pin, self.btn_settings, self.btn_hide):
            button.setMinimumHeight(32)
            top.addWidget(button)

        root.addLayout(top)

        self.results_area = QWidget()
        results_layout = QVBoxLayout(self.results_area)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(6)

        scope_row = QHBoxLayout()
        scope_row.setSpacing(6)
        scope_label = QLabel(t("范围"))
        scope_label.setObjectName("faint")
        scope_row.addWidget(scope_label)
        self.scope_combo = ScopeCombo()
        self.scope_combo.setMaximumWidth(220)
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        self.scope_combo.popup_opened.connect(self._on_scope_popup_opened)
        self.scope_combo.popup_closed.connect(self._on_scope_popup_closed)
        scope_row.addWidget(self.scope_combo, 1)
        results_layout.addLayout(scope_row)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        results_layout.addWidget(divider)

        # 索引进行中时必须让用户看得见 —— 否则他会照着半成品索引下结论
        self.banner = QLabel("")
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        results_layout.addWidget(self.banner)

        self.file_view = QWidget()
        self.file_view.setVisible(False)
        file_layout = QVBoxLayout(self.file_view)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(6)
        file_top = QHBoxLayout()
        file_top.setSpacing(6)
        self.btn_file_back = QPushButton(t("返回"))
        self.btn_file_back.clicked.connect(self._exit_file_search)
        file_top.addWidget(self.btn_file_back)
        self.lbl_file_name = QLabel("")
        self.lbl_file_name.setObjectName("name")
        file_top.addWidget(self.lbl_file_name, 1)
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText(t("在文件内检索（不支持正则）"))
        self.file_input.setClearButtonEnabled(True)
        self.file_input.textChanged.connect(lambda _: self._file_search())
        self.file_input.returnPressed.connect(self._file_search)
        self.file_input.installEventFilter(self)
        file_top.addWidget(self.file_input, 1)
        file_layout.addLayout(file_top)
        self.file_notice = QLabel("")
        self.file_notice.setObjectName("banner")
        self.file_notice.setWordWrap(True)
        self.file_notice.setVisible(False)
        file_layout.addWidget(self.file_notice)
        self.file_matches = QListWidget()
        self.file_matches.setFixedHeight(LIST_MAX_HEIGHT)
        self.file_matches.setSelectionMode(QAbstractItemView.NoSelection)
        self.file_matches.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.file_matches.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.file_matches.setFocusPolicy(Qt.NoFocus)
        file_layout.addWidget(self.file_matches)
        results_layout.addWidget(self.file_view)

        self.list = QListWidget()
        self.list.setFixedHeight(LIST_MAX_HEIGHT)
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.itemDoubleClicked.connect(self._on_item_activated)
        results_layout.addWidget(self.list)

        self.result_toolbar = QWidget()
        toolbar = QHBoxLayout(self.result_toolbar)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)
        self.lbl_count = QLabel(t("未选择"))
        self.lbl_count.setObjectName("stat")
        toolbar.addWidget(self.lbl_count)
        toolbar.addStretch(1)

        self.btn_selall = QPushButton(t("全选"))
        self.btn_selall.clicked.connect(self._toggle_select_all)

        self.btn_copy_path = QPushButton(t("复制路径"))
        self.btn_copy_ref = QPushButton(t("复制引用"))
        self.btn_copy_body = QPushButton(t("复制内容"))
        self.btn_open = QPushButton(t("打开"))
        self.btn_reveal = QPushButton(t("定位"))
        self.btn_reveal.setToolTip(t("在资源管理器里选中该文件"))
        self.btn_file_search = QPushButton(t("文件内检索"))
        self.btn_file_search.clicked.connect(self._enter_file_search)

        self.btn_copy_path.clicked.connect(lambda: self._copy_paths(False))
        self.btn_copy_ref.clicked.connect(lambda: self._copy_paths(True))
        self.btn_copy_body.clicked.connect(self._copy_bodies)
        self.btn_open.clicked.connect(self._open_selected)
        self.btn_reveal.clicked.connect(self._reveal_selected)

        # 原「送入整理器」按钮已删除 —— 本工具只管检索与引用，不做多余入口。
        for button in (
            self.btn_selall, self.btn_copy_path, self.btn_copy_ref,
            self.btn_copy_body, self.btn_open, self.btn_reveal,
            self.btn_file_search,
        ):
            button.setMinimumHeight(26)
            toolbar.addWidget(button)

        results_layout.addWidget(self.result_toolbar)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("stat")
        self.lbl_status.setWordWrap(True)
        results_layout.addWidget(self.lbl_status)

        root.addWidget(self.results_area)
        self._set_expanded(False)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    # ---------------- 样式 ----------------

    def retranslate(self):
        """切换语言后刷新文案。

        常驻控件与结果行靠通用重绘；动态拼接出来的状态栏文案认不出来，
        所以额外重建一次状态栏。范围下拉里是范围名（用户数据），不翻译。
        """
        i18n.refresh(self, (QLabel, QPushButton, QCheckBox))
        self._fit_width()
        self.setWindowTitle(t("CiteDock 引用坞"))
        self.input.setPlaceholderText(t("输入关键词检索本地文件；或先复制一段话，再点「取词」"))
        self.file_input.setPlaceholderText(t("在文件内检索（不支持正则）"))
        self._on_pin_toggled(self.btn_pin.isChecked())
        self.refresh_index_state()
        # 含数字的动态文案（如「文件名命中（3）」）是拼出来的 key，通用重绘认不出来 ——
        # 结果区非空时重跑一次当前检索，让段标题立刻换成新语言。
        if self.input.text().strip():
            self._run_search()

    def apply_theme(self):
        pal = theme.palette(self.cfg.get("theme"))
        extra = """
QLabel#faint { font-size: 11px; }
QLabel#snip  { font-size: 12px; }
QLabel#tag   { font-size: 11px; color: %(warn)s; }
QLabel#section { font-size: 11px; font-weight: 600; color: %(accent)s; }
QLabel#banner {
    font-size: 11px;
    color: %(warn)s;
    background: rgba(224, 163, 62, 34);
    border-radius: 6px;
    padding: 4px 8px;
}
""" % {"warn": pal["warn"], "accent": pal["accent"]}
        self.setStyleSheet(theme.build_qss(self.cfg.get("theme"), extra))
        return pal

    # ---------------- 数据 ----------------

    def _open_conn(self):
        try:
            path = config_mod.db_path()
            self._conn = indexer.connect(path)
            self._schema_upgraded = bool(indexer.init_db(self._conn))
        except Exception:
            self._conn = None

    def _scope_guidance(self):
        """首次使用引导：区分「从没配过」和「曾配过但现在一个都不存在」。

        两种情况都要让人看懂，而不是冷冰冰的一句"尚未设置检索范围"。
        从 git 下载的人会直接跑然后看到空界面 —— 这两句话决定他留还是走。
        """
        roots = config_mod.all_roots(self.cfg)
        if not roots:
            return t("第一次使用：点「设置」→「添加目录」，选一个要索引的文件夹。")
        existing = [r for r in roots if os.path.isdir(r)]
        if not existing:
            shown = "、".join(roots[:3])
            if len(roots) > 3:
                shown += t(" 等 %d 个") % len(roots)
            return t(
                "配置里的目录现在都不存在了（%s），可能被移动、删除或改了盘符 —— 点「设置」重新选择。"
            ) % shown
        return t("尚未设置检索范围：点「设置」选择要索引的目录。")

    def refresh_index_state(self):
        self.lbl_status.setText(self._status_text())

    def _status_text(self):
        if not self.guard.has_roots():
            return self._scope_guidance()
        if self._conn is None:
            return t("索引库不可用 —— 可在「设置」里点「重建索引库」。")
        info = indexer.stats(self._conn)
        if not info["total"]:
            return t("索引为空，点「设置」选择目录后会自动建立索引。")

        # 统计口径全部摊开：不再用一个含糊的"跳过"把截断、失败、超限糊在一起
        parts = [t("已索引 %d 个文件") % info["indexed"]]
        if info["truncated"]:
            parts.append(t("%d 个正文仅索引前半段") % info["truncated"])
        if info["failed"]:
            parts.append(t("%d 个取文失败") % info["failed"])
        if info["skipped"]:
            parts.append(t("%d 个被跳过") % info["skipped"])
        parts.append(t("更新于 %s") % (_stamp(info["last_sync"]) if info["last_sync"] else "-"))
        line = " · ".join(parts)

        warnings = []
        if info["scan_truncated"]:
            warnings.append(
                t("扫描达到文件数上限（%d）已提前停止，请缩小检索范围或调高上限")
                % int(self.cfg.get("max_index_files") or 0)
            )
        if info["mtime_suspect"]:
            warnings.append(t("多数文件时间戳集中在同一天，新近排序已弱化"))
        if warnings:
            line += "\n⚠ " + t("；").join(warnings)
        return line

    # ---------------- 检索 ----------------

    def _on_text_edited(self):
        # 手动改过词就不再算"宽松检索"了 —— 用户明确输入时该用 AND 卡准
        self._loose_search = False
        self._debounce.start()

    def _run_search(self):
        self._debounce.stop()
        if self._conn is None:
            self._open_conn()
        query = self.input.text().strip()
        if not query:
            self._clear_results()
            self.refresh_index_state()
            return
        if not self.guard.has_roots():
            self._clear_results()
            self.lbl_status.setText(self._scope_guidance())
            return
        roots = config_mod.active_roots(self.cfg)
        if not roots:
            self._clear_results()
            self.lbl_status.setText(t("当前范围没有检索目录：请在设置里添加目录。"))
            return
        limit = min(int(config_mod.search_setting(self.cfg, "limit", 60) or 60), 200)
        match = config_mod.search_setting(self.cfg, "match", "all")
        content = bool(config_mod.search_setting(self.cfg, "content", True))
        ext_filter = config_mod.search_setting(self.cfg, "ext_filter", []) or []
        mode = "AND"
        try:
            if self._loose_search:
                hits = search.search_or(
                    self._conn, query, limit=limit, roots=roots,
                    content=content, ext_filter=ext_filter,
                )
                mode = "LOOSE"
            else:
                hits, mode = search.search_with_mode(
                    self._conn, query, limit=limit, roots=roots,
                    match=match, content=content, ext_filter=ext_filter,
                )
        except Exception as exc:
            hits = []
            self.lbl_status.setText(t("检索出错：%s") % exc)
        self._populate(hits, query, mode)
        # 有命中就展开 —— 否则用户在收起态下搜到东西却什么都看不见。
        if hits and not self._expanded:
            self._set_expanded(True)

    def _reload_scope_combo(self):
        scopes = self.cfg.get("scopes") or []
        active = self.cfg.get("active_scope")
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        for scope in scopes:
            name = scope.get("name", "")
            self.scope_combo.addItem(name, name)
        index = self.scope_combo.findData(active)
        self.scope_combo.setCurrentIndex(index if index >= 0 else 0)
        self.scope_combo.blockSignals(False)

    def _on_scope_changed(self, index):
        name = self.scope_combo.itemData(index)
        if name is None:
            return
        self.cfg["active_scope"] = name
        if self.input.text().strip():
            self._run_search()
        else:
            self.refresh_index_state()

    def _on_scope_popup_opened(self):
        # 下拉弹出时坞会短暂失焦，必须先按住 _suppress_hide，否则坞会自己藏起来
        self._suppress_hide = True

    def _on_scope_popup_closed(self):
        QTimer.singleShot(0, self._clear_scope_suppress)

    def _clear_scope_suppress(self):
        self._suppress_hide = False

    def _scope_status_bits(self):
        """状态栏里“和默认不一样”的范围/检索项（G-6）。"""
        bits = []
        scope = config_mod.active_scope(self.cfg)
        if scope:
            bits.append(t("范围：%s") % scope.get("name", ""))
        if not config_mod.search_setting(self.cfg, "content", True):
            bits.append(t("仅文件名"))
        match = config_mod.search_setting(self.cfg, "match", "all")
        if match == "any":
            bits.append(t("任一词"))
        elif match == "phrase":
            bits.append(t("整段短语"))
        exts = config_mod.search_setting(self.cfg, "ext_filter", []) or []
        if exts:
            bits.append(t("后缀 %s") % " ".join(exts))
        return bits

    def _clear_results(self):
        self.list.clear()
        self._rows = []
        self._fit_list()
        self._update_selection_label()

    def _fit_list(self):
        """结果列表高度贴合行数，别在下方留一大片空白。"""
        if not self._rows:
            self.list.setFixedHeight(PLACEHOLDER_HEIGHT)
        else:
            total = sum(self.list.item(i).sizeHint().height()
                        for i in range(self.list.count()))
            self.list.setFixedHeight(min(LIST_MAX_HEIGHT, total + 4))
        self._relayout()

    def _row_height(self, snippet_text=""):
        """行高按**实际字体与列表宽度**测量 snippet 的换行行数。

        旧公式假设每行 44 字符，但坞在宽屏上每行能放 100+ 字符 ——
        snippet_chars=700 时估出 16 行（306px），实际只渲染 3~4 行，
        行内出现大片空白（用户截图反馈的"大量空缺区域"就是这个）。
        """
        fm = self.list.fontMetrics()
        usable = max(220, self.list.viewport().width() - 130)
        snippet_chars = max(
            1, int(config_mod.search_setting(self.cfg, "snippet_chars", 100) or 100)
        )
        text = _snippet_plain(snippet_text or "", snippet_chars)
        text = text.replace(MARK_L, "").replace(MARK_R, "")
        if text:
            rect = fm.boundingRect(0, 0, usable, 10000, Qt.TextWordWrap, text)
            lines = max(1, round(rect.height() / fm.lineSpacing()))
        else:
            lines = 1
        return 50 + lines * fm.lineSpacing()

    def _populate(self, hits, query, mode="AND"):
        self.list.clear()
        self._rows = []
        pal = theme.palette(self.cfg.get("theme"))
        snippet_chars = int(config_mod.search_setting(self.cfg, "snippet_chars", 100) or 100)

        # 索引是快照，文件可能已被删/改名/移动。不验一遍就会把失效路径复制出去，
        # 而下游拿到不存在的路径时不会告诉你为什么。
        stale = 0
        for hit in hits:
            if not os.path.exists(hit["path"]):
                hit["stale"] = True
                stale += 1

        if not hits:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, PLACEHOLDER_HEIGHT))
            placeholder = QLabel(t("没有命中「%s」的文件。换个词，或先重建索引。") % _plain(query, 24))
            placeholder.setObjectName("faint")
            placeholder.setAlignment(Qt.AlignCenter)
            self.list.addItem(item)
            self.list.setItemWidget(item, placeholder)
        else:
            name_hits = [h for h in hits if h.get("group") == "name"]
            content_hits = [h for h in hits if h.get("group") != "name"]
            if name_hits:
                self._add_section_header(t("文件名命中（%d）") % len(name_hits))
                self._add_rows(name_hits, pal, snippet_chars)
            if content_hits:
                self._add_section_header(t("内容命中（%d）") % len(content_hits))
                self._add_rows(content_hits, pal, snippet_chars)

        self._fit_list()
        self._update_selection_label()
        total = indexer.stats(self._conn)["total"] if self._conn else 0
        scope_bits = self._scope_status_bits()
        summary = t("命中 %d 个文件 · 索引共 %d 个") % (len(hits), total)
        head = (t(" ｜ ").join(scope_bits) + t(" ｜ ")) if scope_bits else ""
        trailing = []
        if mode == "OR":
            trailing.append(t("未全部命中，已按任一关键词放宽"))
        elif mode == "LOOSE":
            trailing.append(t("宽松检索（关键词来自取词）"))
        if stale:
            trailing.append(t("其中 %d 个已不存在") % stale)
        tail = (" · ".join(trailing)) if trailing else ""
        self.lbl_status.setText(head + summary + ((" · " + tail) if tail else ""))

    def _add_section_header(self, text):
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 24))
        self.list.addItem(item)
        label = QLabel(text)
        label.setObjectName("section")
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.list.setItemWidget(item, label)

    def _add_rows(self, hits, pal, snippet_chars):
        for hit in hits:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, self._row_height(hit.get("snippet", ""))))
            self.list.addItem(item)
            row = ResultRow(
                hit, pal, guard=self.guard, on_activate=self._open_row,
                snippet_chars=snippet_chars,
            )
            row.check.stateChanged.connect(self._update_selection_label)
            self.list.setItemWidget(item, row)
            self._rows.append(row)

    def _update_selection_label(self):
        chosen = self._selected()
        self.lbl_count.setText(t("未选择") if not chosen else t("已选 %d 项") % len(chosen))
        self.btn_selall.setText(t("清空") if len(chosen) == len(self._rows) and self._rows else t("全选"))
        has = bool(chosen)
        for button in (self.btn_copy_path, self.btn_copy_ref, self.btn_copy_body,
                       self.btn_open, self.btn_reveal):
            button.setEnabled(has)
        self.btn_file_search.setEnabled(len(chosen) == 1)

    def _selected(self):
        return [row.data for row in self._rows if row.check.isChecked()]

    def _selected_text(self):
        """结果面板里当前被鼠标选中的文字（文件名或片段），没有则返回空串。"""
        for row in self._rows:
            for label in (row.name_label, row.snippet_label):
                try:
                    text = label.selectedText()
                except Exception:
                    text = ""
                if text and text.strip():
                    return text.strip()
        return ""

    def _toggle_select_all(self):
        target = not (len(self._selected()) == len(self._rows) and self._rows)
        for row in self._rows:
            row.check.setChecked(target)
        self._update_selection_label()

    # ---------------- 动作 ----------------

    def grab_clipboard(self, auto=False):
        text = QGuiApplication.clipboard().text() or ""
        if not text.strip() or (auto and len(text.strip()) < 12):
            if not auto:
                self.lbl_status.setText(t("剪贴板里没有可用的文本。"))
            return
        words = keyword.keywords_from_text(text, limit=3)
        if not words:
            if not auto:
                self.lbl_status.setText(t("没能从剪贴板里提取出关键词。"))
            return
        self.input.setText(" ".join(words))
        # 这些词是从一段话里猜出来的，不是用户精确指定的 —— 用 AND 卡几乎必然 0 命中，
        # 所以直接走宽松检索，不白跑一次 AND 再回退。
        self._loose_search = True
        self.input.setFocus()
        self._run_search()
        # 命中数合成一行，别被"已取词"覆盖掉
        self.lbl_status.setText(
            t("已取词「%s」 · %s") % (" ".join(words), self.lbl_status.text())
        )

    def on_select_hotkey(self):
        """热键触发：在**当前光标位置**探测选区。

        与右键路径共用同一套探测，区别只是触发方式与位置来源。
        排除列表同样生效 —— 终端里 Ctrl+C 是中断信号，绝不能注入。
        """
        pos = QCursor.pos()
        self._start_selection_probe(pos.x(), pos.y(), via="hotkey")

    def on_global_right_click(self, x, y):
        self._start_selection_probe(x, y, via="right")

    def _start_selection_probe(self, x, y, via="right"):
        self._probe_mime = None
        if self._probe is not None and self._probe.isRunning():
            return
        if mousehook.is_excluded(self.cfg.get("mousehook_exclude")):
            self._on_selection_nothing(
                t("这个程序在排除列表里（终端里 Ctrl+C 是中断信号），已跳过")
            )
            return
        wait_ms = int(self.cfg.get("mousehook_wait_ms") or 120)
        # 备份剪贴板全格式（含图片）—— 探测会 Ctrl+C 覆盖剪贴板，事后还原
        self._probe_mime = _clone_mime(QGuiApplication.clipboard().mimeData())
        self._probe = mousehook.SelectionProbe(x, y, wait_ms)
        self._probe.detected.connect(self._on_selection_detected)
        self._probe.nothing.connect(self._on_selection_nothing)
        self._probe.start()

    def _on_selection_nothing(self, reason):
        """没拿到选区时如实说明 —— 否则用户不知道是坏了还是没选中。"""
        self._restore_clipboard_mime()
        if not reason:
            return
        self.show_dock(expand=True, focus_input=False)
        self.lbl_status.setText(t("没拿到选区：%s") % reason)

    def _on_selection_detected(self, x, y, text):
        self._restore_clipboard_mime()
        self.show_selection_bar(x, y, text)

    #: 浮条相对光标的偏移（**逻辑像素**）。
    SEL_BAR_OFFSET = 2

    def _selection_bar_pos(self, size, pos=None):
        """算浮条左上角：紧贴光标右下 → 放不下就翻到光标另一侧 → 最后夹进屏幕。

        `pos` 必须是 **Qt 逻辑像素**（`QCursor.pos()`）。
        钩子回调给的 `MSLLHOOKSTRUCT.pt` 是 Win32 **物理**像素 —— 这台机器缩放 1.25，
        混用会恒定偏 1.25 倍（屏幕右下角右键时浮条直接被推出屏幕）。

        夹取用**光标所在屏**，不用 `primaryScreen()`：光标在副屏时会被夹回主屏。
        """
        if pos is None:
            pos = QCursor.pos()
        offset = self.SEL_BAR_OFFSET
        x = pos.x() + offset
        y = pos.y() + offset
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        if area is None:
            return QPoint(x, y)
        width = size.width()
        height = size.height()
        left, top = area.x(), area.y()
        right = area.x() + area.width()
        bottom = area.y() + area.height()
        # 右下放不下就翻到光标另一侧。**只贴边不行** —— 贴边之后离光标仍然很远。
        if x + width > right:
            x = pos.x() - width - offset
        if y + height > bottom:
            y = pos.y() - height - offset
        # 夹取兜底（屏幕比浮条还小时，优先"完整可见"）
        x = max(left, min(x, right - width))
        y = max(top, min(y, bottom - height))
        return QPoint(x, y)

    def _restore_clipboard_mime(self):
        mime = getattr(self, "_probe_mime", None)
        if mime is not None:
            QGuiApplication.clipboard().setMimeData(mime)
            self._probe_mime = None

    def show_selection_bar(self, x, y, text):
        """在**光标处**弹浮条。

        `x` / `y` 是触发时那份（Win32 物理像素）坐标，**不参与定位** ——
        只留作无屏幕时的兜底。定位一律走 `QCursor.pos()`（见 `_selection_bar_pos`）。
        """
        if self._sel_bar is not None:
            self._sel_bar.deleteLater()
            self._sel_bar = None
        bar = SelectionBar(text, self.cfg.get("theme"))
        bar.search_requested.connect(self._search_selection)
        bar.fill_requested.connect(self._fill_selection)
        bar.copy_requested.connect(self._copy_selection)
        # 先 polish + 激活布局再量尺寸：新建的 QWidget 还没套上字体与样式，
        # 此刻 `sizeHint()` 偏小，拿它算夹取算出来的位置**仍然出屏**。
        # （与 `_relayout()` 里 `setVisible(False)` 之后 `adjustSize()` 读旧尺寸同源。）
        bar.ensurePolished()
        bar.layout().activate()
        bar.adjustSize()
        bar.layout().activate()
        cursor = QCursor.pos()
        if QGuiApplication.screenAt(cursor) is None and (x or y):
            bar.move(int(x) + self.SEL_BAR_OFFSET, int(y) + self.SEL_BAR_OFFSET)
        else:
            bar.move(self._selection_bar_pos(bar.size(), cursor))
        self._sel_bar = bar
        bar.show()

    def _selection_query(self, text):
        words = keyword.keywords_from_text(text, limit=3)
        return " ".join(words) if words else (text or "").strip()

    def _search_selection(self, text):
        query = self._selection_query(text)
        if not query:
            return
        self.show_dock(expand=True, focus_input=False)
        self.input.setText(query)
        self._loose_search = True
        self._run_search()

    def _fill_selection(self, text):
        query = self._selection_query(text)
        if not query:
            return
        self.show_dock(expand=True, focus_input=False)
        self.input.setText(query)
        self.input.setFocus()
        self.input.selectAll()

    def _copy_selection(self, text):
        QGuiApplication.clipboard().setText(text)
        self.lbl_status.setText(t("已复制选中内容。"))

    def _enter_file_search(self):
        chosen = self._selected()
        if len(chosen) != 1:
            return
        data = chosen[0]
        kind, segments, error = extract.read_for_search(
            data["path"], guard=self.guard
        )
        if kind == "binary" or error:
            self.lbl_status.setText(
                t("无法检索该文件：%s") % (error or t("二进制文件"))
            )
            return
        self._file_data = data
        self._file_kind = kind
        self._file_segments = _coalesce_segments(segments)
        self.lbl_file_name.setText(data["name"])
        self.file_input.clear()
        changed = False
        try:
            stat = os.stat(data["path"])
            changed = (
                abs(stat.st_mtime - float(data.get("mtime") or 0)) > 0.001
                or stat.st_size != int(data.get("size") or -1)
            )
        except OSError:
            changed = False
        self.file_notice.setText(
            t("内容已变更，以下为最新版本") if changed else ""
        )
        self.file_notice.setVisible(bool(changed))
        self._set_file_mode(True)
        self._file_search()

    def _set_file_mode(self, flag):
        self._file_mode = bool(flag)
        self.file_view.setVisible(self._file_mode)
        self.list.setVisible(not self._file_mode)
        self.result_toolbar.setVisible(not self._file_mode)
        self._relayout()
        if self._file_mode:
            self.file_input.setFocus()

    def _exit_file_search(self):
        self._file_mode = False
        self._file_data = None
        self._file_segments = []
        self.file_view.setVisible(False)
        self.list.setVisible(True)
        self.result_toolbar.setVisible(True)
        self._relayout()
        self.refresh_index_state()

    def _file_search(self):
        self.file_matches.clear()
        query = self.file_input.text().strip()
        if not query:
            self.lbl_status.setText("")
            return
        lowered = query.lower()
        total = sum(1 for _index, text in self._file_segments
                    if lowered in (text or "").lower())
        hits = [
            (index, text) for index, text in self._file_segments
            if lowered in (text or "").lower()
        ][:200]
        if not hits:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, PLACEHOLDER_HEIGHT))
            placeholder = QLabel(t("文件内没有命中「%s」。") % _plain(query, 20))
            placeholder.setObjectName("faint")
            placeholder.setAlignment(Qt.AlignCenter)
            self.file_matches.addItem(item)
            self.file_matches.setItemWidget(item, placeholder)
            self.lbl_status.setText(t("命中 0 处"))
            return
        for index, text in hits:
            item = QListWidgetItem()
            row = FileMatchRow(self._file_kind, index, text)
            item.setSizeHint(QSize(0, max(48, row.sizeHint().height())))
            self.file_matches.addItem(item)
            self.file_matches.setItemWidget(item, row)
            row.copy_requested.connect(self._copy_file_match)
        note = t("命中 %d 处") % total + (t("，展示前 200") if total > 200 else "")
        self.lbl_status.setText(note)

    def _copy_file_match(self, text):
        QGuiApplication.clipboard().setText(text)
        self.lbl_status.setText(t("已复制该段。"))

    def _copy_paths(self, as_reference):
        items = self._selected()
        if not items:
            return
        if as_reference:
            text = "\n".join("@" + _quote_if_needed(item["path"]) for item in items)
        else:
            text = "\n".join(item["path"] for item in items)
        QGuiApplication.clipboard().setText(text)
        self.lbl_status.setText(t("已复制 %d 项%s到剪贴板。") % (len(items), t("引用") if as_reference else t("路径")))

    def _copy_bodies(self):
        items = self._selected()
        if not items:
            return
        if self._copy_worker is not None and self._copy_worker.isRunning():
            return
        budget = int(self.cfg.get("copy_total_chars") or 200000)
        self.btn_copy_body.setEnabled(False)
        self.lbl_status.setText(t("正在读取 %d 个文件的正文…") % len(items))
        self._copy_worker = CopyWorker(items, budget, self.guard)
        self._copy_worker.done.connect(self._on_copy_bodies_done)
        self._copy_worker.failed.connect(self._on_copy_bodies_failed)
        self._copy_worker.start()

    def _on_copy_bodies_done(self, result):
        self.btn_copy_body.setEnabled(bool(self._selected()))
        texts = result["texts"]
        too_big = result["too_big"]
        empty = result["empty"]
        total = result["total"]
        budget = result["budget"]
        if too_big:
            self.lbl_status.setText(
                t("已取消复制：所选正文合计会超过 %d 字符上限。放不下的有：%s\n"
                "请取消勾选其中几项或分批复制。源文件未被改动。")
                % (budget, t("、").join(too_big[:6]) + ("…" if len(too_big) > 6 else ""))
            )
            return

        if not texts:
            self.lbl_status.setText(t("所选文件没有可复制的文本内容。"))
            return

        chunks = ["\n\n===== %s =====\n%s" % (item["path"], text)
                  for item, text in texts]
        QGuiApplication.clipboard().setText("".join(chunks))
        note = t("（%d 个无文本内容已跳过）") % len(empty) if empty else ""
        self.lbl_status.setText(
            t("已复制 %d 个文件的正文，共 %d 字符 %s") % (len(texts), total, note)
        )

    def _on_copy_bodies_failed(self, message):
        self.btn_copy_body.setEnabled(bool(self._selected()))
        self.lbl_status.setText(t("读取正文失败：%s") % message)

    def _open_selected(self):
        for item in self._selected()[:5]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(item["path"]))

    def _reveal_selected(self):
        for item in self._selected()[:10]:
            QProcess.startDetached(
                "explorer.exe", ["/select,", os.path.normpath(item["path"])]
            )

    def _on_item_activated(self, list_item):
        row = self.list.itemWidget(list_item)
        if isinstance(row, ResultRow):
            QDesktopServices.openUrl(QUrl.fromLocalFile(row.data["path"]))

    def _open_row(self, data):
        QDesktopServices.openUrl(QUrl.fromLocalFile(data["path"]))

    # ---------------- 索引 ----------------

    def start_reindex(self, expand=True):
        self._reload_scope_combo()
        if self._worker is not None and self._worker.isRunning():
            return
        if not self.guard.has_roots():
            if expand:
                self._set_expanded(True)
                self.lbl_status.setText(self._scope_guidance())
            return
        if expand:
            self._set_expanded(True)
        self._set_banner(
            t("索引正在更新：此刻的结果是半成品（部分新、部分旧），请等它跑完再下结论。")
        )
        self.lbl_status.setText(t("正在建立索引…"))
        self._worker = IndexWorker(self.cfg, self.guard)
        self._worker.progressed.connect(self._on_progress)
        self._worker.done.connect(self._on_index_done)
        self._worker.failed.connect(self._on_index_failed)
        self._worker.start()

    def _set_banner(self, text=""):
        self.banner.setText(text)
        self.banner.setVisible(bool(text))
        self._relayout()

    def _on_progress(self, done, total, name):
        if total:
            self.lbl_status.setText(t("正在索引 %d / %d  %s") % (done, total, _plain(name, 30)))
        else:
            self.lbl_status.setText(t("正在扫描目录…"))

    def _on_index_done(self, result):
        self._set_banner("")
        bits = [t("新增 %d") % result.get("added", 0), t("更新 %d") % result.get("updated", 0)]
        if result.get("removed"):
            bits.append(t("移除 %d") % result["removed"])
        if result.get("truncated"):
            bits.append(t("正文截断 %d") % result["truncated"])
        if result.get("failed"):
            bits.append(t("取文失败 %d") % result["failed"])
        if result.get("skipped_total"):
            detail = result.get("skipped_detail") or {}
            shape = t("、").join("%s %d" % (k, v) for k, v in sorted(detail.items()))
            bits.append(t("跳过 %d（%s）") % (result["skipped_total"], shape))
        bits.append(t("耗时 %.1fs") % result.get("seconds", 0.0))
        line = t("索引完成：") + t("，").join(bits)
        if result.get("schema_upgraded") or self._schema_upgraded:
            line = t("索引结构已升级，已重建。") + line
            self._schema_upgraded = False

        warnings = []
        if result.get("scan_truncated"):
            warnings.append(
                t("扫描达到文件数上限（%s）已提前停止 —— 结果不完整，"
                "请缩小检索范围或到设置里调高上限")
                % result.get("scan_limit", 0)
            )
        if result.get("mtime_suspect"):
            warnings.append(t("多数文件时间戳集中在同一天，新近排序已弱化"))
        if warnings:
            line += "\n⚠ " + t("；").join(warnings)

        self.lbl_status.setText(line)
        if self.input.text().strip():
            self._run_search()
        else:
            QTimer.singleShot(6000, self.refresh_index_state)

    def _on_index_failed(self, message):
        self._set_banner("")
        self.lbl_status.setText(t("索引失败：%s") % message)

    def rebuild_db(self):
        """索引库损坏或结构异常时的唯一恢复路径。

        关连接 → 把 index.db（含 WAL 侧文件）改名成带时间戳的备份 → 重建空库。
        全程不碰任何源文件；备份留在原地，用户自己决定去留。
        """
        self.stop_worker()
        try:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
        except Exception:
            pass
        backup = None
        try:
            backup = indexer.reset_db(config_mod.db_path())
        except OSError as exc:
            self.lbl_status.setText(t("重建索引库失败：%s（可能仍被别的进程占用）") % exc)
            return
        self._open_conn()
        self._set_banner(t("索引库已重建，正在重新扫描…"))
        if backup:
            self.lbl_status.setText(t("旧索引库已备份为：%s") % backup)
        self.start_reindex(expand=True)

    def stop_worker(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2500)

    # ---------------- 显示控制 ----------------

    def _fit_width(self):
        """面板宽度跟着文案走。

        英文动作栏按钮明显比中文宽，写死 700 会把「Copy references」这类按钮
        挤出可视区（被裁成「opy referenc」）。只按动作栏这一行算，它是全宽最紧的。
        结果区里的片段会自动换行，不需要额外宽度。
        """
        buttons = (
            self.btn_selall, self.btn_copy_path, self.btn_copy_ref,
            self.btn_copy_body, self.btn_open, self.btn_reveal, self.btn_file_search,
        )
        row = sum(max(b.sizeHint().width(), b.minimumSizeHint().width())
                  for b in buttons if b.isVisibleTo(self))
        row += 6 * max(0, len(buttons) - 1)
        label = max(self.lbl_count.sizeHint().width(), 90)
        needed = max(theme.PANEL_WIDTH, label + row + 44)
        self.setFixedWidth(min(needed, theme.PANEL_WIDTH_MAX))

    def _relayout(self):
        """强制布局立即重算，再让窗口贴合内容。

        注意：不能在 setVisible 之后直接 adjustSize —— 子控件隐藏只是排了一个
        LayoutRequest 事件，此刻读到的 sizeHint 仍是旧的（展开态），窗口收不回去。
        必须先 activate 布局，才能拿到正确的尺寸。
        """
        if hasattr(self, "btn_file_search"):   # 建界面过程中可能还没轮到它
            self._fit_width()
        for widget in (self.results_area, self.card, self):
            layout = widget.layout()
            if layout is not None:
                layout.activate()
        self.adjustSize()

    def _set_expanded(self, flag):
        self._expanded = bool(flag)
        self.results_area.setVisible(self._expanded)
        self._relayout()

    def _on_pin_toggled(self, checked):
        self._pinned = bool(checked)
        self.cfg["window_pinned"] = self._pinned
        self.btn_pin.setToolTip(
            t("常驻中：置顶且不随焦点隐藏，点一下取消") if checked
            else t("开启后置顶显示、失焦也不隐藏")
        )

    def _on_hide_clicked(self):
        if self._expanded:
            self._set_expanded(False)
        else:
            self.hide_dock()

    def toggle(self):
        if self.isVisible():
            self.hide_dock()
        else:
            self.show_dock()

    def show_dock(self, expand=False, focus_input=True):
        self._shown_at = time.monotonic()
        self._reload_scope_combo()
        if expand:
            self._set_expanded(True)
        self._place_window()
        self.show()
        self.raise_()
        self.activateWindow()
        if focus_input:
            self.input.setFocus()
            self.input.selectAll()
        self.refresh_index_state()
        if (
            self.cfg.get("auto_grab_clipboard")
            and self.guard.has_roots()
            and not self.input.text().strip()
        ):
            self.grab_clipboard(auto=True)

    def hide_dock(self):
        self.remember_pos()
        self.hide()

    def _place_window(self):
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        pos = self.cfg.get("window_pos")
        self._relayout()
        width = self.width()
        height = self.height()
        if isinstance(pos, (list, tuple)) and len(pos) == 2 and area is not None:
            x = max(area.x(), min(int(pos[0]), area.x() + area.width() - width))
            y = max(area.y(), min(int(pos[1]), area.y() + area.height() - height))
        elif area is not None:
            x = area.x() + (area.width() - width) // 2
            y = area.y() + int(area.height() * 0.70)
        else:
            x, y = 200, 400
        self.move(QPoint(x, y))

    def remember_pos(self):
        point = self.pos()
        self.cfg["window_pos"] = [point.x(), point.y()]

    # ---------------- 事件 ----------------

    def event(self, event):
        if event.type() == QEvent.Type.WindowDeactivate and not self._pinned:
            recent = (time.monotonic() - self._shown_at) < 0.6
            if not recent and not self._suppress_hide and QApplication.activeModalWidget() is None:
                self.hide_dock()
        return super().event(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key_Escape:
            if obj is self.file_input and self._file_mode:
                self._exit_file_search()
                return True
            if obj is self.input:
                if self._file_mode:
                    self._exit_file_search()
                elif self._expanded:
                    self._set_expanded(False)
                else:
                    self.hide_dock()
                return True
        return super().eventFilter(obj, event)

    def _show_menu(self, point):
        menu = QMenu(self)
        act_search_sel = None
        selected = self._selected_text()
        if selected:
            act_search_sel = menu.addAction(t("用选中的文字检索「%s」") % _plain(selected, 12))
            menu.addSeparator()
        act_show = menu.addAction(t("展开结果面板") if not self._expanded else t("收起结果面板"))
        act_pin = menu.addAction(t("取消常驻") if self._pinned else t("常驻显示"))
        menu.addSeparator()
        act_settings = menu.addAction(t("设置…"))
        act_reindex = menu.addAction(t("重建索引"))
        act_rebuild = menu.addAction(t("重建索引库（损坏时用）…"))
        menu.addSeparator()
        act_quit = menu.addAction(t("退出 CiteDock"))

        chosen = menu.exec(self.mapToGlobal(point))
        if act_search_sel is not None and chosen is act_search_sel:
            self.input.setText(selected)
            self._loose_search = False
            self.input.setFocus()
            self._run_search()
        elif chosen is act_show:
            self._set_expanded(not self._expanded)
        elif chosen is act_pin:
            self.btn_pin.setChecked(not self._pinned)
        elif chosen is act_settings:
            self.request_settings.emit()
        elif chosen is act_reindex:
            self.request_reindex.emit()
        elif chosen is act_rebuild:
            self._confirm_rebuild_db()
        elif chosen is act_quit:
            self.request_quit.emit()

    def _confirm_rebuild_db(self):
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self, t("重建索引库"),
            t("将把现有 index.db 改名为带时间戳的备份（不删除），再新建一个空库。\n\n"
            "源文件不会被读写，重建后会自动重新扫描。确定继续？"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.rebuild_db()

    def closeEvent(self, event):
        event.ignore()
        self.hide_dock()
