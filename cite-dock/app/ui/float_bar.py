# -*- coding: utf-8 -*-
"""转发存根：真实实现已拆分到 app/ui 下的独立模块。

保留本文件是为了让 `from app.ui.float_bar import DockWindow` 这类外部导入
一行都不用改（main.py / run.py / tests/shot.py / tests/selftest_theme.py 仍指向这里）。
"""
from .dock_window import DockWindow
from .selection_bar import SelectionBar

__all__ = ["DockWindow", "SelectionBar"]
