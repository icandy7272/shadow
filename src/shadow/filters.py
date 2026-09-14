"""从筛选点进去练时，「下一句」在同一个筛选里找。纯函数，不碰数据库。

规则和首页列表上的筛选一模一样：列表里筛出来哪几句，一路点「下一句」走的就是哪几句。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from . import plan

REVIEW, ISSUES, UNHEARD, FRESH = "review", "issues", "unheard", "fresh"

# 筛选名 → (列表上的叫法, 「下一句」按钮, 走完时说什么)
_WORDS = {
    REVIEW: ("该复习", "复习下一句", "今天该复习的都练完了"),
    ISSUES: ("问题没解决", "问题没解决的下一句", "问题没解决的都过了一遍"),
    UNHEARD: ("没听懂", "没听懂的下一句", "没听懂的都过了一遍"),
    FRESH: ("没练过", "练下一句新的", "这份素材的句子都练过了"),
}


@dataclass(frozen=True, slots=True)
class State:
    """一句话练到了什么程度。"""

    runs: int
    issues: int
    rating: int | None
    last_day: date | None


NEVER = State(runs=0, issues=0, rating=None, last_day=None)


def parse(raw: str | None) -> str | None:
    """网址里带的筛选名。不认识的（包括「全部」）一律当作按原文顺序。"""
    return raw if raw in _WORDS else None


def matches(name: str, state: State, today: date) -> bool:
    if name == REVIEW:
        return plan.needs_review(state.last_day, today, issues=state.issues,
                                 rating=state.rating)
    if name == ISSUES:
        return state.issues > 0
    if name == UNHEARD:
        return state.rating is not None and state.rating <= plan.LOW_RATING
    if name == FRESH:
        return state.runs == 0
    raise ValueError(f"没有这个筛选：{name}")


def after(flags: Sequence[bool], position: int) -> int | None:
    """position 之后第一个符合的；后面没有就从头找——从中间点进来的，前面那些也要轮到。"""
    size = len(flags)
    for step in range(1, size):
        index = (position + step) % size
        if flags[index]:
            return index
    return None


def before(flags: Sequence[bool], position: int) -> int | None:
    return next((index for index in range(position - 1, -1, -1) if flags[index]), None)


def remaining(flags: Sequence[bool], position: int) -> int:
    """除了正在练的这句，还有几句符合。"""
    return sum(1 for index, flag in enumerate(flags) if flag and index != position)


def view(name: str, *, remaining: int) -> dict:  # noqa: F811 - 参数和上面的函数同名，只在这里用
    title, label, done = _WORDS[name]
    return {"name": name, "title": title, "label": label, "done": done,
            "remaining": remaining, "query": f"?from={name}"}
