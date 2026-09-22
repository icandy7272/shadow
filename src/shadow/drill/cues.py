"""复述页的提示：每句挑一两个最有内容的词，按原文顺序排好。

复述要讲的是意思。原句摆在屏幕上就成了照着念；什么都不给，打开页面
又不知道从哪儿开口。几个关键词正好在中间：提醒讲到哪儿了，话得自己组织。
"""

from __future__ import annotations

import re
from typing import Sequence

CUE_LIMIT = 12          # 一屏看得完；再多就又成了背书
PER_SENTENCE = 2        # 一句给一两个就够想起来它在说什么

_TOKEN = re.compile(r"[A-Za-z][A-Za-z'\-]*|\d+")
_SELF = frozenset({"i", "i'm", "i've", "i'd", "i'll"})
# 动词后面跟着它才是那个意思：dropped out ≠ dropped
_PARTICLES = frozenset({"out", "up", "off", "away", "back", "down"})
# 虚词、代词、最常见的动词和副词：它们撑起句子，但提醒不了「这句在说什么」
_STOPWORDS = frozenset("""
a about above after again against all also am an and any are aren't as at be because been
before being below between both but by can can't cannot could couldn't did didn't do does
doesn't doing don't down during each even ever every few first for from further get gets
getting go goes going gone got gotten had hadn't has hasn't have haven't having he he'd he'll
he's her here here's hers herself him himself his how how's if in into is isn't it it's its
itself just know knew known let let's like made make many may me might more most much must
my myself never no nor not now of off on once one only or other our ours ourselves out over
own really said same say says see seem she she'd she'll she's should shouldn't so some such
than that that's the their theirs them themselves then there there's these they they'd
they'll they're they've thing things this those though through to today told too under
until up upon us very was wasn't way we we'd we'll we're we've well were weren't what what's
when when's where where's which while who who's whom why why's will with won't would
wouldn't yes yet you you'd you'll you're you've your yours yourself yourselves
across along already always among another anyone anything around behind beyond
everyone everything far later maybe much nothing often ones perhaps someone something
still toward towards within without
okay please pretty quite rather thank thanks
""".split()) | _SELF
# 最常见的动词和泛泛的名词、形容词：可以当提示，但排在不常见的实词后面。
# 实测「following · turned out」把 curiosity、intuition 挤掉了
_COMMON = frozenset("""
accept add allow appear ask become began begin begun believe bring brought build built buy
bought call came carry change come consider continue create cut decide die end expect fall
fallen feel felt fell find follow found gave give given grew grow grown happen held help
hold keep kept kill lead learn leave led left lie live look lose lost love meet met move
need offer open paid pay play provide pull push put reach read remain remember report run
ran sat seem send sent serve set show sit speak spend spent spoke stand start stay stood
stop suggest take taken talk tell think thought took tried try turn understand understood
use wait walk want watch win won work write written wrote
able bad best better big day great group hand hard head high home idea kind large last
life little long lot low man men next number old part people person place point problem
question real right side small sure time true week whole woman women world year
""".split())


def cues(sentences: Sequence[str], *, limit: int = CUE_LIMIT) -> list[str]:
    """按原文顺序给出关键词：专有名词连在一起，动词带上它的小品词，同一个词只给一次。"""
    # 句子多的时候一句只给一个：每句都给两个，上限用完时后面几句一个提示都没有
    per = max(1, min(PER_SENTENCE, limit // max(1, len(sentences))))
    given: set[str] = set()
    found: list[str] = []
    for sentence in sentences:
        for cue, is_name in _sentence_cues(sentence, given, per):
            given |= _key(cue, is_name)
            found.append(cue)
            if len(found) == limit:
                return found
    return found


def _bases(word: str) -> set[str]:
    """一个词可能的原形：stories → story，dropping → drop，taking → take。
    只是粗略地去词尾，够用来去重和认常见词，不求准。"""
    word = word.lower()
    found = {word}
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            stem = word[:-len(suffix)]
            found |= {stem, stem + "e"}
            if stem[-1] == stem[-2]:                 # stopped、dropping：双写的辅音
                found.add(stem[:-1])
    if word.endswith(("ies", "ied")) and len(word) > 4:
        found.add(word[:-3] + "y")
    return found


def _key(cue: str, is_name: bool) -> set[str]:
    """去重看什么：名字看它的每个词（给过 Stanford University，就不再单给 Stanford），
    别的看打头那个词的原形（dropped out 看 drop）。"""
    return set(cue.lower().split()) if is_name else _bases(cue.split()[0])


def _sentence_cues(sentence: str, given: set[str], per: int) -> list[tuple[str, bool]]:
    tokens = _TOKEN.findall(sentence.replace("’", "'"))
    candidates: list[tuple[int, bool, str]] = []      # (位置, 是不是专有名词, 提示)
    index = 0
    while index < len(tokens):
        # 句首的虚词只是因为在句首才大写（Then、And、So），不能拉着后面的名字连成一串
        leading = index == 0 and tokens[0].lower() in _STOPWORDS
        run = 0 if leading else _name_run(tokens, index)
        if run > 1 or (run == 1 and index > 0):
            candidates.append((index, True, " ".join(tokens[index:index + run])))
            index += run
            continue
        word = tokens[index].lower()
        if word not in _STOPWORDS and (len(word) >= 3 or word.isdigit()):
            after = tokens[index + 1].lower() if index + 1 < len(tokens) else ""
            candidates.append((index, False, f"{word} {after}" if after in _PARTICLES else word))
        index += 1

    fresh = [c for c in candidates if not _key(c[2], c[1]) & given]
    # 专有名词最能让人想起是哪一句；其次是不常见的词，同样不常见的挑长的——长词多半是实词。
    # 长短只量打头那个词：dropped out 不因为多带一个 out 就排到前面
    def rank(candidate):
        index, is_name, text = candidate
        head = text.split()[0]
        return (not is_name, not is_name and bool(_bases(head) & _COMMON), -len(head), index)
    chosen = sorted(fresh, key=rank)[:per]
    return [(text, is_name) for _, is_name, text in sorted(chosen)]


def _name_run(tokens: list[str], start: int) -> int:
    """从 start 起连着几个大写开头的词（「I」不算）。"""
    end = start
    while (end < len(tokens) and tokens[end][0].isupper()
           and tokens[end].lower() not in _SELF):
        end += 1
    return end - start
