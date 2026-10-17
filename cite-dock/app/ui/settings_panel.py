# -*- coding: utf-8 -*-
"""设置面板：检索范围管理、全局索引设置、当前范围检索选项。"""
from __future__ import annotations

import copy
import os

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QInputDialog, QKeySequenceEdit, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

from . import theme
from .. import i18n
from ..core import config as config_mod
from ..core import indexer
from ..i18n import t

# 注意：**不要**在模块级调用 t()。模块级求值发生在用户选择语言之前，
# 会把文案冻结在当时的语言上。要翻译就用在函数体里（或用函数包一层）。
STALE_SUFFIX_KEY = "    ← 目录不存在，索引会忽略它"


class _WheelForwarder(QObject):
    """把内层列表的滚轮事件转给最外层的滚动区。

    面板是"外层滚动区 + 内层两个列表"，鼠标停在内层列表上时滚轮只滚内层 ——
    极易"滚错层"。装上它之后内层永远不自己滚，滚轮统一作用于整页；
    要看更多项仍然可以拖内层的滚动条。
    """

    def __init__(self, area, parent=None):
        super().__init__(parent)
        self._area = area

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                bar = self._area.verticalScrollBar()
                bar.setValue(bar.value() - delta)
            return True
        return False


class NoWheelSpinBox(QSpinBox):
    """数值框不吃滚轮：滚轮统一留给整页滚动。

    否则鼠标停在数值框上滚轮会改数值（用户本想滚页面），和「滚轮滚整页」的
    设计冲突。ignore 之后事件冒泡给外层 QScrollArea，由它原生滚动。
    """

    def wheelEvent(self, event):
        event.ignore()


class NoWheelComboBox(QComboBox):
    """下拉框不吃滚轮：滚轮统一留给整页滚动（主题/语言选择）。"""

    def wheelEvent(self, event):
        event.ignore()


class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = copy.deepcopy(cfg)
        self.scopes = self.cfg.get("scopes") or []
        self.saved = False
        self.rebuild_requested = False
        self._current_index = -1
        self.setWindowTitle(t("CiteDock 设置"))
        self.setModal(True)
        # 尺寸：不再跟着设置项无限长高，内容交给滚动区
        self.setMinimumSize(560, 380)
        self.resize(640, 520)

        # 面板是无父窗口的独立对话框，**不会继承悬浮坞的样式表** —— 必须自己套一份。
        self.apply_theme()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        # 内容全部放进滚动区。按钮栏留在滚动区**外面**：
        # 否则内容一长，保存/取消就被滚走，用户会找不到怎么保存。
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(10)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # ---- 顶部：范围下拉 + 管理按钮 ----
        scope_row = QHBoxLayout()
        scope_row.setSpacing(6)
        self.scope_combo = QComboBox()
        self.scope_combo.setMinimumWidth(180)
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        scope_row.addWidget(self.scope_combo)
        self.btn_new_scope = QPushButton(t("新建"))
        self.btn_rename_scope = QPushButton(t("重命名"))
        self.btn_duplicate_scope = QPushButton(t("复制"))
        self.btn_delete_scope = QPushButton(t("删除"))
        self.btn_new_scope.clicked.connect(self._new_scope)
        self.btn_rename_scope.clicked.connect(self._rename_scope)
        self.btn_duplicate_scope.clicked.connect(self._duplicate_scope)
        self.btn_delete_scope.clicked.connect(self._delete_scope)
        for button in (self.btn_new_scope, self.btn_rename_scope,
                       self.btn_duplicate_scope, self.btn_delete_scope):
            scope_row.addWidget(button)
        scope_row.addStretch(1)
        layout.addLayout(scope_row)

        # ---- 当前范围的目录 ----
        title = QLabel(t("检索目录"))
        title.setObjectName("name")
        layout.addWidget(title)
        hint = QLabel(
            t("只有列出的目录会被扫描。范围之外的路径一律拒绝；切换范围时改动会自动保存。")
        )
        hint.setObjectName("faint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.roots_list = QListWidget()
        self.roots_list.setObjectName("plain")
        self.roots_list.setFixedHeight(100)
        layout.addWidget(self.roots_list)

        row = QHBoxLayout()
        self.btn_add = QPushButton(t("添加目录…"))
        self.btn_del = QPushButton(t("移除选中"))
        self.btn_add.clicked.connect(self._add_root)
        self.btn_del.clicked.connect(self._remove_root)
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_del)
        row.addStretch(1)
        self.lbl_stale = QLabel("")
        self.lbl_stale.setObjectName("faint")
        row.addWidget(self.lbl_stale)
        layout.addLayout(row)

        # ---- 全局设置（影响索引，对所有范围生效）----
        global_title = QLabel(t("全局设置（影响索引，对所有范围生效）"))
        global_title.setObjectName("name")
        layout.addWidget(global_title)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.ed_exclude_dirs = QLineEdit(", ".join(cfg.get("exclude_dirs") or []))
        self.ed_exclude_dirs.setCursorPosition(0)   # 长按默认显示末尾，看着像被截断
        form.addRow(t("排除目录名"), self.ed_exclude_dirs)

        self.ed_exclude_globs = QLineEdit(", ".join(cfg.get("exclude_globs") or []))
        self.ed_exclude_globs.setCursorPosition(0)
        form.addRow(t("排除文件类型"), self.ed_exclude_globs)

        self.sp_max = NoWheelSpinBox()
        self.sp_max.setRange(1, 200)
        self.sp_max.setSuffix(" MB")
        self.sp_max.setValue(max(1, int(cfg.get("max_file_bytes", 2097152)) // (1024 * 1024)))
        self.sp_max.setToolTip(t("超过这个体积的文件整份不索引（会在状态栏如实报出数量）"))
        form.addRow(t("单文件索引上限"), self.sp_max)

        self.sp_max_chars = NoWheelSpinBox()
        self.sp_max_chars.setRange(10000, 5000000)
        self.sp_max_chars.setSingleStep(50000)
        self.sp_max_chars.setSuffix(t(" 字符"))
        self.sp_max_chars.setValue(int(cfg.get("max_index_chars") or 400000))
        self.sp_max_chars.setToolTip(t("单文件正文索引到这里为止；被截断的文件会在结果里标注"))
        form.addRow(t("单文件正文上限"), self.sp_max_chars)

        self.sp_max_files = NoWheelSpinBox()
        self.sp_max_files.setRange(0, 1000000)
        self.sp_max_files.setSingleStep(5000)
        self.sp_max_files.setSuffix(t(" 个"))
        self.sp_max_files.setValue(int(cfg.get("max_index_files") or 0))
        self.sp_max_files.setToolTip(
            t("扫描到这么多文件就停下并提示（0 = 不限）。\n"
            "防的是误把整个磁盘加进检索范围。")
        )
        form.addRow(t("索引文件数上限"), self.sp_max_files)

        self.ed_hotkey = QKeySequenceEdit(QKeySequence(cfg.get("hotkey") or "Ctrl+Alt+Space"))
        form.addRow(t("唤起热键"), self.ed_hotkey)

        self.ed_hotkey_select = QKeySequenceEdit(
            QKeySequence(cfg.get("hotkey_select") or "Ctrl+Alt+D")
        )
        self.ed_hotkey_select.setToolTip(
            t("在任意程序里选中文字后按它，CiteDock 会读走选区供检索")
        )
        form.addRow(t("检索选中文字"), self.ed_hotkey_select)

        self.cb_pin = QCheckBox(t("启动后默认常驻（置顶、不随焦点隐藏）"))
        self.cb_pin.setChecked(bool(cfg.get("pin_default")))
        form.addRow("", self.cb_pin)

        self.cb_clip = QCheckBox(t("唤起时自动从剪贴板取关键词"))
        self.cb_clip.setChecked(bool(cfg.get("auto_grab_clipboard", True)))
        form.addRow("", self.cb_clip)

        self.cb_offline = QCheckBox(t("离线断言：启动即切断本进程的全部网络能力"))
        self.cb_offline.setChecked(bool(cfg.get("offline_assert")))
        form.addRow("", self.cb_offline)

        self.cb_audit = QCheckBox(t("记录审计日志（索引与写入来源）"))
        self.cb_audit.setChecked(bool(cfg.get("audit_enabled", True)))
        form.addRow("", self.cb_audit)

        self.cb_theme = NoWheelComboBox()
        self.cb_theme.addItem(t("跟随系统"), "auto")
        self.cb_theme.addItem(t("深色"), "dark")
        self.cb_theme.addItem(t("浅色"), "light")
        self.cb_theme.setCurrentIndex(max(0, self.cb_theme.findData(str(cfg.get("theme")))))
        form.addRow(t("界面主题"), self.cb_theme)

        # 语言名用**自称**显示（中文 / English），不随界面语言变化 ——
        # 这样任何语言下你都认得出自己的母语。
        self.cb_language = NoWheelComboBox()
        self.cb_language.addItem(t("跟随系统"), "auto")
        for code in i18n.SUPPORTED:
            self.cb_language.addItem(i18n.LANGUAGE_NAMES[code], code)
        self.cb_language.setCurrentIndex(
            max(0, self.cb_language.findData(str(cfg.get("language")) or "auto")))
        self.cb_language.currentIndexChanged.connect(self._on_language_changed)
        form.addRow(t("界面语言"), self.cb_language)
        layout.addLayout(form)

        # ---- 当前范围检索设置 ----
        search_title = QLabel(t("当前范围检索设置（只对当前范围生效）"))
        search_title.setObjectName("name")
        layout.addWidget(search_title)

        sform = QFormLayout()
        sform.setSpacing(8)
        sform.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.cb_content = QCheckBox(t("检索文件内容（关闭则只匹配文件名）"))
        sform.addRow("", self.cb_content)

        self.cb_match = QComboBox()
        self.cb_match.addItem(t("全部词（AND）"), "all")
        self.cb_match.addItem(t("任一词（OR）"), "any")
        self.cb_match.addItem(t("整段短语"), "phrase")
        sform.addRow(t("匹配方式"), self.cb_match)

        self.ext_list = QListWidget()
        self.ext_list.setObjectName("plain")
        self.ext_list.setFixedHeight(86)
        sform.addRow(t("只显示后缀"), self.ext_list)

        self.sp_limit = NoWheelSpinBox()
        self.sp_limit.setRange(1, 200)
        self.sp_limit.setSuffix(t(" 条"))
        self.sp_limit.setValue(60)
        sform.addRow(t("结果条数上限"), self.sp_limit)

        self.sp_snippet = NoWheelSpinBox()
        self.sp_snippet.setRange(30, 1000)
        self.sp_snippet.setSingleStep(50)
        self.sp_snippet.setSuffix(t(" 字符"))
        self.sp_snippet.setValue(100)
        sform.addRow(t("片段长度"), self.sp_snippet)

        note = QLabel(t("中文为逐字匹配，不支持全词；检索不分大小写。"))
        note.setObjectName("faint")
        note.setWordWrap(True)
        sform.addRow("", note)
        layout.addLayout(sform)

        hook_title = QLabel(t("全局右键检索"))
        hook_title.setObjectName("name")
        layout.addWidget(hook_title)
        hook_hint = QLabel(
            t("开启后，在其它应用里框选文字并右键，CiteDock 会读取选区供检索。"
            "右键行为本身不会被接管，原生菜单照常弹出。")
        )
        hook_hint.setObjectName("faint")
        hook_hint.setWordWrap(True)
        layout.addWidget(hook_hint)

        hook_row = QHBoxLayout()
        self.cb_mousehook = QCheckBox(t("开启全局右键检索（默认关闭）"))
        self.cb_mousehook.setChecked(bool(cfg.get("mousehook_enabled")))
        self.cb_mousehook.toggled.connect(self._update_hook_health_label)
        hook_row.addWidget(self.cb_mousehook)
        hook_row.addStretch(1)
        self.btn_mousehook_stop = QPushButton(t("一键停用"))
        self.btn_mousehook_stop.clicked.connect(
            lambda: self.cb_mousehook.setChecked(False)
        )
        hook_row.addWidget(self.btn_mousehook_stop)
        layout.addLayout(hook_row)

        hform = QFormLayout()
        self.ed_mousehook_exclude = QLineEdit(
            ", ".join(cfg.get("mousehook_exclude") or [])
        )
        self.ed_mousehook_exclude.setToolTip(
            t("这些进程里 Ctrl+C 是中断信号，绝不注入。按进程名（可含 .exe）逗号分隔。")
        )
        hform.addRow(t("排除进程"), self.ed_mousehook_exclude)
        self.lbl_mousehook_health = QLabel("")
        self.lbl_mousehook_health.setObjectName("faint")
        hform.addRow(t("健康状态"), self.lbl_mousehook_health)
        layout.addLayout(hform)
        self._update_hook_health_label(self.cb_mousehook.isChecked())

        where = QLabel(t("数据目录：%s") % config_mod.data_dir())
        where.setObjectName("faint")
        where.setWordWrap(True)
        layout.addWidget(where)

        maintenance = QHBoxLayout()
        self.btn_rebuild_db = QPushButton(t("重建索引库…"))
        self.btn_rebuild_db.setToolTip(
            t("索引库损坏打不开时用这个。\n"
            "会把 index.db 改名成带时间戳的备份（不删除），再重新建一个空库；\n"
            "源文件一个都不会碰，重建后照常重新扫描。")
        )
        self.btn_rebuild_db.clicked.connect(self._request_rebuild)
        maintenance.addWidget(self.btn_rebuild_db)
        maintenance.addStretch(1)
        layout.addLayout(maintenance)

        buttons = QDialogButtonBox()
        buttons.addButton(t("保存并重建索引"), QDialogButtonBox.AcceptRole)
        buttons.addButton(t("取消"), QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)   # 注意是 outer：固定在滚动区外面

        self._reload_scope_selector(select=self.cfg.get("active_scope"))

        # 内层两个列表不再自己滚（见 _WheelForwarder 的说明）
        self._wheel_forwarder = _WheelForwarder(scroll, self)
        for widget in (self.roots_list, self.ext_list):
            widget.installEventFilter(self._wheel_forwarder)

    def apply_theme(self):
        """重套主题。改主题后由外部调用 —— 否则要关掉重开面板才变。

        除了 QSS 还要写调色板：`QDialog { background }` 这条对独立顶层窗口
        在"app 级样式表 + widget 级样式表同时存在"时不总被绘制，
        系统是深色主题时这个对话框就会露出黑底（浅色模式下尤其明显）。
        QPalette.Window 是可靠的兜底。
        """
        name = self.cfg.get("theme")
        self.setAttribute(Qt.WA_StyledBackground, True)
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(theme.window_color(name)))
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        self.setStyleSheet(theme.build_qss(name, """
QLabel#faint { font-size: 11px; }
"""))

    # ---------- 范围管理 ----------

    def _index_of_name(self, name):
        for i, scope in enumerate(self.scopes):
            if scope.get("name") == name:
                return i
        return -1

    def _validate_scope_name(self, name, ignore=None):
        if not name:
            return t("范围名不能为空。")
        if len(name) > 12:
            return t("范围名不能超过 12 字符。")
        for scope in self.scopes:
            if scope.get("name") == name and scope is not ignore:
                return t("范围名「%s」已存在。") % name
        return ""

    def _unique_name(self, base, ignore=None):
        base = base.strip()[:12] or t("范围")
        candidate = base
        index = 2
        while self._validate_scope_name(candidate, ignore):
            suffix = "-%d" % index
            candidate = base[:12 - len(suffix)] + suffix
            index += 1
        return candidate

    def _save_scope_widgets(self, scope):
        scope["roots"] = self._root_paths()
        search = scope.setdefault("search", {})
        search["content"] = self.cb_content.isChecked()
        search["match"] = self.cb_match.currentData()
        search["ext_filter"] = self._selected_exts()
        search["limit"] = int(self.sp_limit.value())
        search["snippet_chars"] = int(self.sp_snippet.value())

    def _load_scope_widgets(self, scope):
        self.roots_list.clear()
        for path in (scope.get("roots") if scope else []) or []:
            self._add_root_item(path)
        self._refresh_stale_hint()
        search = (scope.get("search") or {}) if scope else {}
        self.cb_content.setChecked(bool(search.get("content", True)))
        idx = self.cb_match.findData(search.get("match", "all"))
        self.cb_match.setCurrentIndex(idx if idx >= 0 else 0)
        self.sp_limit.setValue(int(search.get("limit") or 60))
        self.sp_snippet.setValue(int(search.get("snippet_chars") or 100))
        self._reload_ext_options(scope)

    def _reload_scope_selector(self, select=None):
        if 0 <= self._current_index < len(self.scopes):
            self._save_scope_widgets(self.scopes[self._current_index])
        target = select if select is not None else self.cfg.get("active_scope")
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        for scope in self.scopes:
            self.scope_combo.addItem(scope["name"], scope["name"])
        idx = self._index_of_name(target)
        self.scope_combo.setCurrentIndex(idx)
        self.scope_combo.blockSignals(False)
        self._current_index = idx
        if 0 <= idx < len(self.scopes):
            self._load_scope_widgets(self.scopes[idx])
        else:
            self.roots_list.clear()
            self._refresh_stale_hint()
            self.cb_content.setChecked(True)
            self.cb_match.setCurrentIndex(0)
            self.sp_limit.setValue(60)
            self.sp_snippet.setValue(100)
            self._reload_ext_options(None)
        self._refresh_scope_buttons()

    def _on_scope_changed(self, new_index):
        if 0 <= self._current_index < len(self.scopes):
            self._save_scope_widgets(self.scopes[self._current_index])
        self._current_index = new_index
        if 0 <= new_index < len(self.scopes):
            self.cfg["active_scope"] = self.scopes[new_index]["name"]
            self._load_scope_widgets(self.scopes[new_index])
        else:
            self.cfg["active_scope"] = ""
            self.roots_list.clear()
            self._refresh_stale_hint()
            self.cb_content.setChecked(True)
            self.cb_match.setCurrentIndex(0)
            self.sp_limit.setValue(60)
            self.sp_snippet.setValue(100)
            self._reload_ext_options(None)
        self._refresh_scope_buttons()

    def _refresh_scope_buttons(self):
        has = 0 <= self._current_index < len(self.scopes)
        for button in (self.btn_rename_scope, self.btn_duplicate_scope,
                       self.btn_delete_scope):
            button.setEnabled(has)

    def _new_scope(self):
        name, ok = QInputDialog.getText(self, t("新建范围"), t("范围名（≤12 字符）："))
        if not ok:
            return
        name = name.strip()
        error = self._validate_scope_name(name)
        if error:
            QMessageBox.warning(self, t("无法新建范围"), error)
            return
        self._save_scope_widgets(self.scopes[self._current_index]) if 0 <= self._current_index < len(self.scopes) else None
        self.scopes.append({"name": name, "roots": [], "search": config_mod.default_search()})
        self.cfg["active_scope"] = name
        self._reload_scope_selector(select=name)

    def _rename_scope(self):
        if not (0 <= self._current_index < len(self.scopes)):
            return
        scope = self.scopes[self._current_index]
        name, ok = QInputDialog.getText(self, t("重命名范围"), t("新名称："), text=scope["name"])
        if not ok:
            return
        name = name.strip()
        error = self._validate_scope_name(name, ignore=scope)
        if error:
            QMessageBox.warning(self, t("无法重命名"), error)
            return
        self._save_scope_widgets(scope)
        scope["name"] = name
        self.cfg["active_scope"] = name
        self._reload_scope_selector(select=name)

    def _duplicate_scope(self):
        if not (0 <= self._current_index < len(self.scopes)):
            return
        self._save_scope_widgets(self.scopes[self._current_index])
        source = self.scopes[self._current_index]
        clone = copy.deepcopy(source)
        clone["name"] = self._unique_name(source["name"] + t("-副本"), ignore=None)
        self.scopes.append(clone)
        self.cfg["active_scope"] = clone["name"]
        self._reload_scope_selector(select=clone["name"])

    def _delete_scope(self):
        if not (0 <= self._current_index < len(self.scopes)):
            return
        scope = self.scopes[self._current_index]
        answer = QMessageBox.question(
            self, t("删除范围"),
            t("确定删除范围「%s」？\n\n只删这个范围，不会删任何文件，也不会删目录。")
            % scope["name"],
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        del self.scopes[self._current_index]
        self._current_index = -1
        self.cfg["active_scope"] = self.scopes[0]["name"] if self.scopes else ""
        self._reload_scope_selector(select=self.cfg["active_scope"])

    # ---------- 目录列表 ----------

    def _add_root_item(self, path):
        item = QListWidgetItem()
        item.setData(Qt.UserRole, path)
        if os.path.isdir(path):
            item.setText(path)
        else:
            item.setText(path + t(STALE_SUFFIX_KEY))
            item.setForeground(QColor("#E06C6C"))
            item.setToolTip(t("该目录不存在或不可访问，索引会忽略它。确认后可移除。"))
        self.roots_list.addItem(item)

    def _root_paths(self):
        return [self.roots_list.item(i).data(Qt.UserRole)
                for i in range(self.roots_list.count())]

    def _refresh_stale_hint(self):
        stale = sum(1 for p in self._root_paths() if not os.path.isdir(p))
        self.lbl_stale.setText(t("有 %d 个范围已失效") % stale if stale else "")

    def _artifact_root(self):
        try:
            return os.path.normcase(os.path.realpath(config_mod.artifact_dir()))
        except OSError:
            return ""

    def _add_root(self):
        chosen = QFileDialog.getExistingDirectory(self, t("选择要索引的目录"))
        if not chosen:
            return
        artifact = self._artifact_root()
        picked = os.path.normcase(os.path.realpath(chosen))
        if artifact and (picked == artifact or picked.startswith(artifact + os.sep)
                         or artifact.startswith(picked + os.sep)):
            QMessageBox.warning(
                self, t("该目录不能作为检索范围"),
                t("这是三个项目共用的产物根（%s）。\n\n"
                "把它加进检索范围会让产物被自己索引、再被当成输入重新处理 ——"
                "压缩场景下后果是摘要的摘要，语义逐层衰减。\n\n"
                "该目录已被无条件排除，请换一个目录。") % config_mod.artifact_dir(),
            )
            return
        existing = {os.path.normcase(p) for p in self._root_paths()}
        if picked in existing:
            return
        for path in self._root_paths():
            parent = os.path.normcase(path)
            if picked.startswith(parent + os.sep):
                QMessageBox.information(
                    self, t("已有父目录"),
                    t("该目录已被「%s」覆盖，无需重复添加。") % path,
                )
                return
        self._add_root_item(chosen)
        self._drop_children(chosen)
        self._refresh_stale_hint()

    def _drop_children(self, root):
        norm = os.path.normcase(root)
        for i in range(self.roots_list.count() - 1, -1, -1):
            text = self.roots_list.item(i).data(Qt.UserRole)
            if text == root:
                continue
            if os.path.normcase(text).startswith(norm + os.sep):
                self.roots_list.takeItem(i)

    def _remove_root(self):
        for item in self.roots_list.selectedItems():
            self.roots_list.takeItem(self.roots_list.row(item))
        self._refresh_stale_hint()

    # ---------- 后缀筛选 ----------

    def _norm(self, path):
        try:
            return os.path.normcase(os.path.realpath(path))
        except OSError:
            return os.path.normcase(path)

    def _reload_ext_options(self, scope):
        self.ext_list.clear()
        exts = []
        roots = [self._norm(p) for p in (scope.get("roots") if scope else []) or []]
        try:
            conn = indexer.connect(config_mod.db_path(), readonly=True)
            if roots:
                placeholders = ", ".join("?" * len(roots))
                exts = [r["ext"] for r in conn.execute(
                    "SELECT ext FROM files WHERE root IN (%s) GROUP BY ext ORDER BY ext"
                    % placeholders, roots)]
            else:
                exts = [r["ext"] for r in conn.execute(
                    "SELECT ext FROM files GROUP BY ext ORDER BY ext")]
            conn.close()
        except Exception:
            exts = []
        if "" not in exts:
            exts.append("")
        selected = (scope.get("search", {}).get("ext_filter") if scope else None) or []
        for ext in sorted(set(exts), key=lambda e: (e != "", e)):
            item = QListWidgetItem(ext if ext else t("（无扩展名）"))
            item.setData(Qt.UserRole, ext)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if ext in selected else Qt.Unchecked)
            self.ext_list.addItem(item)

    def _selected_exts(self):
        result = []
        for i in range(self.ext_list.count()):
            item = self.ext_list.item(i)
            if item.checkState() == Qt.Checked:
                result.append(item.data(Qt.UserRole))
        return result

    # ---------- 重建与保存 ----------

    def _on_language_changed(self, index):
        code = self.cb_language.itemData(index)
        if not code:
            return
        i18n.set_language(code)
        self.retranslate()

    def retranslate(self):
        """切换语言后刷新本面板。

        通用重绘够用：动态拼接出来的文案（如「有 3 个范围已失效」）认不出来，
        下次切范围/刷新时会自然变成新语言。
        """
        i18n.refresh(self, (QLabel, QPushButton, QCheckBox))
        self.setWindowTitle(t("CiteDock 设置"))
        self._refresh_stale_hint()

    def _request_rebuild(self):
        answer = QMessageBox.question(
            self, t("重建索引库"),
            t("将把现有 index.db 改名为带时间戳的备份（不删除），然后新建一个空库。\n\n"
            "源文件不会被读写，重建后会自动重新扫描一遍。\n\n确定继续？"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.rebuild_requested = True
            self.accept()

    def _update_hook_health_label(self, checked):
        self.lbl_mousehook_health.setText(
            t("已开启（异常时托盘图标会变色，并自动重装）") if checked else t("已关闭")
        )

    def _split(self, text):
        raw = (text or "").replace(t("，"), ",")
        return [part.strip() for part in raw.split(",") if part.strip()]

    def _save(self):
        hotkey = self.ed_hotkey.keySequence().toString() or "Ctrl+Alt+Space"
        select_hotkey = (self.ed_hotkey_select.keySequence().toString()
                         or "Ctrl+Alt+D")
        if select_hotkey == hotkey:
            QMessageBox.warning(self, t("无法保存"), t("两个热键不能相同"))
            return
        if 0 <= self._current_index < len(self.scopes):
            self._save_scope_widgets(self.scopes[self._current_index])
        self.cfg["scopes"] = self.scopes
        self.cfg["active_scope"] = (
            self.scopes[self._current_index]["name"]
            if 0 <= self._current_index < len(self.scopes) else ""
        )
        self.cfg["exclude_dirs"] = self._split(self.ed_exclude_dirs.text())
        self.cfg["exclude_globs"] = self._split(self.ed_exclude_globs.text())
        self.cfg["max_file_bytes"] = int(self.sp_max.value()) * 1024 * 1024
        self.cfg["max_index_chars"] = int(self.sp_max_chars.value())
        self.cfg["max_index_files"] = int(self.sp_max_files.value())
        self.cfg["hotkey"] = hotkey
        self.cfg["hotkey_select"] = select_hotkey
        self.cfg["pin_default"] = self.cb_pin.isChecked()
        self.cfg["auto_grab_clipboard"] = self.cb_clip.isChecked()
        self.cfg["offline_assert"] = self.cb_offline.isChecked()
        self.cfg["audit_enabled"] = self.cb_audit.isChecked()
        self.cfg["theme"] = self.cb_theme.currentData() or "auto"
        self.cfg["language"] = self.cb_language.currentData() or "auto"
        self.cfg["mousehook_enabled"] = self.cb_mousehook.isChecked()
        self.cfg["mousehook_exclude"] = self._split(self.ed_mousehook_exclude.text())
        self.saved = True
        self.accept()
