"""shadow 命令行入口：import / list / export / compare。"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import datetime
from dataclasses import replace
from pathlib import Path

from . import config, db, media
from .analysis.diff import accuracy as diff_accuracy
from .analysis.diff import diff_words, matched_pairs, unreliable_indices
from .analysis.prosody import analyse, word_contour
from .drill.gapfill import blanks_of, parse_answer, render, tally
from .drill.units import split_into_units
from .ingest.pipeline import import_source
from .ingest.transcriber import transcribe_words
from .models import Word
from .analysis.rhythm import alignment_drift, analyse_rhythm
from .report.advice import PAUSE_KINDS, build_advice, well_done
from .report.blocks import Flag, PauseNote, render_feedback
from .report.takes import TakeMetrics, TakeSummary, summarise


class CliError(RuntimeError):
    """命令执行失败，消息直接呈现给用户。

    不能用 SystemExit——它继承自 BaseException 而非 Exception，
    会绕过各命令的 except Exception，既丢掉错误前缀，也破坏 main() 返回 int 的契约。
    """


def _open_db():
    connection = db.connect()
    db.init_db(connection)
    db.reset_stale_sources(connection)
    return connection


def cmd_import(args: argparse.Namespace) -> int:
    connection = _open_db()
    try:
        source_id = import_source(args.url, conn=connection)
    except Exception as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return 1
    segments = db.list_segments(connection, source_id)
    row = db.get_source(connection, source_id)
    print(f"[{source_id}] {row['title']}")
    print(f"  时长 {row['duration_sec'] / 60:.1f} 分钟，切出 {len(segments)} 个片段")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    connection = _open_db()
    sources = db.list_sources(connection)
    if not sources:
        print("还没有导入任何素材。试试：shadow import <url>")
        return 0
    for row in sources:
        segments = db.list_segments(connection, row["id"])
        print(f"[{row['id']}] {row['title']}  ({row['status']}, {len(segments)} 片段)")
        if row["error"]:
            print(f"      错误：{row['error']}")
        if args.segments:
            for segment in segments:
                preview = segment["text"][:60]
                print(
                    f"      #{segment['id']} "
                    f"{segment['start_sec']:7.1f}-{segment['end_sec']:7.1f}s  {preview}…"
                )
    return 0


UNIT_PAD_SEC = 0.1
MAX_ADVICE = 3


def _segment_units(connection, segment_id: int, *, min_sec: float | None = None,
                   max_sec: float | None = None):
    """取出片段及其练习单元。min_sec=0 表示完全按句子切、不合并短句。"""
    segment = db.get_segment(connection, segment_id)
    if segment is None:
        raise CliError(f"片段 {segment_id} 不存在")
    source = db.get_source(connection, segment["source_id"])
    if source is None or not source["audio_path"]:
        raise CliError(f"片段 {segment_id} 的素材音频缺失")
    return segment, source, split_into_units(
        segment["words"],
        min_sec=config.UNIT_MIN_SEC if min_sec is None else min_sec,
        max_sec=config.UNIT_MAX_SEC if max_sec is None else max_sec,
    )


def _segment_reference(connection, segment_id: int, dest: Path, *,
                       unit: int | None = None, min_sec: float | None = None,
                       max_sec: float | None = None):
    """导出音频，并把词时间戳平移到以裁剪起点为 0。

    unit=None 导出整个片段；给了 unit 就只导出那个练习单元（首尾各留一点余量，
    免得切掉词头的爆破音）。
    """
    segment, source, units = _segment_units(
        connection, segment_id, min_sec=min_sec, max_sec=max_sec
    )

    if unit is None:
        start, end = segment["start_sec"], segment["end_sec"]
        words = segment["words"]
    else:
        if not 1 <= unit <= len(units):
            raise CliError(
                f"片段 {segment_id} 只有 {len(units)} 个练习单元，没有第 {unit} 个"
            )
        words = units[unit - 1]
        start = max(segment["start_sec"], words[0].start - UNIT_PAD_SEC)
        end = min(segment["end_sec"], words[-1].end + UNIT_PAD_SEC)

    media.cut_segment(Path(source["audio_path"]), dest, start=start, end=end)
    rebased = tuple(
        replace(word, start=word.start - start, end=word.end - start)
        for word in words
    )
    return dest, rebased, " ".join(word.text for word in rebased)


def cmd_units(args: argparse.Namespace) -> int:
    connection = _open_db()
    try:
        segment, _, units = _segment_units(
            connection, args.segment,
            min_sec=args.min_sec, max_sec=args.max_sec,
        )
    except Exception as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 1
    span = segment["end_sec"] - segment["start_sec"]
    print(f"片段 #{args.segment}（{span:.1f}s，{len(segment['words'])} 词）"
          f"切成 {len(units)} 个练习单元：")
    for index, unit in enumerate(units, 1):
        duration = unit[-1].end - unit[0].start
        blanks = sum(word.is_blank for word in unit)
        text = " ".join(word.text for word in unit)
        print(f"  {index:2d}. [{duration:4.1f}s {len(unit):2d}词 {blanks}空]  {text}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    connection = _open_db()
    suffix = "" if args.unit is None else f"-u{args.unit}"
    dest = Path(
        args.out or config.segment_audio_dir() / f"{args.segment}{suffix}.wav"
    )
    try:
        path, _, text = _segment_reference(
            connection, args.segment, dest, unit=args.unit,
            min_sec=args.min_sec, max_sec=args.max_sec,
        )
    except Exception as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 1
    print(f"已导出 {path}")
    print(text)
    return 0


def _reference_for(connection, args):
    """取原声音频与词序列。--segment 走库，--ref 走文件。"""
    if args.segment is not None:
        suffix = "" if args.unit is None else f"-u{args.unit}"
        return _segment_reference(
            connection, args.segment,
            config.segment_audio_dir() / f"{args.segment}{suffix}.wav",
            unit=args.unit, min_sec=getattr(args, "min_sec", None),
            max_sec=getattr(args, "max_sec", None),
        )[:2]
    ref_path = Path(args.ref)
    return ref_path, transcribe_words(ref_path)


def _compare(connection, *, ref_path, ref_words, paths, out_path,
             segment_id=None, unit_index=None, args=None, run_id=None) -> int:
    ref_prosody = analyse(ref_path)
    # 交叉验证：库内文本来自长上下文转写，可能把缩读还原成完整形式，
    # 与音频对不上。这些词不能用来判用户对错。
    shaky = unreliable_indices(
        [w.text for w in ref_words],
        [w.text for w in transcribe_words(ref_path)],
    )
    metrics: list[TakeMetrics] = []
    details = []
    skipped: list[tuple[str, float]] = []
    for path in paths:
        usr_words = transcribe_words(path)
        tokens = diff_words([w.text for w in ref_words], [w.text for w in usr_words])
        rhythm = analyse_rhythm(ref_words, usr_words, matched_pairs(tokens))
        usr_prosody = analyse(path)

        drift = alignment_drift(usr_words, usr_prosody)
        if drift is not None and drift > config.ALIGNMENT_TOLERANCE_SEC:
            # 时间戳整体错位，这一遍的每项测量都取自错误的音频位置
            skipped.append((path.name, drift))
            continue

        advice = build_advice(
            ref_words=ref_words, usr_words=usr_words, tokens=tokens,
            rhythm=rhythm, ref_prosody=ref_prosody, usr_prosody=usr_prosody,
        )
        metrics.append(TakeMetrics(
            accuracy=diff_accuracy(tokens), speech_ratio=rhythm.speech_ratio,
            pause_ratio=rhythm.pause_ratio, advice=advice,
        ))
        details.append((path, usr_words, tokens, rhythm, usr_prosody, advice))

    if skipped:
        for name, drift in skipped:
            print(f"⚠ 跳过 {name}：转写时间戳偏离实际发声 {drift:.1f} 秒，"
                  f"该遍的测量不可信。", file=sys.stderr)
    if not metrics:
        print("所有录音的时间戳都对不上，无法比对。换个更安静的环境重录试试。",
              file=sys.stderr)
        return 1

    summary = summarise(metrics)
    _, usr_words, tokens, rhythm, usr_prosody, advice = details[summary.representative]

    flags = tuple(
        Flag(usr_index=usr_index, text=item.flag)
        for item, usr_index in _flag_targets(advice, ref_words, tokens)
        if item.kind not in PAUSE_KINDS
    )
    pause_notes = tuple(
        PauseNote(ref_index=item.ref_index, usr_index=item.usr_index,
                  kind=item.kind, flag=item.flag)
        for item in advice[:MAX_ADVICE] if item.kind in PAUSE_KINDS
    )
    render_feedback(
        ref_words=ref_words, usr_words=usr_words, tokens=tokens, rhythm=rhythm,
        ref_prosody=ref_prosody, usr_prosody=usr_prosody, flags=flags,
        pause_notes=pause_notes, accuracy=diff_accuracy(tokens),
        text=" ".join(w.text for w in ref_words), out_path=out_path,
    )

    if segment_id is not None:
        _save_run(connection, segment_id, unit_index, details, metrics,
                  unit_text=" ".join(w.text for w in ref_words), run_id=run_id)

    _print_summary(summary, paths, tokens, out_path, shaky=shaky)
    if args is not None:
        _suggest_after_compare(connection, args, summary)
    return 0


def _suggest_after_compare(connection, args, summary) -> None:
    """还有反复出现的问题就重练同一句，干净了才往下一句走。"""
    if summary.issues or summary.count < 3:
        _next_step(args, "record --listen 4", "同一句再来一轮")
        return
    if args.segment is None or args.unit is None:
        print("\n这一句没有反复出现的问题了，可以换下一句。")
        return
    try:
        _, _, units = _segment_units(connection, args.segment,
                                     min_sec=args.min_sec, max_sec=args.max_sec)
    except Exception:
        return
    if args.unit >= len(units):
        print(f"\n这是最后一个单元了。换片段：uv run shadow list -s")
        return
    following = args.unit + 1
    print(f"\n这一句干净了。下一句（{following}/{len(units)}）："
          f"{' '.join(w.text for w in units[following - 1])}")
    print(f"  uv run shadow listen --segment {args.segment} --unit {following}")


def _save_run(connection, segment_id, unit_index, details, metrics,
              unit_text=None, run_id=None) -> None:
    """把这一轮存进库，进度才能跨会话累积。

    practice 会把盲听、填空、跟读记到同一行，所以允许复用已有的 run。
    """
    own = run_id is None
    if own:
        run_id = db.start_run(connection, segment_id=segment_id,
                              unit_index=unit_index, unit_text=unit_text)
    for (path, usr_words, _, _, _, advice), take in zip(details, metrics):
        db.add_attempt(
            connection, run_id=run_id, audio_path=str(path),
            asr_text=" ".join(w.text for w in usr_words),
            metrics={
                "accuracy": take.accuracy,
                "speech_ratio": take.speech_ratio,
                "pause_ratio": take.pause_ratio,
                "issues": [
                    {"kind": a.kind, "ref_index": a.ref_index,
                     "score": a.score, "title": a.title}
                    for a in advice
                ],
            },
        )
    if own:
        db.finish_run(connection, run_id)


def cmd_compare(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.user]
    for path in paths:            # 全部先校验，别录了三遍才发现第一遍是静音
        try:
            media.validate_attempt(path)
        except Exception as exc:
            print(f"录音不可用（{path.name}）：{exc}", file=sys.stderr)
            return 1

    connection = _open_db()
    try:
        ref_path, ref_words = _reference_for(connection, args)
        if not ref_words:
            print("原声转写为空，无法比较。", file=sys.stderr)
            return 1
        return _compare(
            connection, ref_path=ref_path, ref_words=ref_words, paths=paths,
            out_path=Path(args.out or "feedback.png"),
            segment_id=args.segment, unit_index=args.unit, args=args,
        )
    except Exception as exc:
        print(f"比对失败：{exc}", file=sys.stderr)
        return 1


BLIND_SCALE = (
    "1  几乎没听懂",
    "2  抓到几个词",
    "3  大意懂了，细节丢了",
    "4  基本都懂，个别词没抓住",
    "5  每个词都听清了",
)


def _ask_blind_rating() -> int | None:
    print("\n听懂了多少？")
    for line in BLIND_SCALE:
        print(f"    {line}")
    while True:
        try:
            answer = input("  输入 1-5（直接回车跳过）：").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not answer:
            return None
        if answer in "12345" and len(answer) == 1:
            return int(answer)
        print("  只接受 1 到 5。")


def _play_times(ref_path, times: int, label: str = "听") -> None:
    if times <= 0:
        return
    try:
        for index in range(1, times + 1):
            print(f"  {label} {index}/{times}", end="\r", flush=True)
            media.play(ref_path, times=1, gap=0.0)
            if index < times:
                time.sleep(0.5)
        print("               ", end="\r")
    except KeyboardInterrupt:
        print("\n  停了。")
    except Exception as exc:
        print(f"\n  播放失败：{exc}", file=sys.stderr)


def _run_gapfill(ref_path, ref_words, times: int):
    """精听填空的核心。返回 (答对, 总数, 听出来的, 重听次数)，没有空则 None。"""
    shaky = unreliable_indices(
        [w.text for w in ref_words],
        [w.text for w in transcribe_words(ref_path)],
    )
    blanks = tuple(b for b in blanks_of(ref_words) if b.word_index not in shaky)
    if not blanks:
        print("这一句没有挖空位（没有被弱读的功能词）。换一句试试。")
        return None

    print(f"精听填空 · {len(ref_words)} 个词，{len(blanks)} 个空")
    print("先听几遍，再逐个填。听不清就输入 ?? 重听。")
    print("听出来的直接写；靠上下文猜的，在词后加个问号（如 up?）——"
          "功能词太好猜了，不分开就测不出听力。\n")
    _play_times(ref_path, times)
    print(f"{render(ref_words)}\n")

    answers = []
    replays: list[int] = []
    for blank in blanks:
        used = 0
        prompt = f"  {blank.number}. …{blank.left} [____] {blank.right}…  "
        while True:
            # 中断向上抛，由调用方决定怎么收尾（practice 需要先把记录收掉）
            guess = input(prompt).strip()
            if guess == "??":
                used += 1
                _play_times(ref_path, 1, label="重听")
                continue
            answers.append(parse_answer(guess))
            replays.append(used)
            break

    correct, total, heard = tally(blanks, answers)
    total_replays = sum(replays)
    extra = f"，重听 {total_replays} 次" if total_replays else "，一遍过"
    print(f"\n{correct}/{total} 对，其中 {heard} 个是听出来的{extra}\n")
    for blank, response, used in zip(blanks, answers, replays):
        if response.guess and blank.matches(response.guess):
            mark = "✓" if response.heard else "○"
            note = "" if response.heard else "   （靠上下文推的，不算听力）"
            if response.heard and used:
                note = f"   （重听 {used} 次才抓到）"
            print(f"  {mark} {blank.answer}{note}")
        else:
            wrote = f"你填了 “{response.guess}”" if response.guess else "跳过了"
            print(f"  ✗ {blank.answer:<10} {wrote}"
                  f"   —— 原声只有 {blank.duration * 1000:.0f} 毫秒，被吞掉了")
    print(f"\n原文：{' '.join(w.text for w in ref_words)}")

    print(f"\n原文：{' '.join(w.text for w in ref_words)}")
    return correct, total, heard, total_replays


def _run_blind_listen(ref_path, ref_words, times: int, gap: float):
    """盲听的核心。返回自评分数或 None。"""
    print(f"盲听 · {len(ref_words)} 个词 · 放 {times} 遍")
    print("不看文字，就听。\n")
    try:
        for index in range(1, times + 1):
            print(f"  {index}/{times}", end="\r", flush=True)
            media.play(ref_path, times=1, gap=0.0)
            if index < times:
                time.sleep(gap)
        print("             ")
    except KeyboardInterrupt:
        print("\n停了。")
    except Exception as exc:
        print(f"\n播放失败：{exc}", file=sys.stderr)
        return 1

    return _ask_blind_rating()


def _reveal(ref_words) -> None:
    """只揭晓挖空版：给「原来是这句」的反馈，但把被弱读的词继续藏着，
    否则紧接着的填空直接知道答案。"""
    blanks = blanks_of(ref_words)
    print("\n原文：")
    print(f"  {render(ref_words)}\n")
    if blanks:
        print(f"（{len(blanks)} 个被弱读的词还藏着）")


def _record_takes(args, ref_path, ref_words, seconds: float):
    """录若干遍，返回文件路径列表；任一遍不可用则返回 None。"""
    stamp = datetime.now().strftime("%m%d-%H%M%S")
    label = f"{args.segment}" if args.segment is not None else "ref"
    if args.unit is not None:
        label += f"-u{args.unit}"
    paths: list[Path] = []
    for index in range(1, args.takes + 1):
        try:
            input(f"第 {index}/{args.takes} 遍 —— 按回车"
                  + ("（先听，再录）" if args.listen else "开始录"))
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。", file=sys.stderr)
            return None
        _listen_before_take(ref_path, args.listen)
        dest = config.attempt_audio_dir() / f"{label}-{stamp}-{index}.wav"
        print("  嘀一声之后开始说 …", end="", flush=True)
        media.beep()
        print("\r  录音中——说完敲回车结束      ", end="", flush=True)
        try:
            media.record(dest, seconds=seconds, device=args.device)
            media.validate_attempt(dest)
        except Exception as exc:
            print(f"\n  第 {index} 遍不可用：{exc}", file=sys.stderr)
            return None
        print(f"\r  录好了 → {dest.name}          ")
        paths.append(dest)
    return paths


def cmd_drill(args: argparse.Namespace) -> int:
    connection = _open_db()
    try:
        ref_path, ref_words = _reference_for(connection, args)
    except Exception as exc:
        print(f"读取原声失败：{exc}", file=sys.stderr)
        return 1
    try:
        result = _run_gapfill(ref_path, ref_words, args.times)
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。", file=sys.stderr)
        return 1
    if result is None:
        return 0
    correct, total, heard, replays = result
    if args.segment is not None:
        run_id = db.start_run(connection, segment_id=args.segment,
                              unit_index=args.unit,
                              unit_text=" ".join(w.text for w in ref_words))
        db.set_gapfill(connection, run_id, correct, total, heard, replays)
        db.finish_run(connection, run_id)
        print("\n记下了。")
    else:
        print("\n（用 --segment 才能存进进度）")
    _next_step(args, "record --listen 4", "跟读录三遍，每遍前会自动放 4 次原声")
    return 0


def cmd_listen(args: argparse.Namespace) -> int:
    connection = _open_db()
    try:
        ref_path, ref_words = _reference_for(connection, args)
    except Exception as exc:
        print(f"读取原声失败：{exc}", file=sys.stderr)
        return 1
    rating = _run_blind_listen(ref_path, ref_words, args.times, args.gap)
    _reveal(ref_words)
    if rating is None:
        print("没记分数。")
    elif args.segment is not None:
        run_id = db.start_run(connection, segment_id=args.segment,
                              unit_index=args.unit,
                              unit_text=" ".join(w.text for w in ref_words))
        db.set_blind_rating(connection, run_id, rating)
        db.finish_run(connection, run_id)
        print(f"记下了：{rating} 分。")
    else:
        print(f"记下了：{rating} 分（用 --segment 才能存进进度）")
    _next_step(args, "drill", "精听填空，把藏着的功能词听出来")
    return 0


def cmd_practice(args: argparse.Namespace) -> int:
    """一条命令走完四步闭环，并记成同一条练习记录。

    摩擦是习惯的头号杀手，而这套东西要靠每天跑才有意义。
    """
    connection = _open_db()
    try:
        ref_path, ref_words = _reference_for(connection, args)
    except Exception as exc:
        print(f"读取原声失败：{exc}", file=sys.stderr)
        return 1
    if not ref_words:
        print("原声转写为空，无法练习。", file=sys.stderr)
        return 1

    text = " ".join(w.text for w in ref_words)
    run_id = None
    if args.segment is not None:
        run_id = db.start_run(connection, segment_id=args.segment,
                              unit_index=args.unit, unit_text=text)

    print("━━ 1/3 盲听 ━━ 不看文字，就听\n")
    rating = _run_blind_listen(ref_path, ref_words, args.times, args.gap)
    _reveal(ref_words)
    if rating is None:
        print("没记分数。")
    else:
        print(f"记下了：{rating} 分。")
        if run_id is not None:
            db.set_blind_rating(connection, run_id, rating)

    print("\n━━ 2/3 精听填空 ━━\n")
    try:
        filled = _run_gapfill(ref_path, ref_words, args.times)
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。", file=sys.stderr)
        if run_id is not None:
            db.finish_run(connection, run_id)
        return 1
    if filled is not None and run_id is not None:
        db.set_gapfill(connection, run_id, *filled)

    print("\n━━ 3/3 跟读 ━━\n")
    span = ref_words[-1].end - ref_words[0].start
    seconds = args.seconds or min(span * 2.5 + 4.0, 120.0)
    devices = media.list_input_devices()
    if devices:
        current = dict(devices).get(args.device, "?")
        print(f"麦克风 [{args.device}] {current}（换设备加 --device N）")
    print(f"共 {args.takes} 遍，每遍前先放 {args.listen} 次原声。"
          f"说完敲回车即可结束。\n")

    paths = _record_takes(args, ref_path, ref_words, seconds)
    if paths is None:
        if run_id is not None:
            db.finish_run(connection, run_id)
        return 1

    print()
    try:
        code = _compare(
            connection, ref_path=ref_path, ref_words=ref_words, paths=paths,
            out_path=Path(args.out or "feedback.png"),
            segment_id=args.segment, unit_index=args.unit, args=args, run_id=run_id,
        )
    except Exception as exc:
        print(f"比对失败：{exc}", file=sys.stderr)
        code = 1
    if run_id is not None:
        db.finish_run(connection, run_id)
    return code


def cmd_play(args: argparse.Namespace) -> int:
    connection = _open_db()
    try:
        ref_path, ref_words = _reference_for(connection, args)
    except Exception as exc:
        print(f"读取原声失败：{exc}", file=sys.stderr)
        return 1
    if args.text:
        print(" ".join(w.text for w in ref_words))
    else:
        print(f"（{len(ref_words)} 个词，不显示原文——想看加 --text）")
    print(f"\n放 {args.times} 遍（Ctrl+C 停）\n")
    try:
        for index in range(1, args.times + 1):
            print(f"  {index}/{args.times}", end="\r", flush=True)
            media.play(ref_path, times=1, gap=0.0)
            if index < args.times:
                time.sleep(args.gap)
    except KeyboardInterrupt:
        print("\n停了。")
        return 0
    except Exception as exc:
        print(f"\n播放失败：{exc}", file=sys.stderr)
        return 1
    print(f"  放完 {args.times} 遍。")
    return 0


def _listen_before_take(ref_path, times: int) -> None:
    """每遍录音前都重放原声。

    实测声学记忆衰减极快：某轮第一遍（紧接试听之后）句尾降幅 −5.3，
    接近原声的 −5.8；第二、三遍掉到 −1.1 和 −1.9。整轮只在开头听一次，
    等于只有第一遍是在模仿，后面几遍是在背诵。
    """
    if times <= 0:
        return
    try:
        for index in range(1, times + 1):
            print(f"  听 {index}/{times}", end="\r", flush=True)
            media.play(ref_path, times=1, gap=0.0)
            if index < times:
                time.sleep(0.5)
        print("            ", end="\r")
    except KeyboardInterrupt:
        print("\n  跳过试听。")
    except Exception as exc:
        print(f"\n  播放失败（不影响录音）：{exc}", file=sys.stderr)


def cmd_record(args: argparse.Namespace) -> int:
    connection = _open_db()
    try:
        ref_path, ref_words = _reference_for(connection, args)
    except Exception as exc:
        print(f"读取原声失败：{exc}", file=sys.stderr)
        return 1

    span = ref_words[-1].end - ref_words[0].start if ref_words else 5.0
    # 多给一点余量：麦克风有启动延迟，且提示音后到开口有反应时间
    # 可以敲回车提前结束，所以上限给宽一点，宁可等也别切掉尾巴
    seconds = args.seconds or min(span * 2.5 + 4.0, 120.0)

    devices = media.list_input_devices()
    if devices:
        current = dict(devices).get(args.device, "?")
        print("麦克风：" + "，".join(f"[{i}] {n}" for i, n in devices))
        print(f"这次用 [{args.device}] {current}（换设备加 --device N）\n")

    print(f"原声：{' '.join(w.text for w in ref_words)}")
    listen_note = f"，每遍前先放 {args.listen} 次原声" if args.listen else ""
    print(f"每遍录 {seconds:.0f} 秒，共 {args.takes} 遍{listen_note}。\n")



    stamp = datetime.now().strftime("%m%d-%H%M%S")
    label = f"{args.segment}" if args.segment is not None else "ref"
    if args.unit is not None:
        label += f"-u{args.unit}"

    paths: list[Path] = []
    for index in range(1, args.takes + 1):
        try:
            input(f"第 {index}/{args.takes} 遍 —— 按回车"
                  + ("（先听，再录）" if args.listen else "开始录"))
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。", file=sys.stderr)
            return 1
        _listen_before_take(ref_path, args.listen)
        dest = config.attempt_audio_dir() / f"{label}-{stamp}-{index}.wav"
        print("  嘀一声之后开始说 …", end="", flush=True)
        media.beep()
        print("\r  录音中——说完敲回车结束      ", end="", flush=True)
        try:
            media.record(dest, seconds=seconds, device=args.device)
            media.validate_attempt(dest)
        except Exception as exc:
            print(f"  第 {index} 遍不可用：{exc}", file=sys.stderr)
            return 1
        print(f"\r  录好了 → {dest.name}          ")
        paths.append(dest)

    print()
    try:
        return _compare(
            connection, ref_path=ref_path, ref_words=ref_words, paths=paths,
            out_path=Path(args.out or "feedback.png"),
            segment_id=args.segment, unit_index=args.unit, args=args,
        )
    except Exception as exc:
        print(f"比对失败：{exc}", file=sys.stderr)
        return 1


def _target_args(args) -> str:
    """把当前的 --segment/--ref/--unit 还原成命令行片段。"""
    if getattr(args, "segment", None) is not None:
        target = f"--segment {args.segment}"
        if getattr(args, "unit", None) is not None:
            target += f" --unit {args.unit}"
    else:
        target = f"--ref {args.ref}"
    for name in ("min_sec", "max_sec"):
        value = getattr(args, name, None)
        if value is not None:
            target += f" --{name.replace('_', '-')} {value:g}"
    return target


def _next_step(args, command: str, hint: str) -> None:
    """把下一条命令直接打出来，省得每次去查。"""
    print(f"\n下一步：{hint}")
    print(f"  uv run shadow {command} {_target_args(args)}")


def _local_time(stamp: str) -> str:
    """库里存的是 UTC，显示要转本地时区，否则跨时区看着像是别人练的。"""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%m-%d %H:%M")
    except ValueError:
        return stamp[:16]


def cmd_progress(args: argparse.Namespace) -> int:
    connection = _open_db()
    runs = db.list_runs(connection, segment_id=args.segment, unit_index=args.unit)
    if not runs:
        print("还没有练习记录。用 shadow record 练一轮就有了。")
        return 0

    print(f"{'时间':<14}{'遍数':>5}{'可懂':>7}{'发声':>7}{'停顿':>7}"
          f"   句子 / 反复出现的问题")
    for row in runs:
        takes = db.run_metrics(connection, row["id"])
        if not takes:
            if row["gapfill_total"]:
                heard = row["gapfill_heard"]
                text = (row["unit_text"] or "")[:40]
                listened = ("—" if heard is None
                            else f"听出 {heard}/{row['gapfill_total']}")
                rep = row["gapfill_replays"]
                shown = "" if rep is None else (f"重听{rep}" if rep else "一遍过")
                print(f"{_local_time(row['started_at']):<14}{'填空':>5}"
                      f"{row['gapfill_correct']}/{row['gapfill_total']:<4}"
                      f"{listened:>10}{shown:>8}   {text}")
                continue
            if row["blind_rating"] is not None:
                text = (row["unit_text"] or "")[:44]
                print(f"{_local_time(row['started_at']):<14}{'盲听':>5}"
                      f"{row['blind_rating']:>6}分{'':>7}{'':>7}   {text}")
            continue
        counts: dict[str, int] = {}
        for take in takes:
            for issue in {(i["kind"], i["ref_index"]): i
                          for i in take.get("issues", ())}.values():
                counts[issue["title"]] = counts.get(issue["title"], 0) + 1
        threshold = max(1, round(len(takes) * 0.5))
        repeated = [t for t, c in sorted(counts.items(), key=lambda kv: -kv[1])
                    if c >= threshold]
        pauses = [t["pause_ratio"] for t in takes if t.get("pause_ratio") is not None]
        text = (row["unit_text"] or f"片段 {row['segment_id']} 单元 {row['unit_index']}")[:30]
        print(f"{_local_time(row['started_at']):<14}{len(takes):>5}"
              f"{statistics.median(t['accuracy'] for t in takes) * 100:>6.0f}%"
              f"{statistics.median(t['speech_ratio'] for t in takes):>7.2f}"
              f"{(f'{statistics.median(pauses):.2f}' if pauses else '—'):>7}"
              f"   {text}"
              f"{('  ← ' + '、'.join(repeated[:2])) if repeated else ''}")
    return 0


def _flag_targets(advice, ref_words, tokens):
    """把诊断挂回到具体的用户词下标，供图 2 标红。"""
    by_ref_text = {}
    for token in tokens:
        if token.kind == "equal" and token.usr_index is not None:
            by_ref_text.setdefault(ref_words[token.ref_index].text, token.usr_index)
    for item in advice[:MAX_ADVICE]:
        for text, usr_index in by_ref_text.items():
            if f"“{text}”" in item.title:
                yield item, usr_index
                break


def _band(spread, unit: str = "x") -> str:
    if spread.width < 0.005:
        return f"{spread.median:.2f}{unit}"
    return f"{spread.median:.2f}{unit}（{spread.low:.2f}–{spread.high:.2f}）"


def _print_summary(summary: TakeSummary, paths, tokens, out_path, shaky=frozenset()) -> None:
    if summary.count > 1:
        print(f"\n{summary.count} 次录音，取中位数（括号内是范围）")
    accuracy = summary.accuracy
    print(f"\n可懂度 {accuracy.median * 100:.0f}%"
          + ("" if accuracy.width < 0.005
             else f"（{accuracy.low * 100:.0f}–{accuracy.high * 100:.0f}%）"))
    problems = [t for t in tokens if t.kind != "equal" and t.ref_index not in shaky]
    hidden = [t for t in tokens if t.kind != "equal" and t.ref_index in shaky]
    if not problems:
        print("  发音层面没问题——每个词机器都听出来了。")
    else:
        for token in problems[:20]:
            if token.kind == "missing":
                print(f"  漏  {token.ref_text}")
            elif token.kind == "wrong":
                print(f"  错  {token.ref_text}  ->  听成 {token.usr_text}")
            else:
                print(f"  多  {token.usr_text}")

    for token in hidden:
        print(f"  ?  {token.ref_text} —— 原声这里库内文本与音频对不上，不作数")

    pause = "—" if summary.pause_ratio is None else _band(summary.pause_ratio)
    print(f"\n发声 {_band(summary.speech_ratio)}    停顿 {pause}")

    if summary.count > 1:
        unstable = [
            name for name, spread, limit in (
                ("发声", summary.speech_ratio, 0.15),
                ("停顿", summary.pause_ratio, 0.30),
            )
            if spread is not None and spread.width > limit
        ]
        if unstable:
            print(f"  ⚠ {' 和 '.join(unstable)}在几次之间差得比较多，"
                  "说明还没形成稳定的模式——先把同一句读稳，再谈往原声靠。")

    if not summary.issues:
        if summary.count < 3:
            print(f"\n这 {summary.count} 遍里没有共同的问题——但样本太少，"
                  f"说明不了稳定性。再录几遍才作数。\n")
        else:
            print("\n没有反复出现的问题，可以换下一个单元了。\n")
    else:
        shown = summary.issues[:MAX_ADVICE]
        head = (f"\n反复出现的问题，按重要性排（先看每次都犯的）：\n"
                if summary.count > 1 else f"\n下一遍改这 {len(shown)} 处：\n")
        print(head)
        for number, issue in enumerate(shown, 1):
            times = (f"  [{issue.hits}/{issue.total} 次]" if summary.count > 1 else "")
            print(f"  {number}. {issue.advice.title}{times}")
            print(f"     现状：{issue.advice.detail}")
            print(f"     怎么做：{issue.advice.action}\n")

    if summary.count > 1:
        print(f"（图用的是第 {summary.representative + 1} 次，"
              f"它的语速最接近这几次的中位数）")
    print(f"反馈图已写入 {out_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shadow", description="英语影子跟读训练工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="从 URL 导入素材")
    p_import.add_argument("url")
    p_import.set_defaults(func=cmd_import)

    p_list = sub.add_parser("list", help="列出已导入素材")
    p_list.add_argument("-s", "--segments", action="store_true", help="同时列出片段")
    p_list.set_defaults(func=cmd_list)

    p_units = sub.add_parser("units", help="列出片段内的练习单元（3-8s）")
    p_units.add_argument("segment", type=int)
    p_units.add_argument("--min-sec", type=float,
                          help="练习单元的最短秒数。默认 0 = 严格一句一个；设成 1.5 会把短句并进下一句")
    p_units.add_argument("--max-sec", type=float,
                          help="练习单元的最长秒数，超过会在最大停顿处再断（默认 6）")
    p_units.set_defaults(func=cmd_units)

    p_export = sub.add_parser("export", help="导出音频用于跟读")
    p_export.add_argument("segment", type=int)
    p_export.add_argument("-u", "--unit", type=int, help="只导出第 n 个练习单元")
    p_export.add_argument("-o", "--out")
    p_export.add_argument("--min-sec", type=float,
                          help="练习单元的最短秒数。默认 0 = 严格一句一个；设成 1.5 会把短句并进下一句")
    p_export.add_argument("--max-sec", type=float,
                          help="练习单元的最长秒数，超过会在最大停顿处再断（默认 6）")
    p_export.set_defaults(func=cmd_export)

    p_record = sub.add_parser("record", help="录音并立即比对（推荐每轮录 3 遍）")
    record_group = p_record.add_mutually_exclusive_group(required=True)
    record_group.add_argument("--ref", help="原声 wav 路径")
    record_group.add_argument("--segment", type=int, help="已导入的片段 id")
    p_record.add_argument("-u", "--unit", type=int, help="片段内第 n 个练习单元")
    p_record.add_argument("-n", "--takes", type=int, default=3, help="录几遍（默认 3）")
    p_record.add_argument("--device", default="0", help="麦克风编号，默认 0")
    p_record.add_argument("--listen", type=int, default=0,
                          help="每遍录音前先放几遍原声（建议 3-5）。声学记忆衰减很快，别只在开头听")
    p_record.add_argument("--seconds", type=float, help="每遍录多少秒，默认按原声长度自动定")
    p_record.add_argument("-o", "--out", help="输出 png 路径")
    p_record.add_argument("--min-sec", type=float,
                          help="练习单元的最短秒数。默认 0 = 严格一句一个；设成 1.5 会把短句并进下一句")
    p_record.add_argument("--max-sec", type=float,
                          help="练习单元的最长秒数，超过会在最大停顿处再断（默认 6）")
    p_record.set_defaults(func=cmd_record)

    p_practice = sub.add_parser(
        "practice", help="一条命令走完盲听 → 填空 → 跟读（推荐日常用这个）")
    practice_group = p_practice.add_mutually_exclusive_group(required=True)
    practice_group.add_argument("--ref", help="原声 wav 路径")
    practice_group.add_argument("--segment", type=int, help="已导入的片段 id")
    p_practice.add_argument("-u", "--unit", type=int, help="片段内第 n 个练习单元")
    p_practice.add_argument("-t", "--times", type=int, default=2,
                            help="盲听和填空各放几遍（默认 2）")
    p_practice.add_argument("--gap", type=float, default=1.2)
    p_practice.add_argument("--listen", type=int, default=4,
                            help="每遍录音前放几次原声（默认 4）")
    p_practice.add_argument("--takes", type=int, default=3, help="录几遍（默认 3）")
    p_practice.add_argument("--device", default="0", help="麦克风编号")
    p_practice.add_argument("--seconds", type=float)
    p_practice.add_argument("-o", "--out", help="输出 png 路径")
    p_practice.add_argument("--min-sec", type=float)
    p_practice.add_argument("--max-sec", type=float)
    p_practice.set_defaults(func=cmd_practice)

    p_drill = sub.add_parser("drill", help="精听填空：挖掉被弱读的功能词")
    drill_group = p_drill.add_mutually_exclusive_group(required=True)
    drill_group.add_argument("--ref", help="原声 wav 路径")
    drill_group.add_argument("--segment", type=int, help="已导入的片段 id")
    p_drill.add_argument("-u", "--unit", type=int, help="片段内第 n 个练习单元")
    p_drill.add_argument("-t", "--times", type=int, default=3, help="先放几遍（默认 3）")
    p_drill.add_argument("--min-sec", type=float)
    p_drill.add_argument("--max-sec", type=float)
    p_drill.set_defaults(func=cmd_drill)

    p_listen = sub.add_parser("listen", help="盲听：不给文字，听完自评")
    listen_group = p_listen.add_mutually_exclusive_group(required=True)
    listen_group.add_argument("--ref", help="原声 wav 路径")
    listen_group.add_argument("--segment", type=int, help="已导入的片段 id")
    p_listen.add_argument("-u", "--unit", type=int, help="片段内第 n 个练习单元")
    p_listen.add_argument("-t", "--times", type=int, default=2, help="放几遍（默认 2）")
    p_listen.add_argument("--gap", type=float, default=1.2, help="两遍之间隔几秒")
    p_listen.add_argument("--min-sec", type=float,
                          help="练习单元的最短秒数。默认 0 = 严格一句一个；设成 1.5 会把短句并进下一句")
    p_listen.add_argument("--max-sec", type=float,
                          help="练习单元的最长秒数，超过会在最大停顿处再断（默认 6）")
    p_listen.set_defaults(func=cmd_listen)

    p_play = sub.add_parser("play", help="播放原声（默认不显示原文）")
    play_group = p_play.add_mutually_exclusive_group(required=True)
    play_group.add_argument("--ref", help="原声 wav 路径")
    play_group.add_argument("--segment", type=int, help="已导入的片段 id")
    p_play.add_argument("-u", "--unit", type=int, help="片段内第 n 个练习单元")
    p_play.add_argument("-t", "--times", type=int, default=1, help="放几遍（默认 1）")
    p_play.add_argument("--gap", type=float, default=0.8, help="两遍之间隔几秒")
    p_play.add_argument("--text", action="store_true", help="同时显示原文")
    p_play.add_argument("--min-sec", type=float,
                          help="练习单元的最短秒数。默认 0 = 严格一句一个；设成 1.5 会把短句并进下一句")
    p_play.add_argument("--max-sec", type=float,
                          help="练习单元的最长秒数，超过会在最大停顿处再断（默认 6）")
    p_play.set_defaults(func=cmd_play)

    p_progress = sub.add_parser("progress", help="查看跨会话的练习趋势")
    p_progress.add_argument("-s", "--segment", type=int)
    p_progress.add_argument("-u", "--unit", type=int)
    p_progress.set_defaults(func=cmd_progress)

    p_compare = sub.add_parser("compare", help="对比原声与你的录音")
    group = p_compare.add_mutually_exclusive_group(required=True)
    group.add_argument("--ref", help="原声 wav 路径")
    group.add_argument("--segment", type=int, help="已导入的片段 id")
    p_compare.add_argument("-u", "--unit", type=int,
                           help="只比对第 n 个练习单元（配合 --segment）")
    p_compare.add_argument("--user", required=True, action="append",
                           help="你的录音 wav 路径，可重复传多次（建议每轮录 3 遍）")
    p_compare.add_argument("-o", "--out", help="输出 png 路径")
    p_compare.add_argument("--min-sec", type=float,
                          help="练习单元的最短秒数。默认 0 = 严格一句一个；设成 1.5 会把短句并进下一句")
    p_compare.add_argument("--max-sec", type=float,
                          help="练习单元的最长秒数，超过会在最大停顿处再断（默认 6）")
    p_compare.set_defaults(func=cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
