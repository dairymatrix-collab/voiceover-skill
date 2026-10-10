from __future__ import annotations

import json
from pathlib import Path
import pytest

from scripts.voice_profiles import main


def output(capsys):
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_cli_create_list_and_show_keep_list_context_small(tmp_path, capsys):
    store = tmp_path / "profiles"
    rc = main([
        "--store", str(store), "create", "--profile-id", "warm-en",
        "--name", "Warm English narrator", "--engine", "qwen3_tts",
        "--mode", "voice_design", "--language", "en",
        "--voice-description", "A warm, calm narrator with a measured pace.",
        "--control", "temperature=0.8",
    ])
    assert rc == 0
    created = output(capsys)
    assert created["ok"] is True
    assert created["profile"]["voice_description_saved"] is True
    assert "voice_description" not in created["profile"]
    assert str(store) not in json.dumps(created)

    assert main(["--store", str(store), "list"]) == 0
    listed = output(capsys)
    assert len(listed["profiles"]) == 1
    assert "voice_description" not in listed["profiles"][0]
    assert "reference_asset" not in listed["profiles"][0]

    assert main(["--store", str(store), "show", "warm-en"]) == 0
    shown = output(capsys)
    assert shown["profile"]["voice_description"] == "A warm, calm narrator with a measured pace."
    assert "reference.wav" not in json.dumps(shown)


def test_cli_voice_design_prompt_file_is_bounded_and_not_echoed(tmp_path, capsys):
    store = tmp_path / "profiles"
    prompt = tmp_path / "voice-description.txt"
    prompt.write_text("A warm, steady Urdu-English narrator with clear diction.", encoding="utf-8")
    args = [
        "--store", str(store), "create", "--profile-id", "design-prompt-file",
        "--name", "Prompt-file voice", "--engine", "qwen3_tts", "--mode", "voice_design",
        "--language", "en", "--voice-description-file", str(prompt),
    ]
    assert main(args) == 0
    created_text = capsys.readouterr().out
    created = json.loads(created_text)
    assert created["profile"]["voice_description_saved"] is True
    assert "warm, steady" not in created_text

    assert main(["--store", str(store), "show", "design-prompt-file"]) == 0
    assert json.loads(capsys.readouterr().out)["profile"]["voice_description"] == prompt.read_text()

    too_large = tmp_path / "too-large.txt"
    too_large.write_text("x" * 1601, encoding="utf-8")
    bad_args = ["--store", str(store), "create", "--profile-id", "oversized",
                "--name", "Oversized prompt", "--engine", "qwen3_tts",
                "--mode", "voice_design", "--language", "en",
                "--voice-description-file", str(too_large)]
    assert main(bad_args) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "VOICE_DESCRIPTION_FILE_TOO_LARGE"
    assert not (store / "profiles" / "oversized.json").exists()


def test_cli_updates_controls_and_rejects_unsupported_control_without_mutation(tmp_path, capsys):
    store = tmp_path / "profiles"
    assert main([
        "--store", str(store), "create", "--profile-id", "kokoro-en",
        "--name", "Kokoro narrator", "--engine", "kokoro", "--mode", "preset",
        "--language", "en", "--voice-id", "af_heart", "--control", "speed=1.0",
    ]) == 0
    output(capsys)
    assert main(["--store", str(store), "update-controls", "kokoro-en", "--control", "speed=1.25"]) == 0
    updated = output(capsys)
    assert updated["profile"]["controls"] == {"speed": 1.25}

    assert main(["--store", str(store), "update-controls", "kokoro-en", "--control", "pitch=1.0"]) == 2
    assert output(capsys)["error"] == "VOICE_CONTROL_UNSUPPORTED"
    assert main(["--store", str(store), "show", "kokoro-en"]) == 0
    assert output(capsys)["profile"]["controls"] == {"speed": 1.25}


def test_cli_requires_json_scalar_control_and_rejects_duplicate_key(tmp_path, capsys):
    base = [
        "--store", str(tmp_path), "create", "--profile-id", "bad-control",
        "--name", "Bad", "--engine", "kokoro", "--mode", "preset",
        "--language", "en", "--voice-id", "af_heart",
    ]
    assert main(base + ["--control", "speed=1.0", "--control", "speed=1.5"]) == 2
    assert output(capsys)["error"] == "CONTROL_DUPLICATE_OR_EMPTY"
    assert not (tmp_path / "profiles" / "bad-control.json").exists()

    assert main(base + ["--control", "speed=not-json"]) == 2
    assert output(capsys)["error"] == "CONTROL_VALUE_MUST_BE_JSON_SCALAR"


def test_cli_blocks_unverified_profile_modes(tmp_path, capsys):
    store = tmp_path / "voice-store"
    with pytest.raises(SystemExit) as error:
        main(["--store", str(store), "create", "--profile-id", "reference-one",
              "--name", "Reference clone", "--engine", "chatterbox", "--mode", "reference_clone",
              "--language", "en", "--reference-audio", "unused.wav"])
    assert error.value.code == 2
    capsys.readouterr()
    assert not (store / "profiles" / "reference-one.json").exists()

    assert main(["--store", str(store), "create", "--profile-id", "qwen-preset",
                 "--name", "Unverified preset", "--engine", "qwen3_tts", "--mode", "preset",
                 "--language", "en", "--voice-id", "Ryan"]) == 2
    assert output(capsys)["error"] == "PROFILE_MODE_NOT_VERIFIED"
    assert not (store / "profiles" / "qwen-preset.json").exists()
