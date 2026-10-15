# -*- coding: utf-8 -*-
"""关键词抽取：把一段话（或剪贴板内容）压缩成几个可检索的词。

目标不是做完整的 NLP，而是“够用的取词”：中文优先取较长片段，英文取整词，
滤掉高频虚词，并去掉互相包含的冗余候选。
"""
from __future__ import annotations

import re

from .textutil import CJK_RE

ASCII_RE = re.compile(r"[0-9A-Za-z_.\-]{2,}")
CJK_RUN_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]{2,}"
)

# 先按“功能词”把中文长句切开，剩下的片段才更接近用户真正关心的名词。
SPLIT_WORDS = (
    "帮我", "帮忙", "看看", "一下", "怎么", "什么", "如何", "为何", "哪些",
    "这个", "那个", "这些", "那些", "我们", "你们", "他们", "咱们",
    "可以", "需要", "应该", "可能", "因为", "所以", "但是", "如果", "然后",
    "现在", "已经", "还是", "或者", "以及", "并且", "而且", "请问",
    "麻烦", "谢谢", "的话", "时候", "知道", "觉得", "看到", "不要",
    "没有", "就是", "这样", "那样", "顺便", "对比", "关于", "对于",
    "能不能", "是不是", "有没有", "为什么", "怎样",
)

SINGLE_STOP = set(
    "的了是在和我你他她它们与就不也很都把被给让从到对个些这那吗呢吧啊呀"
    "着过有要会能而或及以并且于为所之其与何什么怎怎样"
)

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "you", "your", "are", "was",
    "have", "has", "not", "but", "can", "will", "from", "into", "about",
    "please", "help", "make", "using", "use", "get", "set", "new", "one",
    "一下", "一个", "一些", "问题", "内容", "东西", "地方", "感觉",
}

_SPLIT_RE = re.compile("|".join(sorted(SPLIT_WORDS, key=len, reverse=True)))
_SEP = "\x00"


def _cjk_chunks(run):
    """把一个中文长串切成候选关键词片段。"""
    marked = _SPLIT_RE.sub(_SEP, run)
    marked = "".join(_SEP if ch in SINGLE_STOP else ch for ch in marked)
    chunks = []
    for chunk in marked.split(_SEP):
        if len(chunk) < 2:
            continue
        if len(chunk) <= 10:
            chunks.append(chunk)
        else:
            chunks.append(chunk[:8])
    return chunks


def _candidates(text):
    scored = {}
    for token in ASCII_RE.findall(text):
        lowered = token.lower()
        if len(lowered) < 2 or lowered in STOPWORDS:
            continue
        scored[token] = max(scored.get(token, 0), len(token) + 3)
    for run in CJK_RUN_RE.findall(text):
        for chunk in _cjk_chunks(run):
            if chunk in STOPWORDS:
                continue
            scored[chunk] = max(scored.get(chunk, 0), len(chunk) + 1)
    return scored


def keywords_from_text(text, limit=4):
    if not text:
        return []
    scored = _candidates(text)
    if not scored:
        return []

    ordered = sorted(scored.items(), key=lambda item: (-item[1], -len(item[0])))
    picked = []
    for word, _score in ordered:
        if len(picked) >= limit:
            break
        if any(word in kept or kept in word for kept in picked):
            continue
        picked.append(word)
    return picked


def keywords_to_query(keywords):
    return " ".join(keywords)
