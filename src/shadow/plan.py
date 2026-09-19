"""日课：每天该做哪几步，哪些句子该复习。纯函数，不碰数据库。

内容来自「影子跟读日课」：工作日 30 分钟，周六回顾，周日只保住连续天数。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

REVIEW = "review"      # 链接：筛出该复习的句子
NEXT = "next"          # 链接：开始下一句没练过的
CHAIN = "chain"        # 链接：把今天练过的几句连起来跟
WHOLE = "whole"        # 链接：把本周练过的连起来，从头跟到尾
TALK = "talk"          # 链接：自己开口说，在页面上录下来
CHAIN_ROUNDS = 2       # 串起来跟几遍
WHOLE_ROUNDS = 1       # 整段跟读跟几遍：从头到尾一遍，不中断
LOW_RATING = 2         # 盲听自评不超过这个分，算没听懂
GOOD_RATING = 4        # 到这个分，算听懂了
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
    Step("review", "复习到期的", "从上往下 3–5 句：先盲听一遍；跟不上的，完整跟读一遍", REVIEW),
    Step("new", "精练新句子", "3–5 句：盲听 → 默写 → 看字跟读 → 不看字跟读", NEXT),
    Step("chain", "串起来", "今天练过的几句连着跟 2 遍，中间不停下来改", CHAIN),
    Step("retell", "复述", "合上材料，用自己的话讲一遍，录下来回听", TALK),
    _EXTENSIVE,
)

_SATURDAY = (
    Step("redo", "重练", "到期的都过一遍：没听懂、问题没解决的排在最前面", REVIEW),
    Step("whole", "整段跟读", "本周练过的句子从头跟到尾，不中断", WHOLE),
    Step("free_talk", "自由说", "挑本周学到的 3–5 个表达，就一个话题连着说 2 分钟，录音和上周对比",
         TALK),
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


def week_start(day: date) -> date:
    """这一天所在那一周的周一。周六回顾要的「本周练过的」就是从这天算起。"""
    return day - timedelta(days=day.weekday())


# --- 自己开口说 -------------------------------------------------------------
#
# 跟读练的是「听清」和「说得像」，练不出「自己组织语言说出来」。所以每天留一段复述，
# 周六留一段自由说。两件事是同一台机器：挑好要用的话、连着说一段、录下来回头比。
# 步骤名就是录音的种类名，日课里那一步靠「今天录没录过」自己划掉。

FREE_TALK, RETELL = "free_talk", "retell"


@dataclass(frozen=True, slots=True)
class Talk:
    kind: str
    title: str
    seconds: int      # 说多久。到点自动停，早说完可以自己点
    span: str         # 页面上怎么写这个时长：「2 分钟」比「120 秒」好读
    lede: str


TALKS = {
    FREE_TALK: Talk(FREE_TALK, "自由说", 120, "2 分钟",
                    "挑本周学到的 3–5 个表达，就一个话题连着说 2 分钟。"
                    "说不顺也别停下来重来——录完和上周那段比，听的是能不能一直说下去。"),
    RETELL: Talk(RETELL, "复述", 90, "1 分半",
                 "合上材料，用自己的话把今天这段讲一遍。录完回听一遍，"
                 "把「想说却说不出」的地方记下来，明天去原句里找人家怎么说的。"),
}


def talk_for(weekday: int) -> Talk:
    """今天该说的是哪一种：周六自由说，别的日子复述。"""
    return TALKS[FREE_TALK if weekday == SATURDAY else RETELL]


# --- 复习排期 ---------------------------------------------------------------
#
# 每句话有自己的到期日，不是「练过的全部」每天从头读一遍。后者的毛病是：
# 最早练的那几句被复习得最多，而它们恰恰最熟；越靠后的越轮不到；
# 时间被旧句子吃光，新句子进不来。

NEW_SENTENCES = 3               # 「精练新句子」这一步：今天新练够这么多句就算做完
INTERVALS = (1, 3, 7, 14, 30)   # 复习间隔（天）。练对一次往后走一级
DAILY_REVIEW = 8                # 一天最多复习几句。多出来的顺延，不挤掉新句子

ONWARD, HOLD, AGAIN = "onward", "hold", "again"


def result_of(*, rating: int | None, issues: int) -> str:
    """一次练习的结果：往后推、原地不动、还是打回从头数。

    issues 是到这一次为止还挂着的问题——只做了盲听、没录音的那种轮次，
    上一次没解决的问题不会因此就算解决了。
    没打过分（跳过盲听）既不推进也不倒退：不知道不等于练好了。
    """
    if issues > 0 or (rating is not None and rating <= LOW_RATING):
        return AGAIN
    if rating is not None and rating >= GOOD_RATING:
        return ONWARD
    return HOLD


def next_level(level: int, result: str) -> int:
    """练完一次之后的间隔级别：INTERVALS 的下标，从 -1（没练过）开始。

    第一次练完是 0，也就是明天再来——和日课里「先复习昨天练的」对得上。
    """
    if result == AGAIN:
        return 0
    if result == ONWARD:
        return min(level + 1, len(INTERVALS) - 1)
    return max(level, 0)


def due_day(last_day: date, level: int) -> date:
    return last_day + timedelta(days=INTERVALS[max(level, 0)])


def is_due(due: date | None, today: date) -> bool:
    """该不该今天复习。没练过的没有到期日；今天才练的到期日在明天以后。"""
    return due is not None and due <= today


def urgency(*, due: date, today: date, issues: int,
            rating: int | None) -> tuple[int, int]:
    """排队用的先后：越小越先练。

    老问题没解决 → 盲听没听懂 → 单纯到期；同一档里逾期越久的越靠前。
    快忘掉的东西复习收益最高，而人的注意力在前几分钟最好。
    """
    if issues > 0:
        rank = 0
    elif rating is not None and rating <= LOW_RATING:
        rank = 1
    else:
        rank = 2
    return (rank, -(today - due).days)
