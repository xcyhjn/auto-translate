from __future__ import annotations

import argparse
import json
from pathlib import Path

from .style_learning import write_style_learning_artifacts
from .workflow_profiles import find_existing_ass_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从机器字幕 segments 和手修 ASS 中抽取人工风格样例。"
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="项目输出目录；若提供，则默认读取其中的 05_translated_segments.json 和置顶 ASS 产物。",
    )
    parser.add_argument(
        "--segments",
        default=None,
        help="机器字幕 segments JSON 路径。",
    )
    parser.add_argument(
        "--manual-ass",
        default=None,
        help="手修后的 ASS 路径。",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="风格学习产物输出目录；默认写回 project-dir。",
    )
    return parser.parse_args()


def resolve_inputs(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    if args.project_dir:
        project_dir = Path(args.project_dir)
        segments_path = Path(args.segments) if args.segments else project_dir / "05_translated_segments.json"
        manual_ass_path = Path(args.manual_ass) if args.manual_ass else find_existing_ass_path(project_dir)
        if not manual_ass_path:
            raise SystemExit(f"未找到 ASS 产物：{project_dir}")
        output_dir = Path(args.output_dir) if args.output_dir else project_dir
        return segments_path, manual_ass_path, output_dir

    if not args.segments or not args.manual_ass or not args.output_dir:
        raise SystemExit("未提供 --project-dir 时，必须同时提供 --segments、--manual-ass、--output-dir。")

    return Path(args.segments), Path(args.manual_ass), Path(args.output_dir)


def main() -> None:
    args = parse_args()
    segments_path, manual_ass_path, output_dir = resolve_inputs(args)
    manifest = write_style_learning_artifacts(
        segments_path=segments_path,
        manual_ass_path=manual_ass_path,
        output_dir=output_dir,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
