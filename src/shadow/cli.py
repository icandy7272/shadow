"""shadow 命令行入口：import / list / export / compare。"""

from __future__ import annotations

import argparse
import sys
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
from .report.advice import build_advice, well_done
from .report.blocks import Flag, render_feedback


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


def cmd_compare(args: argparse.Namespace) -> int:
    try:
        media.validate_attempt(Path(args.user))
    except Exception as exc:
        print(f"录音不可用：{exc}", file=sys.stderr)
        return 1

    connection = _open_db()
    try:
        if args.segment is not None:
            suffix = "" if args.unit is None else f"-u{args.unit}"
            ref_path, ref_words, _ = _segment_reference(
                connection, args.segment,
                config.segment_audio_dir() / f"{args.segment}{suffix}.wav",
                unit=args.unit,
            )
        else:
            ref_path = Path(args.ref)
            ref_words = transcribe_words(ref_path)
        usr_words: tuple[Word, ...] = transcribe_words(Path(args.user))
    except Exception as exc:
        print(f"转写失败：{exc}", file=sys.stderr)
        return 1

    if not ref_words:
        print("原声转写为空，无法比较。", file=sys.stderr)
        return 1

    tokens = diff_words([w.text for w in ref_words], [w.text for w in usr_words])
    score = diff_accuracy(tokens)
    pairs = matched_pairs(tokens)
    rhythm = analyse_rhythm(ref_words, usr_words, pairs)
    ref_prosody = analyse(ref_path)
    usr_prosody = analyse(Path(args.user))

    advice = build_advice(
        ref_words=ref_words, usr_words=usr_words, tokens=tokens, rhythm=rhythm,
        ref_prosody=ref_prosody, usr_prosody=usr_prosody,
    )
    # 停顿属于节奏，只标在图 1；图 2 只标词本身的音高/时长问题
    flags = tuple(
        Flag(usr_index=usr_index, text=item.flag)
        for item, usr_index in _flag_targets(advice, ref_words, tokens)
        if item.kind != "missed_pause"
    )
    missed = tuple(item.ref_index for item in advice[:MAX_ADVICE]
                   if item.kind == "missed_pause")

    out_path = Path(args.out or "feedback.png")
    render_feedback(
        ref_words=ref_words, usr_words=usr_words, tokens=tokens, rhythm=rhythm,
        ref_prosody=ref_prosody, usr_prosody=usr_prosody, flags=flags,
        missed_pauses=missed,
        accuracy=score, text=" ".join(w.text for w in ref_words), out_path=out_path,
    )

    _print_report(tokens, score, rhythm, advice,
                  well_done(ref_words=ref_words, usr_words=usr_words,
                            tokens=tokens, rhythm=rhythm, advice=advice),
                  out_path)
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


def _print_report(tokens, score, rhythm, advice, good, out_path) -> None:
    print(f"\n可懂度 {score * 100:.0f}%（{sum(1 for t in tokens if t.ref_index is not None)} 个词）")
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

    pause = ("—" if rhythm.pause_ratio is None
             else f"{rhythm.pause_ratio:.2f}x")
    print(f"\n发声 {rhythm.speech_ratio:.2f}x    停顿 {pause}    "
          f"整句 {rhythm.span_ratio:.2f}x")

    if advice:
        print(f"\n下一遍改这 {min(MAX_ADVICE, len(advice))} 处，按重要性排：\n")
        for number, item in enumerate(advice[:MAX_ADVICE], 1):
            print(f"  {number}. {item.title}")
            print(f"     现状：{item.detail}")
            print(f"     怎么做：{item.action}\n")
    else:
        print("\n这一句没有明显偏差，可以换下一个单元了。\n")

    if good:
        print(f"这些词你做对了，保持：{' / '.join(good[:12])}")
    print(f"\n反馈图已写入 {out_path}")


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

    p_compare = sub.add_parser("compare", help="对比原声与你的录音")
    group = p_compare.add_mutually_exclusive_group(required=True)
    group.add_argument("--ref", help="原声 wav 路径")
    group.add_argument("--segment", type=int, help="已导入的片段 id")
    p_compare.add_argument("-u", "--unit", type=int,
                           help="只比对第 n 个练习单元（配合 --segment）")
    p_compare.add_argument("--user", required=True, help="你的录音 wav 路径")
    p_compare.add_argument("-o", "--out", help="输出 png 路径")
    p_compare.set_defaults(func=cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
