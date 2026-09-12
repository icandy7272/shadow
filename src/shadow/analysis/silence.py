"""在一段能量曲线里找停顿，以及判断一段里有没有人声。纯函数，无 IO。

用途一是给裁剪点找落脚处：转写的词级时间戳常整体偏早几百毫秒，照它裁
会把上一句的尾巴带进来。句子之间通常有一小段停顿，裁在那段停顿的中点上，
比信时间戳准得多。

用途二是认出转写凭空编出来的句子：它落在停顿上，那几秒里没人说话。
"""

from __future__ import annotations

import numpy as np

from .. import config

SILENT_DB = -120.0      # 一帧都没有时当作的响度


def quiet_midpoint(
    times: np.ndarray, energy_db: np.ndarray, *,
    drop_db: float = config.SILENCE_DROP_DB,
    min_run: float = config.SILENCE_MIN_RUN_SEC,
) -> float | None:
    """这段窗口里最长那段安静的中点。找不到够长的停顿就返回 None。

    阈值按窗口自己的最大值往下取，不用绝对值：不同素材的响度差得远。
    要求一段最短长度，是为了滤掉爆破音闭塞那种两三帧的下陷。
    """
    if times.size == 0 or energy_db.size == 0:
        return None
    quiet = energy_db < (float(np.max(energy_db)) - drop_db)
    best_start = best_len = 0
    start = None
    for index, is_quiet in enumerate(quiet):
        if is_quiet:
            if start is None:
                start = index
            continue
        if start is not None and index - start > best_len:
            best_start, best_len = start, index - start
        start = None
    if start is not None and quiet.size - start > best_len:
        best_start, best_len = start, quiet.size - start

    if best_len == 0:
        return None
    step = float(times[1] - times[0]) if times.size > 1 else 0.01
    if best_len * step < min_run:
        return None
    return float(times[best_start] + (best_len - 1) * step / 2)


def loud_level(energy_db: np.ndarray, *,
               percentile: float = config.SPEECH_LOUD_PERCENTILE) -> float:
    """整段素材「在说话」时的典型响度。

    取高分位而不是最大值：一声咳嗽、一下掌声不该定标准。
    """
    if energy_db.size == 0:
        return SILENT_DB
    return float(np.percentile(energy_db, percentile))


def voiced_fraction(energy_db: np.ndarray, *, loud_db: float,
                    drop_db: float = config.SPEECH_DROP_DB) -> float:
    """这一段里有多少帧够得上人声。

    门槛跟着整段素材的典型响度走，不用绝对值：录音电平差得远，
    同样 -50 dB，在响的素材里是静音，在轻的素材里是说话。
    """
    if energy_db.size == 0:
        return 0.0
    return float(np.mean(energy_db > loud_db - drop_db))
