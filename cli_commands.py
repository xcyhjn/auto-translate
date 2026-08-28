"""Composable command-line dispatch for the autosub_zh workflow.

The module deliberately contains only argument parsing and adapters.  Subtitle,
translation, QA, and burn behavior remains owned by the existing modules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .pipeline_core import burn_subtitle
from .pipeline_runner import run_pipeline_from_config
from .qa import qa_check, qa_final_ass_file, qa_glossary_consistency
from .segment_io import load_segments, save_segments
from .translate import translate_segments

COMMANDS = ("pipeline", "translate", "qa", "burn", "init")
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FAILED = 1


def _add_dry_run(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析参数并显示计划，不读取媒体、不调用网络或写入产物。",
    )


def build_commands_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autosub_zh",
        description="组合式字幕工作流 CLI。旧式单命令调用仍由 autosub_zh.cli 兼容。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, title="子命令")

    pipeline = subparsers.add_parser("pipeline", help="按配置运行现有完整流水线。")
    pipeline.add_argument("input", help="输入视频或音频路径。")
    pipeline.add_argument("--config", default="ui_config.json", help="JSON 配置文件路径。")
    pipeline.add_argument("--output-root", default=None, help="流水线输出根目录。")
    _add_dry_run(pipeline)

    translate = subparsers.add_parser("translate", help="翻译已有字幕片段 JSON。")
    translate.add_argument("segments", help="输入字幕片段 JSON 路径。")
    translate.add_argument("-o", "--output", required=True, help="输出字幕片段 JSON 路径。")
    translate.add_argument("--src-lang", default=None)
    translate.add_argument("--dst-lang", default="zh-Hans")
    translate.add_argument("--glossary", default=None)
    translate.add_argument("--translation-model", default="gpt-5.4")
    translate.add_argument("--translation-chunk-size", type=int, default=40)
    translate.add_argument("--translation-retries", type=int, default=2)
    translate.add_argument("--openai-base-url", default=None)
    _add_dry_run(translate)

    qa = subparsers.add_parser("qa", help="检查字幕片段 JSON 或 ASS 文件。")
    qa.add_argument("input", help="字幕片段 JSON 或 ASS 文件路径。")
    qa.add_argument("--dst-lang", default="zh-Hans")
    qa.add_argument("--glossary", default=None)
    qa.add_argument("--report", "--save-report", dest="report", default=None)
    _add_dry_run(qa)

    burn = subparsers.add_parser("burn", help="调用现有 ASS 硬压适配器。")
    burn.add_argument("video", help="输入视频路径。")
    burn.add_argument("subtitle", help="ASS 字幕路径。")
    burn.add_argument("output", help="输出视频路径。")
    burn.add_argument("--preview-seconds", type=int, default=None)
    _add_dry_run(burn)

    init = subparsers.add_parser("init", help="创建缺失的示例配置，或显示初始化帮助。")
    init.add_argument(
        "--output",
        default="autosub_zh.config.example.json",
        help="示例配置输出路径；已存在时不会覆盖。",
    )
    _add_dry_run(init)
    return parser


def parse_command_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_commands_parser().parse_args(argv)


def is_command_invocation(argv: list[str]) -> bool:
    return bool(argv and argv[0] in COMMANDS)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 无效：{path}: {exc}") from exc


def _print_plan(args: argparse.Namespace) -> int:
    plan = {"command": args.command, "dry_run": True}
    for key, value in vars(args).items():
        if key not in {"command", "dry_run"}:
            plan[key] = value
    print(json.dumps(plan, ensure_ascii=False, indent=2, default=str))
    return EXIT_OK


def _dispatch_pipeline(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    if not config_path.is_file():
        raise ValueError(f"配置文件不存在：{config_path}")
    config = _load_json(config_path)
    if not isinstance(config, dict):
        raise ValueError(f"配置文件必须是 JSON 对象：{config_path}")
    kwargs: dict[str, Any] = {"video_path": Path(args.input), "config": config}
    if args.output_root:
        kwargs["output_root"] = Path(args.output_root)
    result = run_pipeline_from_config(**kwargs)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return EXIT_OK


def _dispatch_translate(args: argparse.Namespace) -> int:
    segments = load_segments(args.segments)
    translated = translate_segments(
        segments,
        src_lang=args.src_lang,
        dst_lang=args.dst_lang,
        glossary=args.glossary,
        enabled=True,
        provider="openai",
        model=args.translation_model,
        chunk_size=args.translation_chunk_size,
        max_retries=args.translation_retries,
        openai_base_url=args.openai_base_url,
    )
    save_segments(translated, args.output)
    print(f"Saved translated segments: {args.output}")
    return EXIT_OK


def _dispatch_qa(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if input_path.suffix.lower() == ".ass":
        if args.glossary:
            raise ValueError("--glossary 只支持字幕片段 JSON，不能用于 ASS 文件。")
        report = qa_final_ass_file(input_path, dst_lang=args.dst_lang)
    else:
        segments = load_segments(input_path)
        report = qa_check(segments, dst_lang=args.dst_lang)
        if args.glossary:
            glossary_report = qa_glossary_consistency(segments, args.glossary)
            report.errors.extend(glossary_report.errors)
            report.warnings.extend(glossary_report.warnings)
    payload = {"errors": report.errors, "warnings": report.warnings}
    if args.report:
        Path(args.report).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved QA report: {args.report}")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return EXIT_FAILED if report.has_blocking_errors else EXIT_OK


def _dispatch_burn(args: argparse.Namespace) -> int:
    result = burn_subtitle(Path(args.video), Path(args.subtitle), Path(args.output), args.preview_seconds)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return EXIT_OK


def _dispatch_init(args: argparse.Namespace) -> int:
    target = Path(args.output)
    if target.exists():
        print(f"示例配置已存在，未覆盖：{target}")
        return EXIT_OK
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "src_lang": "en",
                "dst_lang": "zh-Hans",
                "model": "base",
                "device": "auto",
                "compute_type": "default",
                "beam_size": 5,
                "translation_model": "gpt-5.4",
                "translation_chunk_size": 40,
                "translation_retries": 2,
                "openai_base_url": "",
                "load_existing_segments": False,
                "preview_seconds": None,
                "style": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Created example config: {target}")
    return EXIT_OK


_DISPATCHERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "pipeline": _dispatch_pipeline,
    "translate": _dispatch_translate,
    "qa": _dispatch_qa,
    "burn": _dispatch_burn,
    "init": _dispatch_init,
}


def dispatch(args: argparse.Namespace) -> int:
    if getattr(args, "dry_run", False):
        return _print_plan(args)
    try:
        return _DISPATCHERS[args.command](args)
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_FAILED
