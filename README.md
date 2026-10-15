# CiteDock 引用坞

> **中文** —— 悬浮在桌面上的本地文件检索小坞。用关键词从你指定的目录里即时捞出相关文件，
> 一键复制路径或 `@` 引用，也可以把多份文档的正文合并成一份。**全程离线、源文件只读、不上传任何数据。**

> **English** — A floating search dock for your local files. Find files by keyword, copy them
> as paths or `@` citations, or merge their contents into a single document.
> **Fully offline, read-only on your files, nothing ever uploaded.**

| | |
|---|---|
| **平台 / Platform** | 仅 Windows（全局热键依赖 Win32 API）/ Windows only |
| **Python** | **3.10 或更高 / 3.10+** |
| **依赖 / Deps** | `PySide6`（必需）；`python-docx` / `pypdf`（可选，缺失时正文退化成只索引文件名）|
| **网络 / Network** | **不联网、不上传**；可开「离线断言」堵死本进程 socket / no network, nothing uploaded |
| **许可证 / License** | Apache-2.0 |

---

## 快速开始 / Quick Start

**1 · 装 Python 3.10+** — <https://www.python.org/downloads/windows/>
安装时勾选 *Add to PATH* / tick *Add to PATH* during install

**2 · 装依赖 / Install dependencies**（在 `cite-dock` 目录里 / inside the `cite-dock` folder）

```bat
python -m pip install -r requirements.txt
```

**3 · 启动 / Launch**

```bat
start-citedock.bat          :: 双击 / double-click
python run.py               :: 或命令行 / or from a terminal
```

找不到 Python 或缺少依赖时，`start-citedock.bat` 会**停下来说明原因**，不会闪退。
如果你有多个 Python，可以在 `cite-dock/` 下建一个 `.python-path` 文件，里面只写解释器的完整路径。

**4 · 首次使用 / First run**

唤出坞 → 点「设置 → 添加目录」选出要索引的文件夹 → 保存后自动建索引。
之后按热键 **`Ctrl+Alt+Space`**（可在设置里改）随时唤出。

---

## 目录结构 / Layout

```
.
├── cite-dock/       检索坞本体（PySide6）/ the dock itself
└── citedock_kit/    共享包（安全收口 / 取文器 / 文本工具）/ shared package
```

> ⚠️ **两个目录必须保持同级** —— `cite-dock` 靠兄弟目录定位 `citedock_kit`，
> 单独拿走其中一个会起不来。
>
> ⚠️ **Both folders must stay siblings** — `cite-dock` locates `citedock_kit` as its
> sibling directory; taking one without the other will not run.

---

## 功能 / Features

| 中文 | English |
|---|---|
| 关键词检索本地文件（FTS5 + 中文逐字切分，不受词长限制）| Keyword search over local files (FTS5 + per-character CJK tokenizing) |
| **复制路径** / **复制引用**：每行一个路径或 `@路径` | Copy as plain paths or `@path` citations, one per line |
| **复制内容**：把多份文件的正文合并成一份（上限 20 万字符，超限会点名而非静默丢弃）| Merge file bodies into one text (200k char cap; over-budget files are named, never silently dropped) |
| 文件内检索：在某一份文件里继续搜 | In-file search: drill into a single file |
| 全局热键唤出；可选「选区探测」 | Global hotkey; optional selection detection |
| 中英文界面、深/浅主题，均可跟随系统 | Chinese & English UI, dark/light theme; both can follow the system |
| 源文件全程只读；写入永不覆盖；审计日志 | Source files are read-only; writes never overwrite; audit log |

---

## 更多文档 / More

- 完整说明（安装细节、界面操作、检索原理、已知边界）/ Full guide: [`cite-dock/README.md`](cite-dock/README.md)
- 项目约定与硬约束（给参与开发者）/ Project rules: [`cite-dock/AGENTS.md`](cite-dock/AGENTS.md)

---

## 许可证 / License

[Apache License 2.0](cite-dock/LICENSE) © 2026 LeebertyQS
