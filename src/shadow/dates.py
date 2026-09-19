"""页面上的日期写法。

同一个日期在练习页、素材库、生词本、录音列表四处露面，原来两种写法：
练习页带年份（2026-09-17），别处不带（09-17）。统一成不带年份，
不是今年的才写上——否则去年练的那句会被看成前天。
"""

from __future__ import annotations

from datetime import date, datetime


def day_label(stamp: str | date | datetime | None, today: date | None = None) -> str | None:
    """「09-17」；不是今年的写成「2025-09-17」。认不出来的原样返回。"""
    if not stamp:
        return None
    today = today or date.today()
    day = stamp
    if isinstance(stamp, str):
        try:
            day = datetime.fromisoformat(stamp).astimezone()
        except ValueError:
            return stamp
    if isinstance(day, datetime):
        day = day.date()
    return day.strftime("%m-%d") if day.year == today.year else day.strftime("%Y-%m-%d")
