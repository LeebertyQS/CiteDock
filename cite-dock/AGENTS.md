# AGENTS.md — cite-dock / citedock_kit 硬约束

> **任何 Agent 在动这个项目的代码之前，必须先读完本文件。**  
> 本文件是硬约束的最终来源。

---

## 0. 这是什么

`<工作区>\` 下有四个目录，本文件管前两个：

| 目录                | 作用                          |
| ----------------- | --------------------------- |
| `citedock_kit/`   | **共享包**：安全收口、取文器、文本工具、路径约定  |
| `cite-dock/`      | **本地离线的悬浮检索坞**（PySide6 GUI） |

`cite-dock/app/core/{safeguard,textutil,extract,scanner}.py` **是转发存根**，  
真实实现在 `citedock_kit/` 下。**改存根没有用。**

```python
# 存根长这样，不要往里写实现
from .. import _kitpath
from citedock_kit.safeguard import *
```

---

## 1. 硬约束（违反任何一条都会**静默**出错）

| ID      | 约束                                                                                                                                  |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| **G-1** | `guard` 与索引**永远基于所有检索范围的所有根**。绝不能用"当前选中范围"的根 —— 那会让 `scanner` 把其他范围的文件判为越界丢弃，`sync_index` 的 `removed` 逻辑随即**把它们从索引里删掉**。切一次范围删一次。   |
| **G-2** | 任何"缩小结果集"的条件**必须进 SQL**（范围过滤、后缀筛选都算）。不允许"先取出 N 条再在 Python 里过滤" —— `LIMIT` 会被先吃掉。                                                    |
| **G-3** | **影响索引的设置不进检索范围**：`exclude_dirs` / `exclude_globs` / `max_file_bytes` / `max_index_chars` / `max_index_files` 留在全局。索引只有一份，做不到按范围区分。 |
| **G-4** | **源文件永远只读。** 所有源文件读取走 `Guard.open_source()`；任何写盘先过 `Guard.free_path()`（永不覆盖）。安全收口只有 `citedock_kit/safeguard.py` 一处。                 |
| **G-5** | **超限一律拒绝并告知，绝不静默截断。** 统计口径必须拆开：已索引 / 截断 / 取文失败 / 跳过。                                                                                |
| **G-6** | 用户可见的"状态"不能靠猜。范围、内容开关、后缀筛选这类"和默认不一样"的项，要在状态栏常显。                                                                                     |
| **G-7** | **`_output` 是保留目录名**（`<workspace>/_output`）。扫描器无条件排除，设置界面拒绝把它加进范围。                                                                  |
| **G-8** | **中文检索方案已定型**：CJK 逐字补空格 + `unicode61` + 短语查询。**不要退回 trigram**，改动前先读 `citedock_kit/textutil.py` 顶部注释。                                |

---

## 2. 代码纪律（都是踩过的坑）

1. **不要写死绝对路径** —— 一律用 `os.path.dirname(os.path.abspath(__file__))` 推算。踩过一次，迁移后直接 `ModuleNotFoundError`。
2. **FTS5 表有一个隐藏列叫 `rank`**。写 `ORDER BY rank` 会用**未加权**的 bm25，你 `AS rank` 的别名权重会静默失效。别名必须换名（现用 `match_rank`），`ORDER BY` 直接重复表达式。
3. **Qt：`setVisible(False)` 之后不能直接 `adjustSize()`** —— 子控件隐藏只排了一个 LayoutRequest 事件，此刻 `sizeHint()` 还是旧的。要先 `layout().activate()` 再 `adjustSize()`，见 `float_bar._relayout()`。
4. **httpx 0.28 的 `AsyncClient.send()` 不接受 `timeout=`** —— 要挂在 `build_request(...)` 上。（本项目 GUI 不用 httpx，）
5. **`QUrl` 在 PySide6 的 `QtCore`**，不在 `QtGui`。
6. **注释与字符串用 UTF-8**。写 `.ps1`/`.bat` 时注释只用 ASCII（中文会导致编码损坏吞掉换行）。
7. **顶层窗口的主题不能只写 QSS**。`QDialog { background }` 在"app 级样式表 + widget 级样式表

   同时存在"时对独立顶层窗口**不保证被绘制**，系统是深色主题时就会露出黑底

   （`WA_StyledBackground` 也救不了）。必须同时用 `theme.window_color()` 写进 `QPalette.Window`。

   `main.apply_theme()` 已经设了应用级调色板，**新建对话框直接用即可**，不要再单独造一套。
8. **`QCheckBox` 必须在 QSS 里显式给 `color`**。它不给就会用 Qt 默认调色板 —— 系统是深色时

   文字是白的，落在浅色卡片上根本看不清。任何"承载文字但没在 QSS 里设 color 的控件"都有这个坑。
9. **改热键用 `GlobalHotkey`，每个实例占一个独立 id**（`_NEXT_ID` 自动分配）。

   `register()` **失败会回滚到原来那个组合** —— 不要再写成"先 unregister 再 register、失败就算了"，

   那会让用户改坏一次就把两个热键都搞丢。
10. **往 class 文件里插代码后，要显式检查类结构**：`py_compile` 通过**不代表**方法还在类里

    （把模块级函数插在类中间会把后面的方法全挤出去）。改完跑一次

    `hasattr(YourClass, '某个方法名')` 或直接跑冒烟。
11. **Win32 坐标是物理像素，Qt 是逻辑像素 —— 两者不能混用**。这台机器缩放 1.25，

    混用会恒定偏 1.25 倍（右下角会把窗口推到屏幕外）。
    - 钩子回调里的 `MSLLHOOKSTRUCT.pt`、`GetCursorPos()` → **物理像素**
    - `QCursor.pos()`、`QWidget.move()`、`QScreen.geometry()` → **逻辑像素**
    - 要定位窗口就用 `QCursor.pos()`，**不要拿 Win32 的坐标直接 `move()`**
    - 夹取边界要用 `QGuiApplication.screenAt(pos)` 拿**光标所在屏**，不要用 `primaryScreen()`
12. **夹取/测量之前先 `ensurePolished()` + `layout().activate()`**。新建的 QWidget 还没

    polish，`sizeHint()` 偏小，拿它算出来的位置会出错（与第 3 条同源）。要用就取真实

    `width()/height()`。

---

### 2.1 界面文案必须走 i18n

改任何**用户可见**的文案，都要包一层 `t("中文原文")`，并把英文写进  
`app/i18n.py` 的 `ENGLISH` 表（**键就是中文原文**）。

```python
from ..i18n import t
self.btn.setText(t("取词"))
```

不用靠人记有没有漏 —— `%PY% cite-dock\tests\selftest_i18n.py` 会扫源码里所有 `t()`  
调用，缺英文直接失败。

三条硬规矩：

1. **不要在模块级调用 `t()`**（例如 `SUFFIX = t("…")`）—— 那发生在用户选语言之前，  
   会把文案**冻结**在装载时的语言上，之后切换语言它不会变。  
   需要常量就存原文：`SUFFIX_KEY = "…"`，用的时候 `t(SUFFIX_KEY)`。
2. **键就是中文原文**，不要再另外维护一份中文。
3. `core/keyword.py` 里的中文串是**中文停用词表**（功能数据），**绝对不要翻译** ——  
   翻了取词就废了。`_kitpath.py` 也不用翻（它的报错发生在 i18n 装载之前）。

## 3. 测试命令

先定义解释器（**必须用这个隔离 venv，不要用全局 Python**）：

```bat
set PY=python
```

| 命令                                      | 作用                          |   |                                          |                                               |
| --------------------------------------- | --------------------------- | - | ---------------------------------------- | --------------------------------------------- |
| `%PY% cite-dock\tests\selftest_core.py` | 核心链路 + 安全 + 检索口径（40+ 断言）    |   |                                          |                                               |
| `%PY% cite-dock\tests\selftest_i18n.py` | **多语言守卫**：漏翻、模块级 `t()`、往返切换 |   |                                          |                                               |
| `%PY% cite-dock\run.py --selftest`      | 窗口 / 托盘 / 热键 / 设置面板构建       |   | `%PY% cite-dock\tests\selftest_theme.py` | **主题覆盖 + 浮条定位**：浅/深色像素占比、QCheckBox 文字色、翻边夹取几何 |

| `set CITEDOCK_HOME=%TEMP%\citedock_agent && %PY% cite-dock\run.py --smoke` | 真实启动路径跑 1.2 秒                        |

| `%PY% cite-dock\tests\shot.py %TEMP%\cite_shots dark`                      | 样例语料 + 截图（`QWidget.grab()`，**不截桌面**） |

| `%PY% citedock_kit\tests\parity_check.py`                                  | 结构守卫：共享模块只允许"存根"或"与 kit 逐字节一致"       |

---

## 4. 禁止事项

1. **不要碰 `%LOCALAPPDATA%\CiteDock\`** —— 那是用户**真实在用的**配置与索引库（已索引 115 个文件）。
   - `tests/selftest_core.py` / `tests/shot.py` 自己会设 `CITEDOCK_HOME` 到 `%TEMP%` ✅
   - **但 `run.py --selftest` 与 `--smoke` 默认用真实目录** ⚠️ 跑它们时**必须**带 `CITEDOCK_HOME=%TEMP%\...`
2. **不要启动长期运行的实例** —— 用户可能正在用 CiteDock，它会占住全局热键 `Ctrl+Alt+Space` 和索引库。  
   跑完测试必须确认进程已退出（`pythonw.exe` 不应该残留）。
3. **不要删用户的任何文件**，也不要为了"清理"而删除。需要删时先问。
4. **不要扩大任务范围**。只做当前任务条目里写的事，不改无关文件。
5. **不要在项目里内联那 4 个共享模块的实现**（会被结构守卫抓住）。
6. **不要往 `_output\` 之外的地方写产物**；临时文件放 `%TEMP%`。

---

## 5. 完成任务后必须报告

1. 改了哪些文件（逐个列出）
2. 跑了哪些测试、结果如何（贴关键输出）
3. **已知风险与未解决的问题** —— 没解决就说没解决，不要含糊过去
4. 如果偏离了任务条目，说明原因
