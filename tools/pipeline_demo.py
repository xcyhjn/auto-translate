from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from autosub_zh.models import BilingualSubtitleStyle
from autosub_zh.pipeline_core import resolve_output_dir, run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行一次完整测试流水线，并把各阶段产物落盘到与视频同名的输出子目录。"
    )
    parser.add_argument("input", help="输入视频路径。")
    parser.add_argument("output_root", help="输出根目录。")
    parser.add_argument("--src-lang", default="en", help="源语言代码。")
    parser.add_argument("--dst-lang", default="zh-Hans", help="目标语言代码。")
    parser.add_argument("--model", default="distil-large-v3", help="faster-whisper 模型名。")
    parser.add_argument("--device", default="cpu", help="ASR 设备。")
    parser.add_argument("--compute-type", default="int8", help="ASR 计算类型。")
    parser.add_argument("--beam-size", type=int, default=5, help="ASR beam size。")
    parser.add_argument("--asr-audio-mode", default="off", choices=["off", "whisper", "strong_whisper"], help="ASR 前增强音频模式。")
    parser.add_argument("--asr-audio-gain-db", type=float, default=6.0, help="增强音频额外增益。")
    parser.add_argument("--asr-vad", default="auto", choices=["auto", "on", "off"], help="ASR VAD 策略。")
    parser.add_argument("--translation-model", default="gpt-5.4", help="翻译使用的 OpenAI 兼容模型名。")
    parser.add_argument("--translation-chunk-size", type=int, default=40, help="每次翻译的字幕行数。")
    parser.add_argument("--translation-retries", type=int, default=2, help="翻译分块失败时的重试次数。")
    parser.add_argument("--openai-base-url", default=None, help="OpenAI 兼容中转地址；不填则读取环境变量。")
    parser.add_argument("--audio-override", default=None, help="为无声视频追加的外部音频文件路径。")
    parser.add_argument("--load-existing-segments", action="store_true", help="读取已有阶段文件，跳过 probe、抽音频、ASR 和翻译。")
    parser.add_argument("--preview-seconds", type=int, default=None, help="只输出前 N 秒的烧录预览视频。")
    parser.add_argument("--skip-burn", action="store_true", help="只生成到双语 ASS 和 QA 产物，不烧录视频。")
    parser.add_argument("--no-span-repair", action="store_true", help="只标记难句 span，不调用 AI 局部修复。")
    parser.add_argument("--span-repair-max-spans", type=int, default=12, help="最多调用 AI 修复的高风险 span 数。")
    parser.add_argument("--enable-ai-display-rewrite", action="store_true", help="启用高风险中文字幕 AI 风格重写。")
    parser.add_argument("--enable-local-translation-feedback", action="store_true", help="Use learned local subtitle feedback guidelines in translation prompts.")
    parser.add_argument("--display-rewrite-max-ai-segments", type=int, default=12, help="最多调用 AI 风格重写的字幕段数。")
    parser.add_argument("--zh-font-size", type=int, default=64, help="中文字幕字号。")
    parser.add_argument("--zh-margin-l", type=int, default=90, help="中文字幕左边距。")
    parser.add_argument("--zh-margin-r", type=int, default=90, help="中文字幕右边距。")
    parser.add_argument("--zh-margin-v", type=int, default=94, help="中文字幕离底部距离。")
    parser.add_argument("--en-font-size", type=int, default=40, help="英文字幕字号。")
    parser.add_argument("--en-margin-l", type=int, default=80, help="英文字幕左边距。")
    parser.add_argument("--en-margin-r", type=int, default=100, help="英文字幕右边距。")
    parser.add_argument("--en-margin-v", type=int, default=44, help="英文字幕离底部距离。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input
    output_root = args.output_root
    style = BilingualSubtitleStyle(
        zh_font_size=args.zh_font_size,
        zh_margin_l=args.zh_margin_l,
        zh_margin_r=args.zh_margin_r,
        zh_margin_v=args.zh_margin_v,
        en_font_size=args.en_font_size,
        en_margin_l=args.en_margin_l,
        en_margin_r=args.en_margin_r,
        en_margin_v=args.en_margin_v,
    )
    manifest = run_pipeline(
        input_path=input_path,
        output_root=output_root,
        src_lang=args.src_lang,
        dst_lang=args.dst_lang,
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
        beam_size=args.beam_size,
        asr_audio_mode=args.asr_audio_mode,
        asr_audio_gain_db=args.asr_audio_gain_db,
        asr_vad_mode=args.asr_vad,
        translation_model=args.translation_model,
        translation_chunk_size=args.translation_chunk_size,
        translation_retries=args.translation_retries,
        openai_base_url=args.openai_base_url,
        audio_override_path=args.audio_override,
        load_existing_segments=args.load_existing_segments,
        preview_seconds=args.preview_seconds,
        skip_burn=args.skip_burn,
        repair_high_risk_spans=not args.no_span_repair,
        span_repair_max_spans=args.span_repair_max_spans,
        enable_ai_display_rewrite=args.enable_ai_display_rewrite,
        enable_local_translation_feedback=args.enable_local_translation_feedback,
        display_rewrite_max_ai_segments=args.display_rewrite_max_ai_segments,
        bilingual_style=style,
    )
    manifest["bilingual_style"] = asdict(style)
    manifest["resolved_output_dir"] = str(resolve_output_dir(Path(input_path), Path(output_root)))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
