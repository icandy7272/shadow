"""日课：每天该做哪几步，哪些句子该复习。纯函数，不碰数据库。

内容来自「影子跟读日课」：工作日 30 分钟，周六回顾，周日只保住连续天数。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

REVIEW = "review"      # 链接：筛出该复习的句子
NEXT = "next"          # 链接：开始下一句没练过的
LOW_RATING = 2         # 盲听自评不超过这个分，算没听懂
SATURDAY, SUNDAY = 5, 6
WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


@dataclass(frozen=True, slots=True)
class Step:
    key: str
    title: str
    detail: str
    link: str | None = None


_EXTENSIVE = Step("extensive", "泛听", "碎片时间 10–20 分钟，原速，不查词，听懂大意就行")

_WEEKDAY = (
    Step("review", "复习昨天", "3–5 句，先盲听一遍；跟不上的，完整跟读一遍", REVIEW),
    Step("new", "精练新句子", "3–5 句：盲听 → 默写 → 看字跟读 → 不看字跟读", NEXT),
    Step("chain", "串起来", "今天练过的几句连着跟 2 遍，中间不停下来改"),
    Step("retell", "复述", "合上材料，用自己的话讲一遍，录下来回听"),
    _EXTENSIVE,
)

_SATURDAY = (
    Step("redo", "重练", "本周没听懂、问题没解决的句子，挑出来重练", REVIEW),
    Step("whole", "整段跟读", "本周练过的句子从头跟到尾，不中断"),
    Step("free_talk", "自由说", "挑本周学到的 3–5 个表达，就一个话题连着说 2 分钟，录音和上周对比"),
    _EXTENSIVE,
)

_SUNDAY = (
    Step("review", "复习 5 分钟", "只做一点复习，保住连续天数", REVIEW),
    Step("extensive", "泛听或休息", "想听就听，不想听就歇着"),
)


def steps_for(weekday: int) -> tuple[Step, ...]:
    """weekday 和 date.weekday() 一致：周一是 0。"""
    if weekday == SATURDAY:
        return _SATURDAY
    if weekday == SUNDAY:
        return _SUNDAY
    return _WEEKDAY


def heading(weekday: int) -> str:
    name = WEEKDAY_NAMES[weekday]
    if weekday == SATURDAY:
        return f"{name} · 回顾"
    if weekday == SUNDAY:
        return f"{name} · 轻松一天"
    return f"{name} · 30 分钟"


def is_step(weekday: int, key: str) -> bool:
    """这一步今天有没有。周六的「自由说」不能在周一勾。"""
    return any(step.key == key for step in steps_for(weekday))


def needs_review(last_day: date | None, today: date, *, issues: int,
                 rating: int | None) -> bool:
    """今天之前练过，并且昨天刚练、还有反复出现的问题、或者盲听没听懂。

    今天才练的不算：隔一天再复习才有效果。
    """
    if last_day is None or last_day >= today:
        return False
    return (last_day == today - timedelta(days=1) or issues > 0
            or (rating is not None and rating <= LOW_RATING))
