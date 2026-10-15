# -*- coding: utf-8 -*-
"""CiteDock 家族共享包。

被 cite-dock 等桌面工具项目共用，
通过 sys.path 直接引用，不做 pip 安装（本地工具，零安装摩擦）。

内容只放「多项目共用且与业务无关」的东西：
    safeguard  安全收口（只读保证 / 白名单边界 / 永不覆盖 / 审计）
    extract    取文器（txt/md/json/jsonl/docx/pdf）
    textutil   CJK 逐字切分、FTS5 查询表达式、token 估算
    scanner    白名单范围内的目录遍历
    paths      运行期数据目录约定、原子写

刻意不放：config（每个项目有自己的配置结构）、indexer/search/keyword、
以及任何 UI —— 那些是单个项目专有的。
"""
__version__ = "1.1.0"

__all__ = ["safeguard", "extract", "textutil", "scanner", "paths"]
