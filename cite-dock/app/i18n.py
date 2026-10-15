# -*- coding: utf-8 -*-
"""界面文案的中英切换。

## 为什么用「中文原文」当 key

不另造 `settings.title` 这种键名，直接把中文原文当键：

- **漏翻时自动回退到中文原文** —— 永远不会显示空白或键名（比显示 key 友好得多）
- 给现有中文代码补国际化是纯机械的：把字面量塞进 `t(...)` 就行，不用先起一套键名
- 代价：中文原文一改，英文会**静默失配**（回退成中文，不报错）
  → 所以配了 `tests/selftest_i18n.py`：扫源码里所有 `t("…")`，缺英文就直接失败

## 用法

    from .i18n import t, set_language, current
    label.setText(t("检索范围"))
    set_language("en")        # 运行中随时切；切完由各窗口调 retranslate()

## 不翻译的东西

- `core/keyword.py` 的 66 个中文串是**中文停用词表**，是功能数据，翻了取词就废了
- `_kitpath.py` 的报错发生在 i18n 装载**之前**（依赖缺失时的引导错误），只能保持原样
- `theme.py` 里的 QSS 文本不是给人读的句子
"""
from __future__ import annotations

import os
import sys

SUPPORTED = ("zh", "en")
DEFAULT = "zh"

_state = {"lang": DEFAULT}

# 语言名用**自称**显示，不随界面语言变化 —— 这样你在任何语言下都能认出自己的母语
LANGUAGE_NAMES = {"zh": "中文", "en": "English"}


def current() -> str:
    return _state["lang"]


def normalize(code) -> str:
    text = str(code or "").strip().lower()
    if text.startswith("zh") or text in ("cn", "chinese", "中文"):
        return "zh"
    if text.startswith("en") or text in ("english", "英文"):
        return "en"
    return DEFAULT


def set_language(code) -> str:
    _state["lang"] = resolve(code)
    return _state["lang"]


def detect_system_language() -> str:
    """跟随系统：Windows 读 UI 语言，其它平台读环境变量。

    旧实现只读 LC_ALL / LC_MESSAGES / LANG 三个环境变量 —— 在 Windows 上这几个
    几乎永远是空的（UI 语言在注册表里），所以永远回退成中文。英文用户第一次打开
    会看到全中文，这是分发的硬伤。
    """
    if sys.platform == "win32":
        try:
            import ctypes
            lang_id = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
            primary = lang_id & 0x3FF
            if primary == 0x04:   # 中文
                return "zh"
            if primary == 0x09:   # 英文
                return "en"
        except Exception:
            pass
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(key)
        if value:
            return normalize(value)
    return DEFAULT


def resolve(code) -> str:
    """把「auto / 跟随系统」解析成具体语言，其余照常 normalize。"""
    text = str(code or "").strip().lower()
    if text in ("auto", "system", "跟随系统", "follow system"):
        return detect_system_language()
    return normalize(text)


def t(text) -> str:
    if _state["lang"] == "zh" or not text:
        return text
    return ENGLISH.get(text, text)


def missing_english(text) -> bool:
    """供自检使用：这条原文有没有英文。"""
    return text not in ENGLISH


# ---------------------------------------------------------------------------
# 通用重绘
# ---------------------------------------------------------------------------
# 关键：**键就是中文原文**，所以不需要额外记录"控件最初的文案"。
# 把当前显示的文案先还原成中文，再按当前语言翻译即可，来回切换都不会跑偏。
# 两个中文键译成同一个英文（多对一）也不影响 —— 往返后结果一样。
#
# 反向表**惰性构建**：ENGLISH 定义在本文件下方，模块导入期就建会 NameError。
_reverse_cache = None


def _reverse():
    global _reverse_cache
    if _reverse_cache is None:
        _reverse_cache = {english: chinese for chinese, english in ENGLISH.items()}
    return _reverse_cache


def to_zh(text: str) -> str:
    return _reverse().get(text, text)


def refresh(root, widget_classes) -> int:
    """遍历控件，按当前语言刷新文案。返回改动的控件数。

    只处理有 text()/setText() 的控件（QLabel / QPushButton / QCheckBox / QAction）。
    动态拼接出来的文案（如"命中 3 个文件 · 索引共 115 个"）认不出来，
    会在下次重建时自然变成新语言 —— 这是可接受的。
    """
    changed = 0
    for cls in widget_classes:
        for widget in root.findChildren(cls):
            getter = getattr(widget, "text", None)
            setter = getattr(widget, "setText", None)
            if not callable(getter) or not callable(setter):
                continue
            try:
                current = getter()
            except (AttributeError, TypeError):
                continue
            if not current:
                continue
            new_text = t(to_zh(current))
            if new_text != current:
                setter(new_text)
                changed += 1
    return changed


# ---------------------------------------------------------------------------
# 英文词条
# ---------------------------------------------------------------------------
ENGLISH = {
    # ---- 悬浮坞 ----
    "CiteDock 引用坞": "CiteDock",
    "按住拖动；双击切换常驻": "Drag to move; double-click to toggle pin",
    "常驻": "Pin",
    "取消常驻": "Unpin",
    "常驻中：置顶且不随焦点隐藏，点一下取消":
        "Pinned: stays on top and ignores focus loss. Click to unpin.",
    "常驻显示": "Always on top",
    "开启后置顶显示、失焦也不隐藏": "Stay on top and ignore focus loss",
    "取词": "From clipboard",
    "从剪贴板提取关键词并检索": "Extract keywords from the clipboard and search",
    "输入关键词检索本地文件；或先复制一段话，再点「取词」":
        "Type keywords to search local files — or copy a passage, then click “From clipboard”",
    "设置": "Settings",
    "设置…": "Settings…",
    "收起": "Collapse",
    "展开结果面板": "Expand results panel",
    "收起结果面板": "Collapse results panel",
    "重建索引": "Rebuild index",
    "重建索引库": "Rebuild index database",
    "重建索引库（损坏时用）…": "Rebuild index database (if broken)…",
    "退出 CiteDock": "Quit CiteDock",

    # ---- 结果区 ----
    "全选": "Select all",
    "清空": "Clear",
    "已选 %d 项": "%d selected",
    "未选择": "Nothing selected",
    "复制路径": "Copy paths",
    "复制引用": "Copy references",
    "复制内容": "Copy content",
    "打开": "Open",
    "定位": "Reveal",
    "在资源管理器里选中该文件": "Reveal in File Explorer",
    "引用": " as references",
    "路径": " as paths",
    "已复制 %d 项%s到剪贴板。": "Copied %d item(s)%s to the clipboard.",
    "已复制 %d 个文件的正文，共 %d 字符 %s":
        "Copied the content of %d files, %d characters %s",
    "（%d 个无文本内容已跳过）": " (%d had no copyable text)",
    "所选文件没有可复制的文本内容。": "None of the selected files have copyable text.",
    "已取消复制：所选正文合计会超过 %d 字符上限。放不下的有：%s\n"
    "请取消勾选其中几项或分批复制。源文件未被改动。":
        "Copy cancelled: the selection exceeds the %d-character limit. Did not fit: %s\n"
        "Uncheck a few files, or copy in batches. Your source files are untouched.",
    "正在读取 %d 个文件的正文…": "Reading %d files…",
    "读取正文失败：%s": "Failed to read file: %s",

    # ---- 结果行标签 ----
    "文件名命中": "filename match",
    "文件名命中（%d）": "Filename matches (%d)",
    "内容命中（%d）": "Content matches (%d)",
    "内容也命中": "content matches too",
    "正文仅索引前半段": "only the first part is indexed",
    "文件已不存在": "file missing",
    "索引里有它，但磁盘上已经不在了 —— 建议重建索引，或确认文件是否被改名/移动。":
        "It is in the index but no longer on disk — rebuild the index, "
        "or check whether the file was renamed or moved.",
    '<span style="color:#E06C6C">索引里有它，但磁盘上已经不在了 —— '
    '建议重建索引，或确认文件是否被改名/移动。</span>':
        '<span style="color:#E06C6C">It is in the index but no longer on disk — '
        'rebuild the index, or check whether the file was renamed or moved.</span>',
    "任一词": "Any word",
    "二进制文件": "Binary file",

    # ---- 状态栏 ----
    "命中 %d 个文件 · 索引共 %d 个": "%d matches · %d files indexed",
    "未全部命中，已按任一关键词放宽": "Not all terms matched; relaxed to any term",
    "宽松检索（关键词来自取词）": "Loose search (keywords came from the clipboard)",
    "其中 %d 个已不存在": "%d missing on disk",
    "已索引 %d 个文件": "%d files indexed",
    "%d 个正文仅索引前半段": "%d only partly indexed",
    "%d 个取文失败": "%d failed to extract",
    "%d 个被跳过": "%d skipped",
    "更新于 %s": "updated %s",
    "范围：%s": "Scope: %s",
    "范围": "Scope",
    "仅文件名": "filenames only",
    "后缀 %s": "extensions %s",
    "索引完成：": "Indexing finished: ",
    "新增 %d": "%d added",
    "更新 %d": "%d updated",
    "移除 %d": "%d removed",
    "正文截断 %d": "%d truncated",
    "取文失败 %d": "%d failed to extract",
    "跳过 %d（%s）": "%d skipped (%s)",
    "耗时 %.1fs": "took %.1fs",
    "正在建立索引…": "Building the index…",
    "正在扫描目录…": "Scanning folders…",
    "正在索引 %d / %d  %s": "Indexing %d / %d  %s",
    "索引失败：%s": "Indexing failed: %s",
    "索引正在更新：此刻的结果是半成品（部分新、部分旧），请等它跑完再下结论。":
        "The index is updating: results are incomplete (a mix of old and new). "
        "Wait for it to finish before drawing conclusions.",
    "索引结构已升级，已重建。": "Index schema upgraded; the index was rebuilt.",
    "索引库已重建，正在重新扫描…": "Index database rebuilt; rescanning…",
    "旧索引库已备份为：%s": "Old index database backed up as: %s",
    "重建索引库失败：%s（可能仍被别的进程占用）":
        "Rebuild failed: %s (the database may still be locked by another process)",
    "扫描达到文件数上限（%s）已提前停止 —— 结果不完整，请缩小检索范围或到设置里调高上限":
        "Scan stopped at the file limit (%s) — results are incomplete. "
        "Narrow the scope, or raise the limit in Settings.",
    "扫描达到文件数上限（%d）已提前停止，请缩小检索范围或调高上限":
        "Scan stopped at the file-count limit (%d). Narrow the scope or raise the limit.",
    "多数文件时间戳集中在同一天，新近排序已弱化":
        "Most files share the same timestamp, so recency ranking is weakened",

    # ---- 空态 / 提示 ----
    "第一次使用：点「设置」→「添加目录」，选一个要索引的文件夹。":
        "First run — open Settings → Add folder, then pick a folder to index.",
    "配置里的目录现在都不存在了（%s），可能被移动、删除或改了盘符 —— 点「设置」重新选择。":
        "The folders in your config no longer exist (%s); they may have been moved, "
        "deleted, or renamed — reopen Settings to pick them again.",
    " 等 %d 个": " and %d more",
    "尚未设置检索范围：点「设置」选择要索引的目录。":
        "No search scope yet — open Settings and pick a folder to index.",
    "当前范围没有检索目录：请在设置里添加目录。":
        "This scope has no folders — add one in Settings.",
    "索引为空，点「设置」选择目录后会自动建立索引。":
        "The index is empty — pick a folder in Settings and it will be built automatically.",
    "索引库不可用 —— 可在「设置」里点「重建索引库」。":
        "The index database is unavailable — use “Rebuild index database” in Settings.",
    "没有命中「%s」的文件。换个词，或先重建索引。":
        "No files matched “%s”. Try another term, or rebuild the index first.",
    "检索出错：%s": "Search error: %s",
    "剪贴板里没有可用的文本。": "No usable text in the clipboard.",
    "没能从剪贴板里提取出关键词。": "Could not extract keywords from the clipboard.",
    "已取词「%s」 · %s": "Keywords “%s” · %s",
    "「%s」": "“%s”",

    # ---- 文件内检索 ----
    "文件内检索": "In-file search",
    "在文件内检索（不支持正则）": "Search within the file (no regular expressions)",
    "返回": "Back",
    "命中 %d 处": "%d hits",
    "命中 0 处": "No hits",
    "，展示前 200": ", showing the first 200",
    "第 %d 条": "message %d",
    "第 %d 段": "paragraph %d",
    "复制该段": "Copy this passage",
    "已复制该段。": "Passage copied.",
    "已复制选中内容。": "Selection copied.",
    "文件内没有命中「%s」。": "No matches for “%s” in this file.",
    "内容已变更，以下为最新版本": "The file has changed; showing the latest version",
    "无法检索该文件：%s": "Cannot search this file: %s",

    # ---- 右键浮条 ----
    "用引用坞检索这段": "Search this in CiteDock",
    "只填关键词": "Fill keywords only",
    "复制这段": "Copy selection",
    "用选中的文字检索「%s」": "Search for “%s”",

    # ---- 设置面板 ----
    "CiteDock 设置": "CiteDock Settings",
    "范围": "Scope",
    "新建": "New",
    "重命名": "Rename",
    "复制": "Duplicate",
    "删除": "Delete",
    "新建范围": "New scope",
    "重命名范围": "Rename scope",
    "删除范围": "Delete scope",
    "无法新建范围": "Cannot create the scope",
    "无法重命名": "Cannot rename",
    "范围名不能为空。": "The scope name cannot be empty.",
    "范围名不能超过 12 字符。": "The scope name cannot exceed 12 characters.",
    "范围名「%s」已存在。": "A scope named “%s” already exists.",
    "范围名（≤12 字符）：": "Scope name (≤12 characters):",
    "新名称：": "New name:",
    "-副本": "-copy",
    "确定删除范围「%s」？\n\n只删这个范围，不会删任何文件，也不会删目录。":
        "Delete the scope “%s”?\n\nThis only removes the scope. "
        "No files and no folders are deleted.",
    "检索目录": "Folders",
    "只有列出的目录会被扫描。范围之外的路径一律拒绝；切换范围时改动会自动保存。":
        "Only the listed folders are scanned. Paths outside the scope are always "
        "rejected. Changes are saved when you switch scopes.",
    "添加目录…": "Add folder…",
    "移除选中": "Remove selected",
    "选择要索引的目录": "Choose a folder to index",
    "有 %d 个范围已失效": "%d folders are missing",
    "    ← 目录不存在，索引会忽略它": "    ← folder missing; the index ignores it",
    "该目录不存在或不可访问，索引会忽略它。确认后可移除。":
        "This folder does not exist or is not accessible; the index ignores it. "
        "You can remove it.",
    "该目录不能作为检索范围": "This folder cannot be a search scope",
    "已有父目录": "A parent folder is already added",
    "该目录已被「%s」覆盖，无需重复添加。":
        "It is already covered by “%s”, so there is no need to add it again.",
    "这是三个项目共用的产物根（%s）。\n\n"
    "把它加进检索范围会让产物被自己索引、再被当成输入重新处理 ——"
    "压缩场景下后果是摘要的摘要，语义逐层衰减。\n\n"
    "该目录已被无条件排除，请换一个目录。":
        "This is the artifact root shared by all three projects (%s).\n\n"
        "Adding it to a search scope makes artifacts index themselves, then get "
        "treated as input again — in the compression case that means summaries of "
        "summaries, with semantics decaying layer by layer.\n\n"
        "The folder is excluded unconditionally. Please pick another one.",

    "全局设置（影响索引，对所有范围生效）":
        "Global settings (they affect the index and apply to every scope)",
    "排除目录名": "Excluded folder names",
    "排除文件类型": "Excluded file types",
    "单文件索引上限": "Max file size",
    "超过这个体积的文件整份不索引（会在状态栏如实报出数量）":
        "Files larger than this are skipped entirely (the count is reported in the status bar)",
    "单文件正文上限": "Max indexed text per file",
    "单文件正文索引到这里为止；被截断的文件会在结果里标注":
        "Text is indexed up to this length; truncated files are flagged in the results",
    "索引文件数上限": "Max indexed files",
    "扫描到这么多文件就停下并提示（0 = 不限）。\n防的是误把整个磁盘加进检索范围。":
        "Stop and warn once this many files have been found (0 = unlimited).\n"
        "This guards against accidentally adding a whole drive to a scope.",
    "唤起热键": "Hotkey",
    "启动后默认常驻（置顶、不随焦点隐藏）": "Start pinned (always on top, ignore focus loss)",
    "唤起时自动从剪贴板取关键词": "Grab keywords from the clipboard when summoned",
    "离线断言：启动即切断本进程的全部网络能力":
        "Offline assertion: cut all network access for this process at startup",
    "记录审计日志（索引与写入来源）": "Write an audit log (indexing and write origins)",
    "跟随系统": "Follow system",
    "界面主题": "Theme",
    "界面语言": "Language",
    "深色": "Dark",
    "浅色": "Light",
    " 个": " files",
    " 字符": " chars",
    " 条": " results",
    "MB": " MB",
    "数据目录：%s": "Data folder: %s",
    "重建索引库…": "Rebuild index database…",
    "索引库损坏打不开时用这个。\n会把 index.db 改名成带时间戳的备份（不删除），再重新建一个空库；\n"
    "源文件一个都不会碰，重建后照常重新扫描。":
        "Use this when the index database is broken and cannot be opened.\n"
        "index.db is renamed to a timestamped backup (nothing is deleted) and a "
        "fresh empty database is created.\nNo source file is ever touched; a full "
        "rescan runs afterwards.",
    # float_bar 里的版本与设置面板里的措辞不同，两条都要有（键是原文，措辞不同就是两条）
    "将把现有 index.db 改名为带时间戳的备份（不删除），再新建一个空库。\n\n"
    "源文件不会被读写，重建后会自动重新扫描。确定继续？":
        "index.db will be renamed to a timestamped backup (nothing is deleted), "
        "and a fresh empty database will be created.\n\n"
        "Your source files are never read or written, and a full rescan runs "
        "afterwards. Continue?",
    "将把现有 index.db 改名为带时间戳的备份（不删除），然后新建一个空库。\n\n"
    "源文件不会被读写，重建后会自动重新扫描一遍。\n\n确定继续？":
        "index.db will be renamed to a timestamped backup (nothing is deleted), "
        "and a fresh empty database will be created.\n\n"
        "Your source files are never read or written, and a full rescan runs "
        "afterwards.\n\nContinue?",
    "保存并重建索引": "Save and rebuild index",
    "取消": "Cancel",
    "全局右键检索": "Global right-click search",
    "开启后，在其它应用里框选文字并右键，CiteDock 会读取选区供检索。"
    "右键行为本身不会被接管，原生菜单照常弹出。":
        "When enabled, select text in another app and right-click: CiteDock reads "
        "the selection for searching. Right-click itself is not hijacked — the "
        "native menu still appears.",
    "开启全局右键检索（默认关闭）": "Enable global right-click search (off by default)",
    "一键停用": "Disable now",
    "排除进程": "Excluded processes",
    "这些进程里 Ctrl+C 是中断信号，绝不注入。按进程名（可含 .exe）逗号分隔。":
        "In these processes Ctrl+C is an interrupt signal, so nothing is injected. "
        "Comma-separated process names (.exe allowed).",
    "健康状态": "Health",
    "已关闭": "Off",
    "已开启（异常时托盘图标会变色，并自动重装）":
        "On (the tray icon turns amber and it reinstalls automatically if it fails)",
    "当前范围检索设置（只对当前范围生效）":
        "Search settings for this scope (they apply to this scope only)",
    "检索文件内容（关闭则只匹配文件名）": "Search file content (off = filenames only)",
    "匹配方式": "Matching",
    "全部词（AND）": "All words (AND)",
    "任一词（OR）": "Any word (OR)",
    "整段短语": "Exact phrase",
    "只显示后缀": "Show only these extensions",
    "（无扩展名）": "(no extension)",
    "结果条数上限": "Max results",
    "片段长度": "Snippet length",
    "中文为逐字匹配，不支持全词；检索不分大小写。":
        "Chinese is matched character by character (no whole-word search); "
        "matching is case-insensitive.",

    # ---- 标点分隔符（中文全角 → 英文半角）----
    "，": ", ",
    "、": ", ",
    "；": "; ",
    " ｜ ": " | ",

    # ---- 热键检索选区 ----
    "检索选中文字": "Search selected text",
    "在任意程序里选中文字后按它，CiteDock 会读走选区供检索": 
        "Select text anywhere, then press this: CiteDock reads the selection for searching",
    "没拿到选区：%s": "No selection: %s",
    "这个程序在排除列表里（终端里 Ctrl+C 是中断信号），已跳过":
        "This program is on the exclude list (Ctrl+C is an interrupt signal in terminals) — skipped",
    "剪贴板里是图片或文件，已跳过探测（不会把它清掉）":
        "The clipboard holds an image or files — probe skipped (they are not cleared)",
    "这个程序没有响应 Ctrl+C，读不到选区（也可能你没选中文字）":
        "This program did not respond to Ctrl+C, so the selection could not be read "
        "(or nothing was selected)",
    "没有检测到选中的文字": "No selected text detected",
    "选中的内容超过 5000 字符，已跳过（可能是不小心全选了）":
        "The selection exceeds 5000 characters — skipped (you may have selected everything)",
    "两个热键不能相同": "The two hotkeys must be different",
    "无法保存": "Cannot save",
    "可以在设置里换一个组合。": "You can pick another combination in Settings.",
    "「%s」%s 注册失败（可能被其它程序占用）%s":
        "Could not register %s “%s” (another program may have taken it)%s",
    "，已保留原来的 %s": ", kept the previous %s",

    # ---- 托盘 ----
    "CiteDock 引用坞 —— 全局钩子异常，正在尝试恢复":
        "CiteDock — the mouse hook failed; attempting to recover",
    "显示 / 隐藏悬浮坞": "Show / hide the dock",

    # ---- 配置校验（会以对话框形式出现）----
    "scopes 必须是数组": "scopes must be an array",
    "第 %d 个检索范围不是对象": "scope #%d is not an object",
    "第 %d 个检索范围的名字为空": "scope #%d has an empty name",
    "检索范围名「%s」超过 12 字符": "scope name “%s” exceeds 12 characters",
    "检索范围名「%s」重复": "duplicate scope name “%s”",
    "检索范围「%s」没有检索目录（roots 为空）": "scope “%s” has no folders (roots is empty)",
    "提示：active_scope「%s」不存在，已回退到「%s」":
        "Note: active_scope “%s” does not exist; fell back to “%s”",
    "默认": "Default",
    "（无）": "(none)",
    "CiteDock 处于离线模式，已切断网络能力":
        "CiteDock is in offline mode; network access is blocked",
    "全局热键 %s 注册失败（可能被其它程序占用）。\n可以从托盘图标打开，或在设置里换一个组合。":
        "Could not register the hotkey %s (another program may have taken it).\n"
        "Open the dock from the tray icon, or choose another combination in Settings.",
}
