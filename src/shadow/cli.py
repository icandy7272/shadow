"""shadow 命令行入口：import / list / export / compare。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from . import config, db, media
from .analysis.align import warp_user_times
from .analysis.diff import accuracy as diff_accuracy
from .analysis.diff import diff_words, matched_pairs
from .analysis.prosody import analyse
from .analysis.timing import word_timings
from .ingest.pipeline import import_source
from .ingest.transcriber import transcribe_words
from .models import Word
from .report.plot import render_comparison


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


def _segment_reference(connection, segment_id: int, dest: Path):
    """导出片段音频，并把词时间戳平移到以片段起点为 0。"""
    segment = db.get_segment(connection, segment_id)
    if segment is None:
        raise SystemExit(f"片段 {segment_id} 不存在")
    source = db.get_source(connection, segment["source_id"])
    if source is None or not source["audio_path"]:
        raise SystemExit(f"片段 {segment_id} 的素材音频缺失")
    media.cut_segment(
        Path(source["audio_path"]), dest,
        start=segment["start_sec"], end=segment["end_sec"],
    )
    offset = segment["start_sec"]
    words = tuple(
        replace(word, start=word.start - offset, end=word.end - offset)
        for word in segment["words"]
    )
    return dest, words, segment["text"]


def cmd_export(args: argparse.Namespace) -> int:
    connection = _open_db()
    dest = Path(args.out or config.segment_audio_dir() / f"{args.segment}.wav")
    try:
        path, _, text = _segment_reference(connection, args.segment, dest)
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
            ref_path, ref_words, _ = _segment_reference(
                connection, args.segment,
                config.segment_audio_dir() / f"{args.segment}.wav",
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

    ref_prosody = analyse(ref_path)
    usr_prosody = analyse(Path(args.user))
    warped = warp_user_times(
        usr_prosody.times,
        ref_words=ref_words,
        usr_words=usr_words,
        pairs=matched_pairs(tokens),
        ref_duration=ref_prosody.duration,
        usr_duration=usr_prosody.duration,
    )
    timings = word_timings(ref_words, usr_words, tokens)

    out_path = Path(args.out or "comparison.png")
    render_comparison(
        ref_prosody=ref_prosody,
        usr_prosody=usr_prosody,
        usr_times_warped=warped,
        timings=timings,
        out_path=out_path,
        title=ref_path.name,
        accuracy=score,
    )

    print(f"可懂度 {score * 100:.0f}%（{len(ref_words)} 个词）")
    problems = [t for t in tokens if t.kind != "equal"]
    if problems:
        print("机器没听对的词：")
        for token in problems[:20]:
            if token.kind == "missing":
                print(f"  漏  {token.ref_text}")
            elif token.kind == "wrong":
                print(f"  错  {token.ref_text}  ->  听成 {token.usr_text}")
            else:
                print(f"  多  {token.usr_text}")
    print(f"对比图已写入 {out_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shadow", description="英语影子跟读训练工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="从 URL 导入素材")
    p_import.add_argument("url")
    p_import.set_defaults(func=cmd_import)

    p_list = sub.add_parser("list", help="列出已导入素材")
    p_list.add_argument("-s", "--segments", action="store_true", help="同时列出片段")
    p_list.set_defaults(func=cmd_list)

    p_export = sub.add_parser("export", help="导出片段音频用于跟读")
    p_export.add_argument("segment", type=int)
    p_export.add_argument("-o", "--out")
    p_export.set_defaults(func=cmd_export)

    p_compare = sub.add_parser("compare", help="对比原声与你的录音")
    group = p_compare.add_mutually_exclusive_group(required=True)
    group.add_argument("--ref", help="原声 wav 路径")
    group.add_argument("--segment", type=int, help="已导入的片段 id")
    p_compare.add_argument("--user", required=True, help="你的录音 wav 路径")
    p_compare.add_argument("-o", "--out", help="输出 png 路径")
    p_compare.set_defaults(func=cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
