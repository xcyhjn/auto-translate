from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .asr import transcribe_audio
from .media import enhance_audio_for_asr, extract_audio, probe_media
from .qa import qa_check
from .segment_io import load_segments, save_segments
from .style_learning import write_style_learning_artifacts
from .workflow_profiles import find_existing_ass_path, project_artifact_path
from .subtitle_io import write_srt
from .timing import refine_timing
from .translate import dry_run_openai_translation, translate_segments


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从视频或音频生成 SRT 字幕，并可选接入 OpenAI 兼容接口翻译。"
    )
    parser.add_argument("input", nargs="?", help="输入视频或音频路径。")
    parser.add_argument(
        "-o",
        "--output",
        help="输出 .srt 路径；默认使用 <输入名>.<源语言>.srt。",
    )
    parser.add_argument(
        "--src-lang",
        default=None,
        help="源语言代码，例如 en、ja、fr；不填则由 faster-whisper 自动检测。",
    )
    parser.add_argument(
        "--dst-lang",
        default="zh-Hans",
        help="启用 --translate 时的目标字幕语言。",
    )
    parser.add_argument(
        "--model",
        default="base",
        help="faster-whisper 模型名，例如 tiny、base、small、medium、large-v3、distil-large-v3。",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="ASR 运行设备：auto、cpu 或 cuda。",
    )
    parser.add_argument(
        "--compute-type",
        default="default",
        help="ASR 计算类型：default、float16、int8_float16 或 int8。",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=5,
        help="ASR 解码 beam size；更高可能提升质量，但会变慢。",
    )
    parser.add_argument(
        "--asr-audio-mode",
        default="off",
        choices=["off", "whisper", "strong_whisper"],
        help="ASR 前是否生成增强音频；whisper 会轻度增强，strong_whisper 会更激进。",
    )
    parser.add_argument(
        "--asr-audio-gain-db",
        type=float,
        default=6.0,
        help="增强音频时额外提升的分贝数。",
    )
    parser.add_argument(
        "--asr-vad",
        default="auto",
        choices=["auto", "on", "off"],
        help="ASR 阶段的 VAD 策略；auto 在增强模式下默认关闭。",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="中间音频目录；不填则使用临时目录。",
    )
    parser.add_argument(
        "--translate",
        action="store_true",
        help="ASR 后调用翻译接口生成目标语言字幕。",
    )
    parser.add_argument(
        "--translate-provider",
        default="openai",
        choices=["openai"],
        help="翻译提供方；当前只支持 openai 兼容接口。",
    )
    parser.add_argument(
        "--translation-model",
        default="gpt-5.4",
        help="字幕翻译使用的 OpenAI 兼容模型名。",
    )
    parser.add_argument(
        "--translation-chunk-size",
        type=int,
        default=40,
        help="每次 API 请求翻译的字幕行数。",
    )
    parser.add_argument(
        "--translation-retries",
        type=int,
        default=2,
        help="每个翻译分块失败后的重试次数。",
    )
    parser.add_argument(
        "--openai-base-url",
        default=None,
        help="OpenAI 兼容中转地址；不填则读取 OPENAI_BASE_URL。",
    )
    parser.add_argument(
        "--openai-dry-run",
        action="store_true",
        help="只发送一个极小测试请求，验证 key、模型名和中转站，不处理视频。",
    )
    parser.add_argument(
        "--glossary",
        default=None,
        help="可选术语表文本文件路径，用于固定人名、术语和译法。",
    )
    parser.add_argument(
        "--save-report",
        default=None,
        help="可选 QA 报告 JSON 输出路径。",
    )
    parser.add_argument(
        "--save-segments",
        default=None,
        help="可选中间字幕片段 JSON 输出路径。",
    )
    parser.add_argument(
        "--load-segments",
        default=None,
        help="读取中间字幕片段 JSON，跳过媒体探测、音频抽取和 ASR。",
    )
    parser.add_argument(
        "--learn-style-project",
        default=None,
        help="从指定项目目录里的 05_translated_segments.json 和置顶 ASS 产物抽取风格样例。",
    )
    parser.add_argument(
        "--enable-ai-display-rewrite",
        action="store_true",
        help="启用高风险中文字幕 AI 风格重写。",
    )
    parser.add_argument(
        "--display-rewrite-max-ai-segments",
        type=int,
        default=12,
        help="最多调用 AI 风格重写的字幕段数。",
    )
    return parser.parse_args()


def default_output_path(input_path: str, src_lang: str | None) -> Path:
    suffix = src_lang or "source"
    return Path(input_path).with_suffix(f".{suffix}.srt")


def save_report(report, output_path: str | Path) -> None:
    payload = {"errors": report.errors, "warnings": report.warnings}
    Path(output_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()

    if args.openai_dry_run:
        # 这个分支只验证 OpenAI 兼容接口，不要求提供视频文件。
        result = dry_run_openai_translation(
            model=args.translation_model,
            base_url=args.openai_base_url,
        )
        print(f"OpenAI dry run ok: {result}")
        return

    if args.learn_style_project:
        project_dir = Path(args.learn_style_project)
        ass_path = find_existing_ass_path(project_dir)
        if not ass_path:
            raise SystemExit(f"未找到 ASS 产物：{project_dir}")
        manifest = write_style_learning_artifacts(
            segments_path=project_artifact_path(project_dir, "05_translated_segments.json"),
            manual_ass_path=ass_path,
            output_dir=project_dir,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return

    if not args.input:
        raise SystemExit("请提供输入视频或音频路径；只有 --openai-dry-run 可以不传 input。")

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else default_output_path(args.input, args.src_lang)
    work_dir = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="autosub_zh_"))

    if args.load_segments:
        # 复用 ASR 中间结果，可以避免每次调试翻译提示词都重新转写长视频。
        print(f"Loading segments from: {args.load_segments}")
        segments = load_segments(args.load_segments)
    else:
        # CLI 只负责流程编排，媒体探测、音频抽取、ASR、翻译和导出分别放在独立模块里。
        media = probe_media(input_path)
        if media.has_text_subtitle:
            print(
                "Text subtitle stream detected, but subtitle extraction is not wired yet. "
                "Falling back to ASR from the audio stream."
            )
        if not media.has_audio:
            raise RuntimeError("No audio stream found. Text subtitle extraction is not implemented yet.")

        # ASR 阶段只负责源语言文本和时间轴；翻译放到后续阶段，便于单独排查问题。
        print(f"Extracting audio to: {work_dir}")
        audio_path = extract_audio(input_path, work_dir=work_dir)
        asr_input_path = audio_path
        if args.asr_audio_mode != "off":
            enhanced_path = work_dir / "01b_audio_asr_enhanced.wav"
            print(f"Enhancing ASR audio ({args.asr_audio_mode}) to: {enhanced_path}")
            asr_input_path = enhance_audio_for_asr(
                audio_path,
                enhanced_path,
                mode=args.asr_audio_mode,
                gain_db=args.asr_audio_gain_db,
            )
        print(f"Running faster-whisper model '{args.model}' on: {asr_input_path}")
        segments = transcribe_audio(
            asr_input_path,
            model_name=args.model,
            language=args.src_lang,
            device=args.device,
            compute_type=args.compute_type,
            beam_size=args.beam_size,
            vad_filter=(args.asr_vad == "on") or (args.asr_vad == "auto" and args.asr_audio_mode == "off"),
        )
        segments = refine_timing(segments)

    if args.save_segments:
        save_segments(segments, args.save_segments)
        print(f"Saved intermediate segments: {args.save_segments}")

    # --translate 关闭时复制原文；开启时在这里进入 OpenAI 兼容翻译接口。
    segments = translate_segments(
        segments,
        src_lang=args.src_lang,
        dst_lang=args.dst_lang,
        glossary=args.glossary,
        enabled=args.translate,
        provider=args.translate_provider,
        model=args.translation_model,
        chunk_size=args.translation_chunk_size,
        max_retries=args.translation_retries,
        openai_base_url=args.openai_base_url,
    )

    report = qa_check(segments, dst_lang=args.dst_lang if args.translate else None)
    if args.save_report:
        save_report(report, args.save_report)
        print(f"Saved QA report: {args.save_report}")

    if report.has_blocking_errors:
        raise RuntimeError("QA failed. Use --save-report to inspect details.")

    write_srt(segments, output_path)
    print(f"Wrote subtitle: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        raise SystemExit(f"错误：{exc}") from exc
