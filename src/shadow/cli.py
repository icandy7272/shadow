"""shadow 命令行入口：import / list / export / compare。"""

from __future__ import annotations

import argparse
import statistics
import sys
from datetime import datetime
from dataclasses import replace
from pathlib import Path

from . import config, db, media, review
from .analysis.diff import accuracy as diff_accuracy
from .drill.units import ends_mid_phrase, split_into_units
from .ingest.pipeline import import_source
from .ingest.transcriber import transcribe_words


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

    # 导入完就地体检：切坏的单元只有扫一遍才看得出来，
    # 而「想起来才跑的检查」等于没有——库里那五处切坏躺了很久没人发现。
    total, bad, broken, silent = _survey(connection, source_id)
    print(f"  {total} 个句子", end="")
    if bad or broken or silent:
        print(f"，其中 {len(bad)} 句断在词组中间、{len(broken)} 句时间戳异常、"
              f"{len(silent)} 句音频里没有（跑 shadow audit 看是哪些）")
    else:
        print("，都能练")
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
        start, end = media.unit_bounds(Path(source["audio_path"]), words,
                                       low=segment["start_sec"],
                                       high=segment["end_sec"])

    media.cut_segment(Path(source["audio_path"]), dest, start=start, end=end)
    # 裁剪点贴到停顿上之后可能晚于转写给的首词起点，钳到 0
    rebased = tuple(
        replace(word, start=max(0.0, word.start - start), end=word.end - start)
        for word in words
    )
    return dest, rebased, " ".join(word.text for word in rebased)


def cmd_realign(args: argparse.Namespace) -> int:
    """用强制对齐改写库里的词时间戳。

    Whisper 的时间戳是猜的：首词起点中位偏早 0.375 秒，还见过把末词排到
    声音之外、把整句停顿报成 0。原文本来就在手上，没有理由去猜。
    """
    from .analysis.align import align_words, available

    if not available():
        print("没装 torchaudio，跑不了强制对齐。", file=sys.stderr)
        return 1

    connection = _open_db()
    fixed = skipped = 0
    for source in db.list_sources(connection):
        path = Path(source["audio_path"] or "")
        if not path.exists():
            continue
        for row in db.list_segments(connection, source["id"]):
            if args.segment is not None and row["id"] != args.segment:
                continue
            segment = db.get_segment(connection, row["id"])
            dest = config.segment_audio_dir() / f"_realign-{row['id']}.wav"
            try:
                media.cut_segment(path, dest, start=segment["start_sec"],
                                  end=segment["end_sec"])
            except Exception as exc:
                print(f"  片段 {row['id']} 裁剪失败：{exc}", file=sys.stderr)
                skipped += 1
                continue
            origin = segment["start_sec"]
            rebased = tuple(replace(w, start=w.start - origin, end=w.end - origin)
                            for w in segment["words"])
            aligned = align_words(dest, rebased)
            dest.unlink(missing_ok=True)
            if aligned is None:
                print(f"  片段 {row['id']} 对不上，保留原时间戳")
                skipped += 1
                continue
            db.update_segment_words(connection, row["id"], tuple(
                replace(w, start=w.start + origin, end=w.end + origin)
                for w in aligned))
            fixed += 1
            print(f"  片段 {row['id']} 已对齐（{len(aligned)} 词）")

    # 单元音频是按旧时间戳裁的，得重裁
    for stale in config.segment_audio_dir().glob("*-u*.wav"):
        stale.unlink(missing_ok=True)
    print(f"\n对齐 {fixed} 个片段，跳过 {skipped} 个。单元音频缓存已清，下次访问重裁。")
    return 0


def _same_sentence(left: str, right: str) -> bool:
    return "".join(left.lower().split()) == "".join(right.lower().split())


def cmd_recompute(args: argparse.Namespace) -> int:
    """拿现在的代码把历史录音全部重算一遍。

    词边界、发声起点、判定规则都改过好几轮，库里存的还是当时算出来的。
    录音都在磁盘上，重算一遍，趋势线才第一次可信。
    """
    connection = _open_db()
    done = moved = skipped = 0
    for run in db.list_runs(connection):
        rows = db.run_attempts(connection, run["id"])
        paths = [Path(row["audio_path"]) for row in rows]
        if not rows or not all(p.exists() for p in paths):
            continue

        segment, _source, units = _segment_units(connection, run["segment_id"])
        index = next((i for i, unit in enumerate(units, 1)
                      if _same_sentence(" ".join(w.text for w in unit),
                                        run["unit_text"] or "")), None)
        if index is None:
            print(f"  轮次 {run['id']}：库里已经找不到这句，跳过")
            skipped += 1
            continue
        if index != run["unit_index"]:
            moved += 1

        dest = config.segment_audio_dir() / f"{run['segment_id']}-u{index}.wav"
        ref_path, ref_words, text = _segment_reference(
            connection, run["segment_id"], dest, unit=index)
        result = review.evaluate(ref_path, ref_words, paths,
                                 transcribe=transcribe_words)
        if result is None:
            print(f"  轮次 {run['id']}：没有一遍能用，指标清空")
            for row in rows:
                db.set_attempt_metrics(connection, row["id"], None)
            skipped += 1
            continue

        fresh = {str(take.path): take for take in result.takes}
        for row in rows:
            take = fresh.get(row["audio_path"])
            db.set_attempt_metrics(connection, row["id"], None if take is None else {
                "accuracy": diff_accuracy(take.tokens),
                "speech_ratio": take.rhythm.speech_ratio,
                "pause_ratio": take.rhythm.pause_ratio,
                "issues": [{"kind": a.kind, "ref_index": a.ref_index,
                            "score": a.score, "title": a.title} for a in take.advice],
            })
        db.relabel_run(connection, run["id"], unit_index=index, unit_text=text)
        done += 1
        print(f"  轮次 {run['id']}  {run['segment_id']}/{index}  "
              f"{len(result.takes)}/{len(rows)} 遍可用  {text[:40]}")

    print(f"\n重算 {done} 轮，序号校正 {moved} 轮，跳过 {skipped} 轮。")
    return 0


def _survey(connection, source_id: int | None = None):
    """扫一遍切出来的单元，返回 (总数, 切坏的, 时间戳异常的, 音频里没有的)。"""
    total, bad, broken, silent = 0, [], [], []
    for source in db.list_sources(connection):
        if source_id is not None and source["id"] != source_id:
            continue
        for row in db.list_segments(connection, source["id"]):
            segment = db.get_segment(connection, row["id"])
            for index, unit in enumerate(split_into_units(segment["words"]), 1):
                total += 1
                text = " ".join(word.text for word in unit)
                problem = media.unit_problem(source["audio_path"], unit)
                if problem == media.PROBLEM_CRUSHED:
                    broken.append((row["id"], index, text))
                elif problem == media.PROBLEM_SILENT:
                    silent.append((row["id"], index, text))
                elif ends_mid_phrase(unit):
                    bad.append((row["id"], index, text))
    return total, bad, broken, silent


def cmd_audit(args: argparse.Namespace) -> int:
    """扫全库，把切坏的单元挑出来。

    切分规则改一次，就得这么扫一次——只靠合成数据的单测，发现不了真素材
    里的切坏。「在最大停顿处断开」这条规则在库里坏了五处，全是这么找出来的。
    """
    connection = _open_db()
    total, bad, broken, silent = _survey(connection)
    for segment_id, index, text in broken:
        print(f"  ⚠ {segment_id}/{index} 时间戳异常：{text[:60]}")
    for segment_id, index, text in silent:
        print(f"  ⚠ {segment_id}/{index} 音频里没有这句：{text[:60]}")
    for segment_id, index, text in bad:
        print(f"  ✂ {segment_id}/{index} 断在词组中间：…{text[-50:]}")
    print(f"\n共 {total} 个单元：切坏 {len(bad)}，时间戳异常 {len(broken)}，"
          f"没有声音 {len(silent)}")
    return 0


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
    source = db.get_source(connection, segment["source_id"])
    audio = source["audio_path"] if source else None
    flags = {media.PROBLEM_CRUSHED: "  ⚠ 时间戳异常，无法练习",
             media.PROBLEM_SILENT: "  ⚠ 音频里没有这句，无法练习"}
    for index, unit in enumerate(units, 1):
        duration = unit[-1].end - unit[0].start
        blanks = sum(word.is_blank for word in unit)
        text = " ".join(word.text for word in unit)
        flag = flags.get(media.unit_problem(audio, unit), "")
        print(f"  {index:2d}. [{duration:4.1f}s {len(unit):2d}词 {blanks}空]  {text}{flag}")
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










BLIND_SCALE = (
    "1  几乎没听懂",
    "2  抓到几个词",
    "3  大意懂了，细节丢了",
    "4  基本都懂，个别词没抓住",
    "5  每个词都听清了",
)








BLIND_SCALE = (
    "1  几乎没听懂",
    "2  抓到几个词",
    "3  大意懂了，细节丢了",
    "4  基本都懂，个别词没抓住",
    "5  每个词都听清了",
)
















































def _local_time(stamp: str) -> str:
    """库里存的是 UTC，显示要转本地时区，否则跨时区看着像是别人练的。"""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%m-%d %H:%M")
    except ValueError:
        return stamp[:16]


def _lan_address() -> str | None:
    """本机在局域网里的地址。手机要用就得知道它，省得自己去翻设置。"""
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.168.1.1", 80))      # 不发包，只为拿本机出口地址
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def _reload_dirs() -> list[str]:
    """自动重载只盯自己的代码。

    默认盯整个工作目录，而没装 watchfiles 时 uvicorn 每 0.25 秒把目录下所有 .py
    stat 一遍——连 .venv 一共 8604 个，监工进程空闲时一直占着半个核。
    自己的代码只有 33 个。
    """
    return [str(Path(__file__).parent)]


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    _open_db()      # 确保库和目录就绪
    host = "0.0.0.0" if args.lan else args.host      # noqa: S104
    print(f"打开 http://{'127.0.0.1' if args.lan else host}:{args.port}")
    if args.lan:
        address = _lan_address()
        if address:
            print(f"手机同一个 Wi-Fi 下打开 http://{address}:{args.port}")
        print("注意：手机上录不了音——浏览器只在 HTTPS 或 localhost 下给"
              "麦克风权限。盲听和填空照常。")
    uvicorn.run("shadow.web.app:app", host=host, port=args.port,
                reload=args.reload, reload_dirs=_reload_dirs(), log_level="warning")
    return 0


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

    p_audit = sub.add_parser("audit", help="扫全库，挑出切坏的练习单元")
    p_audit.set_defaults(func=cmd_audit)

    p_recompute = sub.add_parser("recompute", help="拿现在的代码重算所有历史录音")
    p_recompute.set_defaults(func=cmd_recompute)

    p_realign = sub.add_parser("realign", help="用强制对齐改写词时间戳")
    p_realign.add_argument("-s", "--segment", type=int, help="只对齐这一个片段")
    p_realign.set_defaults(func=cmd_realign)

    p_export = sub.add_parser("export", help="导出音频用于跟读")
    p_export.add_argument("segment", type=int)
    p_export.add_argument("-u", "--unit", type=int, help="只导出第 n 个练习单元")
    p_export.add_argument("-o", "--out")
    p_export.add_argument("--min-sec", type=float,
                          help="练习单元的最短秒数。默认 0 = 严格一句一个；设成 1.5 会把短句并进下一句")
    p_export.add_argument("--max-sec", type=float,
                          help="练习单元的最长秒数，超过会在最大停顿处再断（默认 6）")
    p_export.set_defaults(func=cmd_export)






    p_serve = sub.add_parser("serve", help="启动网页版")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--lan", action="store_true",
                         help="局域网内可访问，手机同 Wi-Fi 就能打开")
    p_serve.add_argument("--port", type=int, default=8000)
    # 默认开自动重载：本地单人工具，服务一开就是一整天，
    # 改了代码而页面还跑着旧进程，给出的反馈会是错的，而且看不出来。
    p_serve.add_argument("--no-reload", dest="reload", action="store_false",
                         help="关掉改代码自动重载")
    p_serve.set_defaults(reload=True)
    p_serve.set_defaults(func=cmd_serve)

    p_progress = sub.add_parser("progress", help="查看跨会话的练习趋势")
    p_progress.add_argument("-s", "--segment", type=int)
    p_progress.add_argument("-u", "--unit", type=int)
    p_progress.set_defaults(func=cmd_progress)


    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
