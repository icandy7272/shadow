"""从筛选点进去练时，「下一句」在同一个筛选里找。纯函数，不碰数据库。

规则和首页列表上的筛选一模一样：列表里筛出来哪几句，一路点「下一句」走的就是哪几句。
连先后也一样——「该复习」在列表上按急迫程度排过，「下一句」就按同样的顺序走。
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
    due: date | None = None        # 下次该复习的日子，由练习记录一路算出来
    first_day: date | None = None  # 第一次练它是哪天：日课要数今天新练了几句


NEVER = State(runs=0, issues=0, rating=None, last_day=None)


@dataclass(frozen=True, slots=True)
class Selection:
    """一个筛选选中哪几句（列表里的下标），以及按什么先后走。"""

    order: tuple[int, ...] = ()
    deferred: tuple[int, ...] = ()   # 到期但超出今天的上限，顺延到以后
    resorted: bool = False           # order 不是原文顺序，而是排过急迫程度

    def flags(self, size: int) -> list[bool]:
        chosen = set(self.order)
        return [index in chosen for index in range(size)]


def parse(raw: str | None) -> str | None:
    """网址里带的筛选名。不认识的（包括「全部」）一律当作按原文顺序。"""
    return raw if raw in _WORDS else None


def matches(name: str, state: State, today: date) -> bool:
    if name == REVIEW:
        return plan.is_due(state.due, today)
    if name == ISSUES:
        return state.issues > 0
    if name == UNHEARD:
        return state.rating is not None and state.rating <= plan.LOW_RATING
    if name == FRESH:
        return state.runs == 0
    raise ValueError(f"没有这个筛选：{name}")


def select(name: str, states: Sequence[State], today: date, *,
           usable: Sequence[bool] | None = None) -> Selection:
    """这个筛选选中哪几句。

    「该复习」要整条列表一起算：到期的排一遍急迫程度，今天只做前 DAILY_REVIEW 句，
    剩下的顺延——不封顶的话，积压会滚雪球，最后每天都在读前面那几句。
    今天已经复习掉的占掉名额，免得练一句、后面又补上来一句，永远练不完。
    """
    fit = [index for index, state in enumerate(states)
           if (usable is None or usable[index]) and matches(name, state, today)]
    if name != REVIEW:
        return Selection(order=tuple(fit))
    fit.sort(key=lambda index: plan.urgency(
        due=states[index].due, today=today, issues=states[index].issues,
        rating=states[index].rating) + (index,))
    quota = max(plan.DAILY_REVIEW - _reviewed_today(states, today), 0)
    return Selection(order=tuple(fit[:quota]), deferred=tuple(fit[quota:]),
                     resorted=True)


def _reviewed_today(states: Sequence[State], today: date) -> int:
    """今天已经复习了几句。练过不止一轮、最后一轮在今天的，算复习过。"""
    return sum(1 for state in states if state.last_day == today and state.runs > 1)


def after(selection: Selection, position: int, *, wrap: bool = True) -> int | None:
    """队列里排在这一句后面的那句。走到头就回到队头——从中间点进来的，前面那些也要轮到。

    这一句已经不在队列里了（刚练完就不到期了、本来就不符合）时：
    按原文顺序走的队列接着往后找，排过急迫程度的队列直接给最急的那句。
    """
    order = selection.order
    if not order:
        return None
    if position in order:
        step = order.index(position) + 1
        if step < len(order):
            return order[step]
        return order[0] if wrap and order[0] != position else None
    if selection.resorted:
        return order[0]
    later = next((index for index in order if index > position), None)
    if later is not None:
        return later
    return order[0] if wrap else None


def before(selection: Selection, position: int) -> int | None:
    """队列里排在这一句前面的那句。不绕回队尾。"""
    order = selection.order
    if position in order:
        step = order.index(position)
        return order[step - 1] if step else None
    if selection.resorted:
        return None
    return max((index for index in order if index < position), default=None)


def remaining(selection: Selection, position: int) -> int:
    """除了正在练的这句，今天这个队列里还有几句。"""
    return len(selection.order) - (1 if position in selection.order else 0)


def view(name: str, *, remaining: int) -> dict:  # noqa: F811 - 参数和上面的函数同名，只在这里用
    title, label, done = _WORDS[name]
    return {"name": name, "title": title, "label": label, "done": done,
            "remaining": remaining, "query": f"?from={name}"}
