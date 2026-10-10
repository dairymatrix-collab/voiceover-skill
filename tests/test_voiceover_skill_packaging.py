from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import zipfile

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "package_voiceover_skill", ROOT / "scripts" / "package_voiceover_skill.py"
)
assert SPEC is not None and SPEC.loader is not None
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)


def _json_from_zip(archive: zipfile.ZipFile, path: str) -> dict:
    return json.loads(archive.read(path).decode("utf-8"))


def test_sample_voice_design_request_matches_closed_v2_schema():
    schema = json.loads((ROOT / "schemas" / "synthesis-request-v2.schema.json").read_text(encoding="utf-8"))
    request = json.loads((ROOT / "skills" / "voiceover-skill" / "templates" / "qwen-voice-design-request-v2.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(request, schema)


def test_skill_source_contains_no_template_placeholders():
    for relative in ("SKILL.md", "references/api_reference.md"):
        content = (ROOT / "skills" / "voiceover-skill" / relative).read_text(encoding="utf-8")
        assert "[TODO:" not in content
        assert "Structuring This Skill" not in content
    assert not (ROOT / "skills" / "voiceover-skill" / "scripts" / "example.py").exists()


def test_four_packages_are_reproducible_and_minimax_manifests_are_separated(tmp_path: Path):
    output = tmp_path / "Voiceover packages"
    rows = packager.build_packages(output, check_reproducible=True)
    assert {row["kind"] for row in rows} == {
        "standalone", "claude", "minimax_code", "minimax_submission"
    }
    assert all(Path(row["path"]).is_file() for row in rows)
    assert all(len(row["sha256"]) == 64 for row in rows)
    assert all(hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() == row["sha256"] for row in rows)
    by_kind = {row["kind"]: Path(row["path"]) for row in rows}

    for package in by_kind.values():
        with zipfile.ZipFile(package) as archive:
            assert archive.testzip() is None
            for info in archive.infolist():
                assert info.filename.isascii()
                mode = (info.external_attr >> 16) & 0xFFFF
                assert stat.S_IFMT(mode) in {0, stat.S_IFREG}
                assert mode & 0o111 == 0
                assert not info.filename.casefold().endswith(
                    (".safetensors", ".pt", ".pth", ".bin", ".so", ".dll", ".dylib", ".exe")
                )

    with zipfile.ZipFile(by_kind["standalone"]) as archive:
        names = set(archive.namelist())
        assert "voiceover-skill/SKILL.md" in names
        assert "voiceover-skill/backend/scripts/run_voiceover.py" in names
        assert "voiceover-skill/backend/schemas/synthesis-request-v2.schema.json" in names

    with zipfile.ZipFile(by_kind["claude"]) as archive:
        manifest = _json_from_zip(archive, ".claude-plugin/plugin.json")
        assert manifest["skills"] == ["./skills/voiceover-skill"]
        assert "skills/voiceover-skill/SKILL.md" in archive.namelist()

    with zipfile.ZipFile(by_kind["minimax_code"]) as archive:
        names = set(archive.namelist())
        assert {"plugin.json", ".claude-plugin/plugin.json", "skills/SKILL.md",
                "skills/voiceover-skill/SKILL.md", "assets/voiceover.png"}.issubset(names)
        assert ".minimax-plugin/plugin.json" not in names
        portable = _json_from_zip(archive, "plugin.json")
        modern = _json_from_zip(archive, ".claude-plugin/plugin.json")
        assert set(portable) == {"$schema", "name"}
        assert portable["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
        assert modern["skills"] == "./skills/SKILL.md"
        assert archive.read("skills/SKILL.md") == archive.read("skills/voiceover-skill/SKILL.md")

    with zipfile.ZipFile(by_kind["minimax_submission"]) as archive:
        names = set(archive.namelist())
        assert {".minimax-plugin/plugin.json", "skills/voiceover-skill/SKILL.md",
                "assets/voiceover.png"}.issubset(names)
        assert "plugin.json" not in names
        assert ".claude-plugin/plugin.json" not in names
        submission = _json_from_zip(archive, ".minimax-plugin/plugin.json")
        assert submission["skills"] == ["skills/voiceover-skill/SKILL.md"]
        assert submission["apps"] == [] and submission["mcpServers"] == []
        assert len(submission["exampleQueries"]) <= 3
