"""把分析结果变成排序后的可执行指令。纯函数，无 IO。

图告诉你「哪里不一样」，这里告诉你「下一遍怎么改」。
所有问题按 偏差/阈值 打分，因此不同量纲（秒、半音、倍数）之间可以直接比大小。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..analysis.diff import KIND_EQUAL, DiffToken
from ..analysis.prosody import Prosody, terminal_fall, word_pitch
from ..analysis.rhythm import MIN_PAUSE_SEC, Rhythm
from ..models import Word

PAUSE_KINDS = frozenset({"missed_pause", "long_pause", "extra_pause"})

STRETCH_RATIO = 1.4
STRETCH_MIN_SEC = 0.12   # 拖长得少于这么多秒就别提：转写的词边界本身就有
                         # 几十毫秒误差，说了也不可操作
PITCH_GAP_ST = 3.0
SLOPE_GAP_ST = 2.5
STRONG_SLOPE_ST = 3.0
STRONG_FALL_ST = 5.0
FALL_GAP_ST = 4.0


@dataclass(frozen=True, slots=True)
class Advice:
    kind: str
    ref_index: int
    score: float
    flag: str          # 图上标注用的短标签
    title: str
    detail: str
    action: str
    usr_index: int | None = None


def _stretch(ref: Word, usr: Word, speech_ratio: float) -> float:
    """相对「你自己的语速」的拖长倍数——整体慢不是问题，分配不均才是。"""
    if ref.duration <= 0 or speech_ratio <= 0:
        return 1.0
    return (usr.duration / ref.duration) / speech_ratio


def _pitch_off(ref, ref_index: int, ref_head: float, usr_head: float) -> "Advice":
    """词头音高偏了。升降说不清的词，起音高低仍然是能比的。"""
    gap = usr_head - ref_head
    higher = gap > 0
    return Advice(
        kind="pitch_off",
        flag="音高偏高" if higher else "音高偏低",
        ref_index=ref_index,
        score=abs(gap) / PITCH_GAP_ST,
        title=f"“{ref.text}” 音高{'偏高' if higher else '偏低'}",
        detail=f"和你自己的平均音高比，差了 {abs(gap):.0f} 个半音。",
        action=f"“{ref.text}” 起音{'压低' if higher else '抬高'}一点。",
    )


def build_advice(
    *,
    ref_words: Sequence[Word],
    usr_words: Sequence[Word],
    tokens: Sequence[DiffToken],
    rhythm: Rhythm,
    ref_prosody: Prosody,
    usr_prosody: Prosody,
) -> tuple[Advice, ...]:
    found: list[Advice] = []

    for gap in rhythm.gaps:
        if gap.missed:
            found.append(Advice(
                kind="missed_pause",
                usr_index=gap.usr_index,
                flag="后面该停没停",
                ref_index=gap.ref_index,
                score=gap.ref_gap / MIN_PAUSE_SEC,
                title=f"“{gap.text}” 后面该停没停",
                detail=(f"原声在这里停了 {gap.ref_gap:.2f} 秒，"
                        f"你只停了 {gap.usr_gap:.2f} 秒。"),
                action="读到这里把嘴停住，别连下去。停顿本身就是内容。",
            ))

        elif gap.overdone:
            extra = gap.usr_gap - gap.ref_gap
            if gap.ref_gap < MIN_PAUSE_SEC:
                found.append(Advice(
                    kind="extra_pause",
                usr_index=gap.usr_index,
                    flag="多停了一下",
                    ref_index=gap.ref_index,
                    score=extra / MIN_PAUSE_SEC,
                    title=f"“{gap.text}” 后面多停了一下",
                    detail=(f"原声这里没有停顿，你停了 {gap.usr_gap:.2f} 秒。"),
                    action="这里不该断开，连着往下说。",
                ))
            else:
                found.append(Advice(
                    kind="long_pause",
                usr_index=gap.usr_index,
                    flag="停太久",
                    ref_index=gap.ref_index,
                    score=extra / MIN_PAUSE_SEC,
                    title=f"“{gap.text}” 后面停太久",
                    detail=(f"原声停了 {gap.ref_gap:.2f} 秒，你停了 {gap.usr_gap:.2f} 秒。"),
                    action="这里是换口气就走，不是真的等一下。",
                ))

    ratio = rhythm.speech_ratio
    # 隔壁词没对上，说明那条词边界靠不住——连读时 “out of” 的界线本来就是估的，
    # 机器听错一个词，相邻那个词的时长跟着一起不可信。
    matched_refs = {t.ref_index for t in tokens
                    if t.kind == KIND_EQUAL and t.usr_index is not None}
    solid = {i for i in matched_refs
             if (i - 1 in matched_refs or i == 0)
             and (i + 1 in matched_refs or i == len(ref_words) - 1)}
    for token in tokens:
        if token.kind != KIND_EQUAL or token.usr_index is None:
            continue
        ref, usr = ref_words[token.ref_index], usr_words[token.usr_index]

        stretch = _stretch(ref, usr, ratio)
        excess = usr.duration - ref.duration * ratio
        if (stretch > STRETCH_RATIO and excess >= STRETCH_MIN_SEC
                and token.ref_index in solid):
            found.append(Advice(
                kind="stretched",
                flag="拖长了",
                ref_index=token.ref_index,
                score=(stretch - 1.0) / (STRETCH_RATIO - 1.0),
                title=f"“{ref.text}” 拖长了",
                detail=(f"原声 {ref.duration * 1000:.0f} 毫秒，你 {usr.duration * 1000:.0f} 毫秒，"
                        f"是你自己平均语速的 {stretch:.1f} 倍。"),
                action=f"“{ref.text}” 要短促地带过去，别在上面停留。",
            ))

        if token.ref_index == len(ref_words) - 1:
            # 句尾单独用跨词的降幅衡量，词内起止会与听感相反
            ref_fall = terminal_fall(ref_prosody, ref_words)
            usr_fall = terminal_fall(usr_prosody, usr_words)
            if (ref_fall is not None and usr_fall is not None
                    and ref_fall < -STRONG_FALL_ST
                    and usr_fall > ref_fall + FALL_GAP_ST):
                found.append(Advice(
                    kind="flat_fall",
                    flag="句尾没沉下去",
                    ref_index=token.ref_index,
                    score=abs(usr_fall - ref_fall) / FALL_GAP_ST,
                    title=f"“{ref.text}” 收尾没沉下去",
                    detail=(f"原声到句尾沉下去 {abs(ref_fall):.0f} 个半音，"
                            f"你只沉了 {abs(usr_fall):.0f} 个。"),
                    action=f"读到 “{ref.text}” 时整个把声音丢下去，像句号砸下来。",
                ))
            continue

        rp = word_pitch(ref_prosody, ref.start, ref.end)
        up = word_pitch(usr_prosody, usr.start, usr.end)
        if rp is None or up is None:
            continue
        ref_move, usr_move = rp.move, up.move
        if ref_move is None or usr_move is None:
            # 形状不单调（先扬后抑之类），用一个升降数说不清，判了多半与听感
            # 相反。升降不判，但词头音高照旧可以比。
            if abs(up.head - rp.head) > PITCH_GAP_ST:
                found.append(_pitch_off(ref, token.ref_index, rp.head, up.head))
            continue

        if ref_move < -STRONG_SLOPE_ST and usr_move > ref_move + SLOPE_GAP_ST:
            found.append(Advice(
                kind="flat_fall",
                flag="该降没降",
                ref_index=token.ref_index,
                score=abs(usr_move - ref_move) / SLOPE_GAP_ST,
                title=f"“{ref.text}” 该降没降",
                detail=(f"原声在这个词里把音调压下去 {abs(ref_move):.0f} 个半音，"
                        + (f"你只降了 {abs(usr_move):.0f} 个。" if usr_move < 0
                           else f"你反而升了 {usr_move:.0f} 个。")),
                action=f"读 “{ref.text}” 时把声音明显往下丢，别停在半空。",
            ))
        elif ref_move > STRONG_SLOPE_ST and usr_move < ref_move - SLOPE_GAP_ST:
            found.append(Advice(
                kind="flat_rise",
                flag="该升没升",
                ref_index=token.ref_index,
                score=abs(ref_move - usr_move) / SLOPE_GAP_ST,
                title=f"“{ref.text}” 该升没升",
                detail=(f"原声在这个词里把音调抬起 {ref_move:.0f} 个半音，"
                        + (f"你只升了 {usr_move:.0f} 个。" if usr_move > 0
                           else f"你反而降了 {abs(usr_move):.0f} 个。")),
                action=f"读 “{ref.text}” 时把声音往上挑一下。",
            ))
        elif abs(up.head - rp.head) > PITCH_GAP_ST:
            found.append(_pitch_off(ref, token.ref_index, rp.head, up.head))

    # 同一个词的音高/时长问题只留最严重的一条，避免一个词刷满整个列表。
    # 但「该停没停」是另一个动作（嘴要停住），不和词本身的问题合并。
    best: dict[tuple[int, str], Advice] = {}
    for item in found:
        key = (item.ref_index,
               "pause" if item.kind in PAUSE_KINDS else "word")
        if key not in best or item.score > best[key].score:
            best[key] = item
    return tuple(sorted(best.values(), key=lambda item: -item.score))


def well_done(
    *,
    ref_words: Sequence[Word],
    usr_words: Sequence[Word],
    tokens: Sequence[DiffToken],
    rhythm: Rhythm,
    advice: Sequence[Advice] = (),
) -> tuple[str, ...]:
    """做对了的词：时长贴合且没有被点名。

    必须排除已进入建议列表的词，否则同一个词会既出现在「问题」又出现在
    「你做对了」里，自相矛盾。
    """
    flagged = {item.ref_index for item in advice}
    ratio = rhythm.speech_ratio
    good: list[str] = []
    for token in tokens:
        if token.kind != KIND_EQUAL or token.usr_index is None:
            continue
        if token.ref_index in flagged:
            continue
        stretch = _stretch(ref_words[token.ref_index], usr_words[token.usr_index], ratio)
        if 0.5 <= stretch <= 1.15:
            good.append(ref_words[token.ref_index].text.strip(".,!?"))
    return tuple(good)
