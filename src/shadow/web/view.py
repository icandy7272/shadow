"""把一次评估摊成前端画图要的纯数据。

网页不再收 PNG：图片里的字随图缩放，页面一宽就小得看不清。
这里只给几何，字由浏览器按页面字号渲染。
"""

from __future__ import annotations

from ..analysis.diff import accuracy as _accuracy
from ..analysis.diff import matched_pairs, spoken_pairs
from ..analysis.prosody import word_pitch, word_trace, level_gap, terminal_fall
from ..report import geometry


def _round(value):
    return None if value is None else round(value, 2)


def _block(block) -> dict:
    return {"text": block.text, "start": round(block.start, 4),
            "width": round(block.width, 4), "matched": block.matched}


def _take_view(review, take, limit: int, audio: dict) -> dict:
    """一遍录音的两张图。每一遍都算，让人自己挑着看。"""
    from .. import review as review_mod

    flags, notes = review_mod.flags_for(review, limit, take)
    pairs = matched_pairs(take.tokens)
    rhythm = geometry.rhythm_view(
        ref_words=review.ref_words, usr_words=take.words,
        rhythm=take.rhythm, pause_notes=notes, pairs=pairs,
    )
    # 图 2 只是把音高摆在一起看：读成别的词也是在这个位置出了声，照样画
    slots = geometry.pitch_slots(
        ref_words=review.ref_words, usr_words=take.words,
        pairs=spoken_pairs(take.tokens), ref_prosody=review.ref_prosody,
        usr_prosody=take.prosody, flags=flags,
    )
    uncertain_issues = []
    matching = dict(pairs)
    for index, ref in enumerate(review.ref_words):
        usr_index = matching.get(index)
        if usr_index is None:
            continue
        usr = take.words[usr_index]
        rp = word_pitch(review.ref_prosody, ref.start, ref.end)
        up = word_pitch(take.prosody, usr.start, usr.end)
        if level_gap(word_trace(review.ref_prosody, ref.start, ref.end),
                     word_trace(take.prosody, usr.start, usr.end)) is None:
            uncertain_issues.append(f"pitch_off:{index}")
        if rp is None or up is None or rp.move is None or up.move is None:
            uncertain_issues.extend((f"flat_rise:{index}", f"flat_fall:{index}"))
        if index == len(review.ref_words) - 1:
            fall_key = f"flat_fall:{index}"
            if fall_key in uncertain_issues:
                uncertain_issues.remove(fall_key)
            if (terminal_fall(review.ref_prosody, review.ref_words) is None
                    or terminal_fall(take.prosody, take.words) is None
                    or (index > 0 and (matching.get(index - 1) != usr_index - 1
                                       or index - 1 in review.shaky))):
                uncertain_issues.append(fall_key)
        neighbors = [neighbor for neighbor in (index - 1, index + 1)
                     if 0 <= neighbor < len(review.ref_words)]
        if any(matching.get(neighbor) != usr_index + neighbor - index
               or neighbor in review.shaky for neighbor in neighbors):
            uncertain_issues.append(f"stretched:{index}")
        if (index + 1 < len(review.ref_words)
                and (matching.get(index + 1) != usr_index + 1
                     or index + 1 in review.shaky)):
            uncertain_issues.extend(f"{kind}:{index}" for kind in
                                    ("missed_pause", "extra_pause", "long_pause"))
    return {
        "uncertain_issues": uncertain_issues,
        "issues": [{"kind": a.kind, "ref_index": a.ref_index,
                    "title": a.title} for a in take.advice],
        "uncertain": sorted(set(review.shaky) | {
            t.ref_index for t in take.tokens
            if t.ref_index is not None and t.kind != "equal"
        }),
        "accuracy": round(_accuracy(take.tokens) * 100),
        "speech": round(take.rhythm.speech_ratio, 2),
        "pause": (None if take.rhythm.pause_ratio is None
                  else round(take.rhythm.pause_ratio, 2)),
        # 机器在这一遍里没听对的词，跟着这一遍走。原声那一带转写本身就不可信的不算
        "problems": [{"kind": t.kind, "ref": t.ref_text, "usr": t.usr_text}
                     for t in take.tokens
                     if t.kind != "equal" and t.ref_index not in review.shaky],
        # 两条音轨各自第一个词从第几秒开始。同时播放时各自跳到这里，
        # 起点对齐了，图上同一个 x 才是同一刻。
        "audio": {**audio,
                  "refOffset": round(review.ref_words[0].start, 3),
                  "usrOffset": round(take.words[0].start, 3)},
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
            {"text": s.text,
             "refWidth": round(s.ref_width, 5), "usrWidth": round(s.usr_width, 5),
             "refTrace": [_round(v) for v in s.ref_trace],
             "usrTrace": [_round(v) for v in s.usr_trace],
             "flag": s.flag,
             "refAt": [round(s.ref_start, 3), round(s.ref_end, 3)],
             "usrAt": (None if s.usr_start is None
                       else [round(s.usr_start, 3), round(s.usr_end, 3)])}
            for s in slots
        ],
    }


def feedback_view(review, limit: int, *, audio: dict, takes: dict) -> dict:
    """每一遍都出图，默认打开挑出来的那一遍。

    指标本身是全部遍数的中位数，画的却只能是一遍——所以让人能自己切。
    """
    return {
        "text": " ".join(w.text for w in review.ref_words),
        "chosen": review.summary.representative,
        "takes": [
            _take_view(review, take, limit,
                       {**audio, "usr": takes[str(take.path)]})
            for take in review.takes
        ],
    }
