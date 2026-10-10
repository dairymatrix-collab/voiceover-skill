"""Regression tests for deterministic packaging and manifest verification."""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_package.py"


def test_packager_is_reproducible_and_excludes_cache_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("packaging fixture\n", encoding="utf-8")
    (source / "module.py").write_text("VALUE = 7\n", encoding="utf-8")
    cache = source / "__pycache__"
    cache.mkdir()
    (cache / "module.cpython-313.pyc").write_bytes(b"not a real bytecode file")
    (source / "scratch.tmp").write_text("exclude me", encoding="utf-8")
    output = tmp_path / "release.zip"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(source), "--output", str(output), "--check-reproducible"],
        check=False, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Reproducibility check: PASS" in result.stdout
    assert output.is_file()
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert "README.md" in names and "module.py" in names and "SHA256SUMS" in names
        assert not any("__pycache__" in name or name.endswith(".tmp") for name in names)
        assert archive.testzip() is None
        extracted_manifest = archive.read("SHA256SUMS").decode("utf-8")
        assert "module.py" in extracted_manifest
    assert hashlib.sha256(output.read_bytes()).hexdigest() in result.stdout


def test_packager_rejects_manifest_path_traversal(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "safe.txt").write_text("safe\n", encoding="utf-8")
    malicious_manifest = "0" * 64 + "  ../outside.txt\n"
    archive_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("safe.txt", "safe\n")
        archive.writestr("SHA256SUMS", malicious_manifest)

    spec = importlib.util.spec_from_file_location("build_package", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.verify_archive(archive_path)
    except RuntimeError as exc:
        assert "unsafe or duplicate path" in str(exc)
    else:
        raise AssertionError("malicious manifest path traversal was not rejected")


def _load_packager():
    spec = importlib.util.spec_from_file_location("build_package_failure_tests", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_failed_archive_write_preserves_previous_release_and_cleans_staging(tmp_path: Path, monkeypatch) -> None:
    module = _load_packager()
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("safe content\n", encoding="utf-8")
    module.write_manifest(source)
    output = tmp_path / "release.zip"
    output.write_bytes(b"previous known-good release")
    original_writestr = module.zipfile.ZipFile.writestr

    def fail_writestr(self, *args, **kwargs):
        if str(self.filename).endswith(".building"):
            raise OSError("simulated disk write failure")
        return original_writestr(self, *args, **kwargs)

    monkeypatch.setattr(module.zipfile.ZipFile, "writestr", fail_writestr)
    try:
        module.build_archive(source, output)
    except OSError as exc:
        assert "simulated disk write failure" in str(exc)
    else:
        raise AssertionError("simulated archive write failure did not propagate")

    assert output.read_bytes() == b"previous known-good release"
    assert not list(tmp_path.glob(".release.zip.*.building"))


def test_invalid_output_parent_fails_before_source_manifest_mutation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("unchanged\n", encoding="utf-8")
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("file", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(source), "--output", str(blocked_parent / "release.zip")],
        check=False, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert "output parent is not a directory" in result.stderr
    assert not (source / "SHA256SUMS").exists()
    assert (source / "README.md").read_text(encoding="utf-8") == "unchanged\n"


def test_malformed_archive_is_rejected_without_extracting(tmp_path: Path) -> None:
    module = _load_packager()
    malformed = tmp_path / "malformed.zip"
    malformed.write_bytes(b"this is not a zip archive")
    try:
        module.verify_archive(malformed)
    except zipfile.BadZipFile:
        pass
    else:
        raise AssertionError("malformed archive was not rejected")
    assert not list(tmp_path.glob("voiceover-package-verify-*"))


def test_package_build_changes_only_manifest_inside_source_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("baseline\n", encoding="utf-8")
    (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    before = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    output = tmp_path / "release.zip"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(source), "--output", str(output)],
        check=False, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    after = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert set(after) == set(before) | {"SHA256SUMS"}
    assert all(after[name] == content for name, content in before.items())


def test_manifest_rejects_non_hex_digest_duplicate_and_case_collision(tmp_path: Path) -> None:
    module = _load_packager()
    root = tmp_path / "root"
    root.mkdir()
    (root / "Readme.txt").write_text("x", encoding="utf-8")
    (root / "README.txt").write_text("x", encoding="utf-8")
    (root / "SHA256SUMS").write_text(
        "g" * 64 + "  Readme.txt\n" + "0" * 64 + "  Readme.txt\n" + "0" * 64 + "  README.txt\n",
        encoding="utf-8",
    )
    errors = module.verify_manifest(root)
    assert any("malformed SHA-256 digest" in error for error in errors)
    assert any("unsafe or duplicate path" in error for error in errors)


def test_manifest_rejects_symlink_parent_when_supported(tmp_path: Path) -> None:
    module = _load_packager()
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("do not read", encoding="utf-8")
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    (root / "SHA256SUMS").write_text(
        hashlib.sha256(secret.read_bytes()).hexdigest() + "  linked/secret.txt\n", encoding="utf-8"
    )
    errors = module.verify_manifest(root)
    assert any("unsafe" in error for error in errors)


def test_archive_rejects_symlink_and_special_file_metadata_before_extract(tmp_path: Path) -> None:
    module = _load_packager()
    for label, mode in (("symlink", 0o120777), ("fifo", 0o010644), ("socket", 0o140644)):
        archive_path = tmp_path / f"{label}.zip"
        info = zipfile.ZipInfo("payload")
        info.create_system = 3
        info.external_attr = mode << 16
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(info, b"payload")
            archive.writestr("SHA256SUMS", "0" * 64 + "  payload\n")
        try:
            module.verify_archive(archive_path)
        except RuntimeError as exc:
            assert "not a regular file" in str(exc)
        else:
            raise AssertionError(f"{label} metadata was not rejected")
        assert not list(tmp_path.glob("voiceover-package-verify-*"))


def test_archive_rejects_duplicate_and_case_colliding_paths(tmp_path: Path) -> None:
    module = _load_packager()
    for names in (("payload", "payload"), ("Readme.txt", "README.txt")):
        archive_path = tmp_path / f"duplicate-{len(names)}-{names[0]}.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(names[0], b"a")
            archive.writestr(names[1], b"b")
            archive.writestr("SHA256SUMS", "0" * 64 + f"  {names[0]}\n")
        try:
            module.verify_archive(archive_path)
        except RuntimeError as exc:
            assert "duplicate or case-colliding" in str(exc)
        else:
            raise AssertionError("duplicate/case-colliding ZIP paths were not rejected")


def test_archive_rejects_uncompressed_size_limit_before_extract(tmp_path: Path, monkeypatch) -> None:
    module = _load_packager()
    archive_path = tmp_path / "large-metadata.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        info = zipfile.ZipInfo("payload")
        info.file_size = module.MAX_UNCOMPRESSED_BYTES + 1
        # Create a normal archive then mutate the in-memory central-directory metadata
        # through a tiny test double to avoid allocating a large fixture.
        archive.writestr("payload", b"x")
        archive.writestr("SHA256SUMS", "0" * 64 + "  payload\n")
    original_open = module.zipfile.ZipFile

    class OversizedArchive:
        def __init__(self, *args, **kwargs):
            self.inner = original_open(*args, **kwargs)
        def __enter__(self): return self
        def __exit__(self, *args): return self.inner.__exit__(*args)
        def infolist(self):
            infos = self.inner.infolist()
            infos[0].file_size = module.MAX_UNCOMPRESSED_BYTES + 1
            return infos
        def __getattr__(self, name): return getattr(self.inner, name)

    monkeypatch.setattr(module.zipfile, "ZipFile", OversizedArchive)
    try:
        module.verify_archive(archive_path)
    except RuntimeError as exc:
        assert "uncompressed size exceeds safety limit" in str(exc)
    else:
        raise AssertionError("oversized archive metadata was not rejected")
