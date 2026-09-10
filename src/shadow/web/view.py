"""把一次评估摊成前端画图要的纯数据。

网页不再收 PNG：图片里的字随图缩放，页面一宽就小得看不清。
这里只给几何，字由浏览器按页面字号渲染。
"""

from __future__ import annotations

from ..analysis.diff import accuracy as _accuracy
from ..analysis.diff import matched_pairs
from ..report import geometry


def _round(value):
    return None if value is None else round(value, 2)


def _block(block) -> dict:
    return {"text": block.text, "start": round(block.start, 4),
            "width": round(block.width, 4)}


def feedback_view(review, limit: int, *, audio: dict) -> dict:
    """图 1 的节奏几何 + 图 2 的音高格子，单位与命令行那张图完全一致。"""
    from .. import review as review_mod

    take = review.best
    flags, notes = review_mod.flags_for(review, limit)
    rhythm = geometry.rhythm_view(
        ref_words=review.ref_words, usr_words=take.words,
        rhythm=take.rhythm, pause_notes=notes,
    )
    slots = geometry.pitch_slots(
        ref_words=review.ref_words, usr_words=take.words,
        pairs=matched_pairs(take.tokens), ref_prosody=review.ref_prosody,
        usr_prosody=take.prosody, flags=flags,
    )
    return {
        "text": " ".join(w.text for w in review.ref_words),
        # 两条音轨各自第一个词从第几秒开始。同时播放时各自跳到这里，
        # 起点对齐了，图上同一个 x 才是同一刻。
        "audio": {**audio,
                  "refOffset": round(review.ref_words[0].start, 3),
                  "usrOffset": round(take.words[0].start, 3)},
        "accuracy": round(_accuracy(take.tokens) * 100),
        "speech": round(take.rhythm.speech_ratio, 2),
        "pause": (None if take.rhythm.pause_ratio is None
                  else round(take.rhythm.pause_ratio, 2)),
        "rhythm": {
            "seconds": round(rhythm.seconds, 4),
            "ref": [_block(b) for b in rhythm.ref],
            "usr": [_block(b) for b in rhythm.usr],
            "lags": [{"refAt": round(lag.ref_at, 4), "usrAt": round(lag.usr_at, 4),
                      "seconds": round(lag.seconds, 2), "marked": lag.marked}
                     for lag in rhythm.lags],
            "spans": [{"row": s.row, "start": round(s.start, 4),
                       "end": round(s.end, 4), "flag": s.flag}
                      for s in rhythm.spans],
        },
        "pitch": [
            {"text": s.text, "x": round(s.x, 5),
             "refWidth": round(s.ref_width, 5), "usrWidth": round(s.usr_width, 5),
             "refTrace": [_round(v) for v in s.ref_trace],
             "usrTrace": [_round(v) for v in s.usr_trace],
             "flag": s.flag}
            for s in slots
        ],
    }
