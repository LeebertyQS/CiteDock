# -*- coding: utf-8 -*-
"""后台线程：建索引（IndexWorker）、读正文供复制（CopyWorker）。"""
from PySide6.QtCore import QThread, Signal

from ..core import config as config_mod
from ..core import extract, indexer


class IndexWorker(QThread):
    progressed = Signal(int, int, str)
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, cfg, guard, parent=None):
        super().__init__(parent)
        self._cfg = dict(cfg)
        self._guard = guard
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            conn = indexer.connect(config_mod.db_path())
            rebuilt = indexer.init_db(conn)
            result = indexer.sync_index(
                conn,
                self._cfg,
                self._guard,
                progress=lambda done, total, name: self.progressed.emit(done, total, name),
                should_cancel=lambda: self._cancel,
            )
            result["schema_upgraded"] = rebuilt
            conn.close()
            self.done.emit(result)
        except Exception as exc:  # 后台线程不能把异常丢给 Qt
            self.failed.emit("%s: %s" % (type(exc).__name__, exc))

class CopyWorker(QThread):
    """在后台线程读取所选文件的正文，避免勾选多个大文件时卡死主线程。"""
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, items, budget, guard, parent=None):
        super().__init__(parent)
        self._items = items
        self._budget = budget
        self._guard = guard

    def run(self):
        try:
            texts = []
            too_big = []
            empty = []
            total = 0
            for item in self._items:
                text, error, _truncated = extract.read_for_copy(
                    item["path"], guard=self._guard
                )
                if error or not text:
                    empty.append(item["name"])
                    continue
                if total + len(text) > self._budget:
                    too_big.append(item["name"])
                    continue
                texts.append((item, text))
                total += len(text)
            self.done.emit({
                "texts": texts,
                "too_big": too_big,
                "empty": empty,
                "total": total,
                "budget": self._budget,
            })
        except Exception as exc:  # 后台线程不能把异常丢给 Qt
            self.failed.emit("%s: %s" % (type(exc).__name__, exc))
