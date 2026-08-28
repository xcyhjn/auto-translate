from __future__ import annotations

import json
from pathlib import Path

import pytest

from autosub_zh import cli
from autosub_zh import cli_commands
from autosub_zh.models import Segment
from autosub_zh.qa import QaReport


def test_modern_command_parser_exposes_expected_commands() -> None:
    parser = cli_commands.build_commands_parser()
    commands = set(parser._subparsers._group_actions[0].choices)
    assert commands == {"pipeline", "translate", "qa", "burn", "init"}


def test_unknown_command_and_help_have_standard_exit_codes() -> None:
    parser = cli_commands.build_commands_parser()
    with pytest.raises(SystemExit) as unknown:
        parser.parse_args(["unknown"])
    assert unknown.value.code == 2
    with pytest.raises(SystemExit) as help_exit:
        parser.parse_args(["--help"])
    assert help_exit.value.code == 0


def test_top_level_help_advertises_composable_commands(capsys) -> None:
    with pytest.raises(SystemExit) as help_exit:
        cli.parse_args(["--help"])
    assert help_exit.value.code == 0
    assert "组合式子命令" in capsys.readouterr().out


def test_legacy_invocation_remains_legacy() -> None:
    args = cli.parse_args(["input.mp4", "--src-lang", "en"])
    assert not hasattr(args, "command")
    assert args.input == "input.mp4"
    assert args.src_lang == "en"


def test_dry_run_does_not_read_input_or_write_output(tmp_path: Path, capsys) -> None:
    output = tmp_path / "should-not-exist.json"
    code = cli.main(["init", "--output", str(output), "--dry-run"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["command"] == "init"
    assert not output.exists()


def test_pipeline_dispatch_forwards_to_existing_runner(tmp_path: Path, monkeypatch) -> None:
    from autosub_zh import pipeline_runner

    config_path = tmp_path / "config.json"
    config_path.write_text('{"src_lang":"en"}', encoding="utf-8")
    captured = {}

    def fake_run_pipeline_from_config(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(pipeline_runner, "run_pipeline_from_config", fake_run_pipeline_from_config)
    code = cli.main(["pipeline", "input.mp4", "--config", str(config_path)])
    assert code == 0
    assert captured["video_path"] == Path("input.mp4")
    assert captured["config"] == {"src_lang": "en"}


def test_qa_json_uses_glossary_consistency(tmp_path: Path, monkeypatch) -> None:
    from autosub_zh import qa, segment_io

    segments_path = tmp_path / "segments.json"
    segments_path.write_text("{}", encoding="utf-8")
    segments = [Segment(id=1, start=0.0, end=1.0, source_text="source", target_text="中文")]
    monkeypatch.setattr(segment_io, "load_segments", lambda _path: segments)
    monkeypatch.setattr(qa, "qa_check", lambda *_args, **_kwargs: QaReport())
    monkeypatch.setattr(
        qa,
        "qa_glossary_consistency",
        lambda *_args, **_kwargs: QaReport(warnings=["review glossary"]),
    )
    code = cli.main(["qa", str(segments_path), "--glossary", "glossary.json"])
    assert code == 0


def test_qa_ass_rejects_glossary_option(tmp_path: Path, capsys) -> None:
    ass_path = tmp_path / "subtitle.ass"
    ass_path.write_text("[Events]", encoding="utf-8")
    code = cli.main(["qa", str(ass_path), "--glossary", "glossary.json"])
    assert code == 1
    assert "只支持字幕片段 JSON" in capsys.readouterr().err
