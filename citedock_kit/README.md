# citedock_kit · CiteDock 家族共享包

三个项目共用的一层薄公共代码。通过 `sys.path` 直接引用，**不做 pip 安装**（本地工具，零安装摩擦）。

---

## 为什么要有它

拆项目时共同的 4 个模块必须共用，否则会出现最糟的情况：**安全收口变成两处**。
`safeguard.py` 是整个家族唯一的安全边界（只读保证 / 白名单 / 永不覆盖 / 审计），
复制成两份意味着任何一处改漏都会破防，而且两份必然漂移。

所以：**共用代码单一来源，业务代码各自独立。**

---

## 里面有什么

| 模块 | 作用 | 谁在用 |
|---|---|---|
| `safeguard.py` | **安全收口**：`open_source()` 只读保证、`in_scope()` 白名单边界、`free_path()` 永不覆盖、`audit()` 审计 | cite-dock |
| `extract.py` | 取文器：txt/md/json/jsonl/docx/pdf → 纯文本，多编码兜底，缺依赖时降级不抛错 | cite-dock |
| `textutil.py` | CJK 逐字切分与还原、FTS5 查询表达式构造、token 估算、体积格式化 | cite-dock |
| `scanner.py` | 白名单范围内的目录遍历（排除规则 + 大小上限 + 逐项边界校验） | cite-dock |
| `paths.py` | 数据目录约定、原子写文本、兄弟目录定位 | cite-dock |

**刻意不放**：`config`（每个项目配置结构不同）、`indexer` / `search` / `keyword`（cite-dock 专有）、
任何 UI 代码。共用层越薄越不容易腐化。

---

## 怎么引用

在项目入口最前面插入一行：

```python
import os, sys
WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE)          # 让 citedock_kit 可导入

from citedock_kit import safeguard, extract, textutil
```

> 目录名用**下划线** `citedock_kit` 而不是连字符：Python 包名不能带连字符。
> 项目展示名（`cite-dock`）仍用连字符。

---

---

## 切换状态

**已完成。** cite-dock 的 `app/core/{safeguard,textutil,extract,scanner}.py` 已改为转发存根——
真实实现现在**只有一份**，就在本目录下。要改就改这里。

`app/_kitpath.py` 负责路径引导，所以 **run.py 与测试文件都不需要改**：存根自己会找到本包，
且路径由 `__file__` 推出，整棵目录换盘符换位置都不用动代码。

守卫脚本用来确认结构没有被破坏：

```bat
set PY=python
%PY% tests\parity_check.py
```

它检查两件事：① 每个共享模块的真实实现在 `citedock_kit/` 里存在；
② cite-dock 侧要么是**存根**、要么与 kit **逐字节一致**——两者都不是就说明实现被内联回了项目里、
安全收口重新分裂，脚本会报错。

**永远不要**在项目里重新内联这几个模块的实现。
