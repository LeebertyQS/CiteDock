# CiteDock 引用坞

**你记得内容，只是忘了它在哪个文件里。**

别再靠文件名找文档了。你记得那句话，就搜那句话。写东西最烦的不是没资料，是资料就在硬盘里，你找不到。翻文件夹翻半天，不如直接搜内容。

CiteDock 干的就是这件事：不搜文件名，搜正文。设定集、访谈纪要、会议记录、代码注释——只要那句话在文件里，就能把它连同文件一起捞出来。

**三步上手**

1. 按 `Ctrl+Alt+Space`，检索坞就地浮出
2. 把记得的那句话敲进去，结果直接给出命中片段，高亮就在眼前
3. 勾选要的文件：复制路径、复制 `@` 引用，或者把几份正文合并成一份——拿到的已经是能直接用的材料

点别处坞自动收起，需要钉住就按「常驻」。

**选区探测（可随时开关）**

更懒一点：在任意程序里框选或复制一段文字，坞自动弹出，这段话直接变成一次检索。复制、切窗口、粘贴、回车，四步省成一步。终端这类把 `Ctrl+C` 当中断信号的程序已被排除；探测前先备份剪贴板，用完恢复，你原来复制的东西不会丢。机制与排除列表见[详细文档](cite-dock/README.md)。

**两个提醒**

热键 `Ctrl+Alt+Space` 可能与个别软件冲突，唤不出就进设置换一个组合。选区探测涉及全局钩子，安全软件询问是否放行属正常现象。

---

**You remember the content — just not which file it's in.**

Stop searching by filename. Search by the sentence you remember. The worst part of writing isn't a lack of material — it's knowing the material is on your disk and still not finding it. Digging through folders for half an hour loses to searching the content directly.

That's what CiteDock does: it doesn't search filenames, it searches file bodies. Design docs, interview notes, meeting minutes, code comments — if the sentence is in a file, CiteDock pulls the file out with it.

**Three steps**

1. Press `Ctrl+Alt+Space` — the dock pops up right where you are
2. Type the sentence you remember — results show highlighted snippets
3. Tick the files you want: copy paths, copy `@` citations, or merge bodies into one text — ready to use

Click elsewhere and the dock tucks itself away; pin it if you want it to stay.

**Selection probe (toggleable)**

Even lazier: select or copy a passage in any program and the dock pops up, turning it into a search. Copy, switch windows, paste, Enter — four steps become one. Terminals that treat `Ctrl+C` as an interrupt are excluded; the clipboard is backed up before probing and restored after, so nothing you copied is lost. Mechanism and exclusion list in the [full guide](cite-dock/README.md).

**Two notes**

The hotkey `Ctrl+Alt+Space` may clash with some software — if it doesn't respond, change the combo in Settings. The probe uses a global hook; it's normal for security software to ask for permission.

---

| | |
|---|---|
| **平台 / Platform** | 仅 Windows（全局热键依赖 Win32 API）/ Windows only |
| **Python** | **3.10 或更高 / 3.10+** |
| **依赖 / Deps** | `PySide6`（必需）；`python-docx` / `pypdf`（可选，缺失时正文退化成只索引文件名）|
| **网络 / Network** | **不联网、不上传**；可开「离线断言」堵死本进程 socket / no network, nothing uploaded |
| **许可证 / License** | Apache-2.0 |

## 目录结构 / Layout

```
.
├── cite-dock/       检索坞本体（PySide6）/ the dock itself
└── citedock_kit/    共享包（安全收口 / 取文器 / 文本工具）/ shared package
```

> ⚠️ **两个目录必须保持同级** —— `cite-dock` 靠兄弟目录定位 `citedock_kit`，单独拿走其中一个会起不来。
>
> ⚠️ **Both folders must stay siblings** — `cite-dock` locates `citedock_kit` as its sibling directory; taking one without the other will not run.

## 安装 / Install

**1 · 装 Python 3.10+** — <https://www.python.org/downloads/windows/>（勾选 *Add to PATH* / tick *Add to PATH*）

**2 · 装依赖 / Install dependencies**（在 `cite-dock` 目录里 / inside the `cite-dock` folder）

```bat
python -m pip install -r requirements.txt
```

**3 · 启动 / Launch**

```bat
start-citedock.bat          :: 双击 / double-click
python run.py               :: 或命令行 / or from a terminal
```

找不到 Python 或缺少依赖时，`start-citedock.bat` 会停下来说明原因，不会闪退。多个 Python 可在 `cite-dock/` 下建 `.python-path` 文件指定解释器完整路径。

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

## 更多文档 / More

- 完整说明（安装细节、界面操作、检索原理、选区探测机制、已知边界）/ Full guide: [`cite-dock/README.md`](cite-dock/README.md)
- 项目约定与硬约束（给参与开发者）/ Project rules: [`cite-dock/AGENTS.md`](cite-dock/AGENTS.md)

## 许可证 / License

[Apache License 2.0](cite-dock/LICENSE) © 2026 LeebertyQS
