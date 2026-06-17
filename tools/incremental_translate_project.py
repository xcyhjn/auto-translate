from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from autosub_zh.segment_io import load_segments, save_segments_payload
from autosub_zh.translate import load_glossary, translate_chunk_with_openai
from autosub_zh.ui_server import ensure_openai_runtime_env_loaded, read_config
from autosub_zh.workflow_profiles import project_artifact_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Incrementally translate existing timed segments.")
    parser.add_argument("--project", required=True, help="Project output directory.")
    parser.add_argument("--input-file", required=True, help="Original input video path.")
    parser.add_argument("--src-lang", default="en")
    parser.add_argument("--dst-lang", default="zh-Hans")
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--outer-retries", type=int, default=5)
    parser.add_argument("--context-window", type=int, default=4)
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_openai_runtime_env_loaded()

    project_dir = Path(args.project)
    config = read_config()
    timed_path = project_artifact_path(project_dir, "03_timed_source_segments.json")
    translated_path = project_artifact_path(project_dir, "05_translated_segments.json")
    checkpoint_path = project_artifact_path(project_dir, "05_translated_segments.incremental_checkpoint.json")
    glossary_path = project_artifact_path(project_dir, "03_glossary_resolved_prompt.txt")

    segments = load_segments(timed_path)
    completed_chunks: set[int] = set()
    if checkpoint_path.exists():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            completed_chunks = {int(value) for value in checkpoint.get("completed_chunks", [])}
            if translated_path.exists():
                translated_segments = load_segments(translated_path)
                if [segment.id for segment in translated_segments] == [segment.id for segment in segments]:
                    segments = translated_segments
        except Exception as exc:
            print(f"Ignoring invalid checkpoint: {exc}", flush=True)

    chunk_size = max(1, int(args.chunk_size or config.get("translation_chunk_size") or 8))
    max_retries = max(0, int(args.retries or config.get("translation_retries") or 6))
    outer_retries = max(1, int(args.outer_retries or 1))
    context_window = max(0, int(args.context_window or 0))
    model = args.model or str(config.get("translation_model") or "gpt-5.4")
    base_url = (args.base_url or str(config.get("openai_base_url") or "")).strip() or None
    style_prompt = str(config.get("translation_prompt") or "")
    glossary_text = load_glossary(str(glossary_path)) if glossary_path.exists() else ""

    chunks = [(index, segments[index : index + chunk_size]) for index in range(0, len(segments), chunk_size)]
    print(
        f"start chunks={len(chunks)} chunk_size={chunk_size} retries={max_retries} "
        f"outer_retries={outer_retries} model={model} base_url={base_url}",
        flush=True,
    )

    for chunk_number, (start_index, chunk) in enumerate(chunks, start=1):
        if chunk_number in completed_chunks and all((segment.target_text or "").strip() for segment in chunk):
            print(f"skip chunk {chunk_number}/{len(chunks)} already complete", flush=True)
            continue

        context_before = segments[max(0, start_index - context_window) : start_index]
        context_after = segments[
            start_index + len(chunk) : min(len(segments), start_index + len(chunk) + context_window)
        ]
        started_at = time.time()
        for outer_attempt in range(1, outer_retries + 1):
            try:
                translations = translate_chunk_with_openai(
                    chunk,
                    src_lang=args.src_lang,
                    dst_lang=args.dst_lang,
                    glossary_text=glossary_text,
                    style_prompt_text=style_prompt,
                    model=model,
                    base_url=base_url,
                    max_retries=max_retries,
                    context_before=context_before,
                    context_after=context_after,
                )
                for segment in chunk:
                    segment.target_text = translations.get(segment.id, "").strip()

                completed_chunks.add(chunk_number)
                save_segments_payload(
                    segments,
                    translated_path,
                    input_file=args.input_file,
                    summary={
                        "stage": "translated_segments_incremental",
                        "chunk_size": chunk_size,
                        "completed_chunks": len(completed_chunks),
                        "chunk_total": len(chunks),
                        "last_completed_chunk": chunk_number,
                    },
                )
                checkpoint_path.write_text(
                    json.dumps(
                        {
                            "completed_chunks": sorted(completed_chunks),
                            "chunk_total": len(chunks),
                            "updated_at": time.time(),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print(
                    f"complete chunk {chunk_number}/{len(chunks)} elapsed={time.time() - started_at:.1f}s",
                    flush=True,
                )
                break
            except Exception as exc:
                print(
                    f"chunk {chunk_number}/{len(chunks)} outer_attempt {outer_attempt}/{outer_retries} failed: {exc}",
                    flush=True,
                )
                if outer_attempt >= outer_retries:
                    raise
                time.sleep(min(60, 5 * outer_attempt))

    print("translation incremental complete", flush=True)


if __name__ == "__main__":
    main()
