# -*- coding: utf-8 -*-
"""纯文本工具。

中文检索的取舍：SQLite 自带的 unicode61 分词器不切中文，trigram 分词器又要求
查询词至少 3 个字符（"简历"这种 2 字词会直接搜不到）。这里的做法是——入库前把
每一个中日韩字符两侧补空格，让 unicode61 按“单字”建索引；查询时做同样变换并
用短语查询，于是 "迷宫生成" 变成 "迷 宫 生 成" 的相邻短语匹配，等价于子串匹配，
且不受词长限制、无需 jieba。
"""
from __future__ import annotations

import re

CJK_CLASS = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\u31f0-\u31ff\uac00-\ud7af"
CJK_RE = re.compile("[" + CJK_CLASS + "]")
_CJK_SUB = re.compile("[" + CJK_CLASS + "]")
_WS_RE = re.compile(r"\s+")

# 展示态需要还原的中文族字符：汉字 + 假名 + 谚文 + CJK 标点 + 全角符号。
# 只把“两侧都属于中文族”的空格吃掉，ASCII 与中文之间的空格保留（如 "SLG 品类"）。
WIDE_CLASS = (
    "\u3000-\u303f\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff"
    "\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef\uac00-\ud7af"
)
_DESPACE_RE = re.compile("(?<=[" + WIDE_CLASS + "]) (?=[" + WIDE_CLASS + "])")
_TIGHT_L = re.compile("(?<=[" + WIDE_CLASS + "]) (?=[\\-_./+|])")
_TIGHT_R = re.compile("(?<=[\\-_./+|]) (?=[" + WIDE_CLASS + "])")

# 换行在索引里换成一个可见的分隔符：unicode61 本来就把换行当分隔，检索行为不变，
# 但片段回显时能看出原来的断行位置，不会出现“标题黏正文”的糊句。
LINE_SEP = " \u00b7 "
_SEP_CHAR = LINE_SEP.strip()
_MULTI_SEP = re.compile(
    r"\s*%s(?:\s*%s)+" % (re.escape(_SEP_CHAR), re.escape(_SEP_CHAR))
)
_TERM_SPLIT = re.compile(r"[\s,，、;；|/\\]+")
_ASCII_TOK = re.compile(r"[0-9A-Za-z_]+")

MARK_L = "\x01"
MARK_R = "\x02"


def to_index_text(text):
    """入库文本：CJK 逐字加空格，行内空白折叠，换行转成可见分隔符。"""
    if not text:
        return ""
    spaced = _CJK_SUB.sub(lambda m: " " + m.group(0) + " ", text)
    spaced = re.sub(r"[ \t\f\v]+", " ", spaced)
    spaced = re.sub(r"(?:\r?\n)+", LINE_SEP, spaced)
    spaced = re.sub(r" +", " ", spaced)
    return spaced.strip()


def from_index_text(text):
    """展示文本：把逐字切开的中文重新拼回去，并清掉高亮标记内外的零余空格。"""
    if not text:
        return ""
    cleaned = _DESPACE_RE.sub("", text)
    cleaned = _TIGHT_R.sub("", _TIGHT_L.sub("", cleaned))
    cleaned = _MULTI_SEP.sub(LINE_SEP, cleaned)
    cleaned = cleaned.replace(" " + MARK_L, MARK_L).replace(MARK_R + " ", MARK_R)
    cleaned = cleaned.strip()
    if cleaned.startswith(_SEP_CHAR):
        cleaned = cleaned[1:].strip()
    if cleaned.endswith(_SEP_CHAR):
        cleaned = cleaned[:-1].strip()
    return cleaned


def build_query_expr(user_query, operator="AND"):
    """把用户输入转成 FTS5 查询表达式；没有有效词元时返回空串。"""
    if not user_query:
        return ""
    terms = [t for t in _TERM_SPLIT.split(user_query.strip()) if t]
    parts = []
    seen = set()
    for term in terms:
        if CJK_RE.search(term):
            spaced = to_index_text(term)
            if not spaced:
                continue
            key = "c:" + spaced
            if key in seen:
                continue
            seen.add(key)
            parts.append('"' + spaced.replace('"', '""') + '"')
        else:
            for token in _ASCII_TOK.findall(term):
                key = "a:" + token.lower()
                if key in seen:
                    continue
                seen.add(key)
                parts.append(token + "*")
    if not parts:
        return ""
    return (" %s " % operator).join(parts)


def build_phrase_expr(user_query):
    """把整段输入当作一个短语查询（CJK 逐字加空格后整体引用）。

    注意：英文里 `*` 是词前缀匹配，不是短语匹配；短语模式对英文是“相邻词组”的
    精确匹配，不加前缀通配。
    """
    if not user_query:
        return ""
    spaced = to_index_text(user_query)
    if not spaced:
        return ""
    return '"' + spaced.replace('"', '""') + '"'


def estimate_tokens(text):
    """粗略 token 估算：CJK 约 1 字 1 token，其余按 4 字符 1 token。"""
    if not text:
        return 0
    cjk = len(CJK_RE.findall(text))
    rest = max(0, len(text) - cjk)
    return int(cjk + rest / 4.0 + 0.5)


def human_size(num):
    units = ["B", "KB", "MB", "GB"]
    value = float(num or 0)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return "%d %s" % (int(value), unit)
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return "%d B" % int(num or 0)
