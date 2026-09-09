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
from .analysis.diff import diff_words, matched_pairs
from .analysis.prosody import analyse, word_contour
from .drill.units import split_into_units
from .ingest.pipeline import import_source
from .ingest.transcriber import transcribe_words
from .models import Word
from .analysis.rhythm import analyse_rhythm
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


def _segment_units(connection, segment_id: int):
    """取出片段及其练习单元。"""
    segment = db.get_segment(connection, segment_id)
    if segment is None:
        raise CliError(f"片段 {segment_id} 不存在")
    source = db.get_source(connection, segment["source_id"])
    if source is None or not source["audio_path"]:
        raise CliError(f"片段 {segment_id} 的素材音频缺失")
    return segment, source, split_into_units(segment["words"])


def _segment_reference(connection, segment_id: int, dest: Path, *, unit: int | None = None):
    """导出音频，并把词时间戳平移到以裁剪起点为 0。

    unit=None 导出整个片段；给了 unit 就只导出那个练习单元（首尾各留一点余量，
    免得切掉词头的爆破音）。
    """
    segment, source, units = _segment_units(connection, segment_id)

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
        segment, _, units = _segment_units(connection, args.segment)
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
            connection, args.segment, dest, unit=args.unit
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
            unit=args.unit,
        )[:2]
    ref_path = Path(args.ref)
    return ref_path, transcribe_words(ref_path)


def _compare(connection, *, ref_path, ref_words, paths, out_path,
             segment_id=None, unit_index=None) -> int:
    ref_prosody = analyse(ref_path)
    metrics: list[TakeMetrics] = []
    details = []
    for path in paths:
        usr_words = transcribe_words(path)
        tokens = diff_words([w.text for w in ref_words], [w.text for w in usr_words])
        rhythm = analyse_rhythm(ref_words, usr_words, matched_pairs(tokens))
        usr_prosody = analyse(path)
        advice = build_advice(
            ref_words=ref_words, usr_words=usr_words, tokens=tokens,
            rhythm=rhythm, ref_prosody=ref_prosody, usr_prosody=usr_prosody,
        )
        metrics.append(TakeMetrics(
            accuracy=diff_accuracy(tokens), speech_ratio=rhythm.speech_ratio,
            pause_ratio=rhythm.pause_ratio, advice=advice,
        ))
        details.append((path, usr_words, tokens, rhythm, usr_prosody, advice))

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
        _save_run(connection, segment_id, unit_index, details, metrics)

    _print_summary(summary, paths, tokens, out_path)
    return 0


def _save_run(connection, segment_id, unit_index, details, metrics) -> None:
    """把这一轮存进库，进度才能跨会话累积。"""
    run_id = db.start_run(connection, segment_id=segment_id, unit_index=unit_index)
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
            segment_id=args.segment, unit_index=args.unit,
        )
    except Exception as exc:
        print(f"比对失败：{exc}", file=sys.stderr)
        return 1


def cmd_play(args: argparse.Namespace) -> int:
    connection = _open_db()
    try:
        ref_path, ref_words = _reference_for(connection, args)
    except Exception as exc:
        print(f"读取原声失败：{exc}", file=sys.stderr)
        return 1
    print(" ".join(w.text for w in ref_words))
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


def cmd_record(args: argparse.Namespace) -> int:
    connection = _open_db()
    try:
        ref_path, ref_words = _reference_for(connection, args)
    except Exception as exc:
        print(f"读取原声失败：{exc}", file=sys.stderr)
        return 1

    span = ref_words[-1].end - ref_words[0].start if ref_words else 5.0
    seconds = args.seconds or min(span * 1.8 + 1.5, 120.0)

    devices = media.list_input_devices()
    if devices:
        current = dict(devices).get(args.device, "?")
        print("麦克风：" + "，".join(f"[{i}] {n}" for i, n in devices))
        print(f"这次用 [{args.device}] {current}（换设备加 --device N）\n")

    print(f"原声：{' '.join(w.text for w in ref_words)}")
    print(f"每遍录 {seconds:.0f} 秒，共 {args.takes} 遍。\n")

    if args.listen:
        print(f"先听 {args.listen} 遍，什么都别做，让声音的形状进去：")
        try:
            for index in range(1, args.listen + 1):
                print(f"  {index}/{args.listen}", end="\r", flush=True)
                media.play(ref_path, times=1, gap=0.0)
                if index < args.listen:
                    time.sleep(0.6)
            print("  听完了。      \n")
        except KeyboardInterrupt:
            print("\n  跳过试听。\n")
        except Exception as exc:
            print(f"\n  播放失败（不影响录音）：{exc}\n", file=sys.stderr)

    stamp = datetime.now().strftime("%m%d-%H%M%S")
    label = f"{args.segment}" if args.segment is not None else "ref"
    if args.unit is not None:
        label += f"-u{args.unit}"

    paths: list[Path] = []
    for index in range(1, args.takes + 1):
        try:
            input(f"第 {index}/{args.takes} 遍 —— 按回车开始")
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。", file=sys.stderr)
            return 1
        dest = config.attempt_audio_dir() / f"{label}-{stamp}-{index}.wav"
        try:
            media.record(dest, seconds=seconds, device=args.device)
            media.validate_attempt(dest)
        except Exception as exc:
            print(f"  第 {index} 遍不可用：{exc}", file=sys.stderr)
            return 1
        print(f"  录好了 → {dest.name}")
        paths.append(dest)

    print()
    try:
        return _compare(
            connection, ref_path=ref_path, ref_words=ref_words, paths=paths,
            out_path=Path(args.out or "feedback.png"),
            segment_id=args.segment, unit_index=args.unit,
        )
    except Exception as exc:
        print(f"比对失败：{exc}", file=sys.stderr)
        return 1


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

    print(f"{'时间':<14}{'片段':>5}{'单元':>5}{'遍数':>5}"
          f"{'可懂':>7}{'发声':>7}{'停顿':>7}   反复出现的问题")
    for row in runs:
        takes = db.run_metrics(connection, row["id"])
        if not takes:
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
        print(f"{_local_time(row['started_at']):<14}"
              f"{row['segment_id']:>5}{(row['unit_index'] or '-'):>5}{len(takes):>5}"
              f"{statistics.median(t['accuracy'] for t in takes) * 100:>6.0f}%"
              f"{statistics.median(t['speech_ratio'] for t in takes):>7.2f}"
              f"{(statistics.median(pauses) if pauses else float('nan')):>7.2f}"
              f"   {'、'.join(repeated[:3]) if repeated else '—'}")
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


def _print_summary(summary: TakeSummary, paths, tokens, out_path) -> None:
    if summary.count > 1:
        print(f"\n{summary.count} 次录音，取中位数（括号内是范围）")
    accuracy = summary.accuracy
    print(f"\n可懂度 {accuracy.median * 100:.0f}%"
          + ("" if accuracy.width < 0.005
             else f"（{accuracy.low * 100:.0f}–{accuracy.high * 100:.0f}%）"))
    problems = [t for t in tokens if t.kind != "equal"]
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
    p_units.set_defaults(func=cmd_units)

    p_export = sub.add_parser("export", help="导出音频用于跟读")
    p_export.add_argument("segment", type=int)
    p_export.add_argument("-u", "--unit", type=int, help="只导出第 n 个练习单元")
    p_export.add_argument("-o", "--out")
    p_export.set_defaults(func=cmd_export)

    p_record = sub.add_parser("record", help="录音并立即比对（推荐每轮录 3 遍）")
    record_group = p_record.add_mutually_exclusive_group(required=True)
    record_group.add_argument("--ref", help="原声 wav 路径")
    record_group.add_argument("--segment", type=int, help="已导入的片段 id")
    p_record.add_argument("-u", "--unit", type=int, help="片段内第 n 个练习单元")
    p_record.add_argument("-n", "--takes", type=int, default=3, help="录几遍（默认 3）")
    p_record.add_argument("--device", default="0", help="麦克风编号，默认 0")
    p_record.add_argument("--listen", type=int, default=0,
                          help="录之前先放几遍原声（建议 5-10）")
    p_record.add_argument("--seconds", type=float, help="每遍录多少秒，默认按原声长度自动定")
    p_record.add_argument("-o", "--out", help="输出 png 路径")
    p_record.set_defaults(func=cmd_record)

    p_play = sub.add_parser("play", help="播放原声")
    play_group = p_play.add_mutually_exclusive_group(required=True)
    play_group.add_argument("--ref", help="原声 wav 路径")
    play_group.add_argument("--segment", type=int, help="已导入的片段 id")
    p_play.add_argument("-u", "--unit", type=int, help="片段内第 n 个练习单元")
    p_play.add_argument("-n", "--times", type=int, default=1, help="放几遍（默认 1）")
    p_play.add_argument("--gap", type=float, default=0.8, help="两遍之间隔几秒")
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
    p_compare.set_defaults(func=cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
