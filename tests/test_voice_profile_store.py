from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import struct
import sys
import wave

import pytest
from jsonschema import Draft202012Validator, FormatChecker

import voice_profile_store as store
from voice_profile_store import (
    ProfileStoreError,
    create_profile,
    delete_profile,
    list_profiles,
    load_profile,
    reference_audio_path,
    update_controls,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "voice-profile-v1.schema.json").read_text(encoding="utf-8"))


def make_wav(path: Path, *, seconds: float = 1.0, rate: int = 16000, channels: int = 1) -> bytes:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        silence = struct.pack("<h", 0) * frames * channels
        wav.writeframes(silence)
    return path.read_bytes()


def test_voice_design_profile_is_atomic_loadable_and_schema_valid(tmp_path):
    profile = create_profile(
        tmp_path,
        profile_id="clear-narrator",
        name="Clear narrator",
        engine_id="qwen3_tts",
        mode="voice_design",
        language="en",
        voice_description="Warm, clear, measured narrator with a low-mid register.",
        controls={"temperature": 0.8, "top_k": 40, "max_new_tokens": 256},
    )
    Draft202012Validator.check_schema(SCHEMA)
    Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(profile)
    assert load_profile(tmp_path, "clear-narrator") == profile
    target = tmp_path / "profiles" / "clear-narrator.json"
    assert json.loads(target.read_text(encoding="utf-8")) == profile
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


def test_preset_profile_records_engine_specific_speed(tmp_path):
    profile = create_profile(
        tmp_path, profile_id="kokoro-us", name="US narrator", engine_id="kokoro",
        mode="preset", language="en-us", voice_id="af_heart", controls={"speed": 1.1},
    )
    assert profile["controls"] == {"speed": 1.1}
    assert profile["voice_id"] == "af_heart"


def test_reference_clone_copies_only_valid_wav_into_contained_asset_path(tmp_path):
    source = tmp_path / "input.wav"
    original = make_wav(source, seconds=0.25)
    profile = create_profile(
        tmp_path / "store", profile_id="ref-voice", name="Reference voice", engine_id="chatterbox",
        mode="reference_clone", language="en", reference_audio=source,
        controls={"exaggeration": 0.6, "cfg_weight": 0.3},
    )
    asset = tmp_path / "store" / profile["reference_asset"]
    assert profile["reference_asset"] == "assets/ref-voice/reference.wav"
    assert asset.read_bytes() == original
    assert source.read_bytes() == original
    assert load_profile(tmp_path / "store", "ref-voice") == profile


def test_reference_path_helper_returns_only_validated_store_asset(tmp_path):
    source = tmp_path / "source.wav"
    make_wav(source, seconds=0.2)
    store_root = tmp_path / "store"
    create_profile(store_root, profile_id="clone", name="Clone", engine_id="chatterbox",
                   mode="reference_clone", language="en", reference_audio=source)
    assert reference_audio_path(store_root, "clone") == store_root / "assets" / "clone" / "reference.wav"
    create_profile(store_root, profile_id="preset", name="Preset", engine_id="kokoro",
                   mode="preset", language="en", voice_id="af_heart")
    with pytest.raises(ProfileStoreError, match="PROFILE_REFERENCE_NOT_CONFIGURED"):
        reference_audio_path(store_root, "preset")


def test_create_is_atomic_on_profile_write_failure_and_rolls_back_reference_asset(tmp_path, monkeypatch):
    source = tmp_path / "reference.wav"
    make_wav(source)

    def fail_write(_target, _payload):
        raise OSError("simulated write failure")

    monkeypatch.setattr(store, "_atomic_write", fail_write)
    with pytest.raises(OSError, match="simulated write failure"):
        create_profile(
            tmp_path / "store", profile_id="ref-fail", name="Failure case", engine_id="chatterbox",
            mode="reference_clone", language="en", reference_audio=source,
        )
    assert not (tmp_path / "store" / "profiles" / "ref-fail.json").exists()
    assert not (tmp_path / "store" / "assets" / "ref-fail" / "reference.wav").exists()


def test_bad_language_and_unsupported_control_fail_closed(tmp_path):
    with pytest.raises(ProfileStoreError, match="PROFILE_LANGUAGE_UNSUPPORTED"):
        create_profile(
            tmp_path, profile_id="qwen-urdu", name="Urdu", engine_id="qwen3_tts",
            mode="voice_design", language="ur", voice_description="Warm voice",
        )
    with pytest.raises(ProfileStoreError, match="VOICE_CONTROL_UNSUPPORTED"):
        create_profile(
            tmp_path, profile_id="qwen-pitch", name="Pitch", engine_id="qwen3_tts",
            mode="voice_design", language="en", voice_description="Warm voice", controls={"pitch": 2},
        )
    assert not (tmp_path / "profiles" / "qwen-urdu.json").exists()


@pytest.mark.parametrize("kwargs,code", [
    ({"profile_id": "../escape"}, "PROFILE_ID_INVALID"),
    ({"name": "   "}, "PROFILE_NAME_INVALID"),
    ({"voice_id": "../outside"}, "PROFILE_PRESET_INVALID"),
])
def test_invalid_identifiers_names_and_voice_ids(kwargs, code, tmp_path):
    args = dict(profile_id="valid", name="Valid", engine_id="kokoro", mode="preset", language="en", voice_id="af_heart")
    args.update(kwargs)
    with pytest.raises(ProfileStoreError, match=code):
        create_profile(tmp_path, **args)
    assert not (tmp_path.parent / "escape.json").exists()


def test_duplicate_id_and_list_are_deterministic(tmp_path):
    create_profile(tmp_path, profile_id="zeta", name="Zeta", engine_id="kokoro", mode="preset", language="en", voice_id="af_heart")
    create_profile(tmp_path, profile_id="alpha", name="Alpha", engine_id="kokoro", mode="preset", language="en", voice_id="af_heart")
    with pytest.raises(ProfileStoreError, match="PROFILE_ALREADY_EXISTS"):
        create_profile(tmp_path, profile_id="alpha", name="Duplicate", engine_id="kokoro", mode="preset", language="en", voice_id="af_heart")
    assert [item["profile_id"] for item in list_profiles(tmp_path)] == ["alpha", "zeta"]


def test_concurrent_creates_for_same_id_allow_exactly_one_winner(tmp_path):
    def create(name):
        try:
            create_profile(tmp_path, profile_id="same", name=name, engine_id="kokoro", mode="preset", language="en", voice_id="af_heart")
            return "created"
        except ProfileStoreError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ("First", "Second")))
    assert results.count("created") == 1
    assert results.count("PROFILE_ALREADY_EXISTS") == 1
    assert load_profile(tmp_path, "same")["name"] in {"First", "Second"}


def test_update_controls_is_atomic_and_rejects_engine_incompatible_keys(tmp_path, monkeypatch):
    create_profile(tmp_path, profile_id="stable", name="Stable", engine_id="kokoro", mode="preset", language="en", voice_id="af_heart", controls={"speed": 1.0})
    updated = update_controls(tmp_path, "stable", {"speed": 1.25})
    assert updated["controls"] == {"speed": 1.25}
    with pytest.raises(ProfileStoreError, match="VOICE_CONTROL_UNSUPPORTED"):
        update_controls(tmp_path, "stable", {"temperature": 0.8})
    assert load_profile(tmp_path, "stable")["controls"] == {"speed": 1.25}

    def fail_write(_target, _payload):
        raise OSError("blocked")

    before = load_profile(tmp_path, "stable")
    monkeypatch.setattr(store, "_atomic_write", fail_write)
    with pytest.raises(OSError, match="blocked"):
        update_controls(tmp_path, "stable", {"speed": 1.5})
    monkeypatch.undo()
    assert load_profile(tmp_path, "stable") == before


def test_reference_source_must_be_a_regular_bounded_wav(tmp_path):
    text = tmp_path / "not.wav"
    text.write_text("not a wav", encoding="utf-8")
    with pytest.raises(ProfileStoreError, match="PROFILE_REFERENCE_AUDIO_INVALID"):
        create_profile(tmp_path / "store", profile_id="bad-wave", name="Bad", engine_id="chatterbox", mode="reference_clone", language="en", reference_audio=text)

    long_wav = tmp_path / "long.wav"
    make_wav(long_wav, seconds=30.01)
    with pytest.raises(ProfileStoreError, match="PROFILE_REFERENCE_AUDIO_INVALID"):
        create_profile(tmp_path / "store", profile_id="long-wave", name="Long", engine_id="chatterbox", mode="reference_clone", language="en", reference_audio=long_wav)


def test_reference_symlink_and_asset_directory_symlink_are_rejected(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink support unavailable")
    source = tmp_path / "real.wav"
    make_wav(source)
    source_link = tmp_path / "linked.wav"
    try:
        source_link.symlink_to(source)
    except OSError:
        pytest.skip("symlink creation denied")
    with pytest.raises(ProfileStoreError, match="PROFILE_REFERENCE_FILE_UNSAFE"):
        create_profile(tmp_path / "store", profile_id="source-link", name="Link", engine_id="chatterbox", mode="reference_clone", language="en", reference_audio=source_link)

    store_root = tmp_path / "store2"
    store_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (store_root / "assets").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation denied")
    with pytest.raises(ProfileStoreError, match="PROFILE_REFERENCE_SYMLINK"):
        create_profile(store_root, profile_id="asset-link", name="Link", engine_id="chatterbox", mode="reference_clone", language="en", reference_audio=source)
    assert not list(outside.iterdir())


def test_store_root_symlink_and_home_directory_are_rejected(tmp_path):
    if hasattr(os, "symlink"):
        target = tmp_path / "real-store"
        target.mkdir()
        alias = tmp_path / "alias"
        try:
            alias.symlink_to(target, target_is_directory=True)
        except OSError:
            alias = None
        if alias is not None:
            with pytest.raises(ProfileStoreError, match="PROFILE_STORE_SYMLINK"):
                list_profiles(alias)
    with pytest.raises(ProfileStoreError, match="PROFILE_STORE_PATH_UNSAFE"):
        list_profiles(Path.home())


def test_profile_tampering_duplicate_json_and_asset_traversal_fail_closed(tmp_path):
    create_profile(tmp_path, profile_id="tamper", name="Tamper", engine_id="kokoro", mode="preset", language="en", voice_id="af_heart")
    path = tmp_path / "profiles" / "tamper.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(ProfileStoreError, match="PROFILE_JSON_DUPLICATE_KEY"):
        load_profile(tmp_path, "tamper")
    original["mode"] = "reference_clone"
    original["engine_id"] = "chatterbox"
    original["voice_id"] = None
    original["reference_asset"] = "assets/../outside.wav"
    path.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ProfileStoreError, match="PROFILE_REFERENCE_CLONE_INVALID|PROFILE_REFERENCE_PATH_INVALID"):
        load_profile(tmp_path, "tamper")


def test_profile_symlink_rejected_and_delete_removes_owned_files(tmp_path):
    create_profile(tmp_path, profile_id="to-delete", name="Delete", engine_id="kokoro", mode="preset", language="en", voice_id="af_heart")
    if hasattr(os, "symlink"):
        outside = tmp_path / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        target = tmp_path / "profiles" / "link.json"
        try:
            target.symlink_to(outside)
        except OSError:
            pass
        else:
            with pytest.raises(ProfileStoreError, match="PROFILE_PATH_SYMLINK"):
                load_profile(tmp_path, "link")
    delete_profile(tmp_path, "to-delete")
    assert not (tmp_path / "profiles" / "to-delete.json").exists()
    with pytest.raises(ProfileStoreError, match="PROFILE_NOT_FOUND_OR_UNSAFE"):
        load_profile(tmp_path, "to-delete")
