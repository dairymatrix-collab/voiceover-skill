import json, subprocess, sys
from pathlib import Path
import pytest
import python_runtime_acquisition as r

def test_version_validation():
    assert r._validate_version("3.12") == (3,12)
    for x in ["3.9", "3.13", "x", "3.12\x00"]:
        with pytest.raises(ValueError): r._validate_version(x)

def test_uv_cache_inventory_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(r.shutil, "which", lambda x: None)
    out = r.inspect_uv(cache_dir=tmp_path / "missing")
    assert out["uv_available"] is False
    assert out["cache_dir_exists"] is False

def test_uv_cache_inventory_counts_files(tmp_path, monkeypatch):
    monkeypatch.setattr(r.shutil, "which", lambda x: "/usr/bin/uv")
    (tmp_path / "a").write_text("x")
    (tmp_path / "b").write_text("x")
    assert r.inspect_uv(cache_dir=tmp_path)["cache_file_count"] == 2

def test_offline_probe_classifies_cache_miss(monkeypatch, tmp_path):
    monkeypatch.setattr(r.shutil, "which", lambda x: "/usr/bin/uv")
    monkeypatch.setattr(r, "inspect_uv", lambda: {"uv_available":True,"uv_executable":"/usr/bin/uv","cache_dir":str(tmp_path),"cache_dir_exists":False,"cache_file_count":0,"cache_truncated":False})
    class C:
        returncode=1
        stderr="network connectivity is disabled, but the requested data wasn't found in the cache"
        stdout=""
    monkeypatch.setattr(r.subprocess, "run", lambda *a, **k: C())
    out = r.offline_acquisition_probe("3.12")
    assert out["status"] == "OFFLINE_CACHE_MISS"
    assert out["runtime_acquired"] is False

def test_offline_probe_never_claims_install(monkeypatch):
    monkeypatch.setattr(r.shutil, "which", lambda x: "/usr/bin/uv")
    monkeypatch.setattr(r, "inspect_uv", lambda: {"uv_available":True,"uv_executable":"/usr/bin/uv","cache_dir":"/tmp/uv","cache_dir_exists":True,"cache_file_count":1,"cache_truncated":False})
    class C: returncode=0; stderr=""; stdout="ok"
    monkeypatch.setattr(r.subprocess, "run", lambda *a, **k: C())
    out = r.offline_acquisition_probe("3.12")
    assert out["status"] == "OFFLINE_RUNTIME_AVAILABLE"
    assert out["installation_performed"] is False
    assert out["runtime_acquired"] is False

def test_collection_status(monkeypatch):
    monkeypatch.setattr(r, "offline_acquisition_probe", lambda version, timeout_seconds: {"status":"OFFLINE_CACHE_MISS" if version=="3.12" else "UV_UNAVAILABLE"})
    out = r.collect_runtime_acquisition_report()
    assert out["status"] == "NO_OFFLINE_RUNTIME_AVAILABLE"
    assert out["installation_performed"] is False
    assert out["runtime_acquired"] is False

def test_schema_accepts_real_report():
    import jsonschema
    schema=json.loads((Path(__file__).parents[1]/"schemas/python-runtime-acquisition-v1.schema.json").read_text())
    report=r.collect_runtime_acquisition_report()
    jsonschema.validate(report,schema)

def test_cli_real_environment():
    p=subprocess.run([sys.executable,"scripts/probe_python_runtime_acquisition.py","--versions","3.12","--pretty"],cwd=Path(__file__).parents[1],capture_output=True,text=True,timeout=40)
    assert p.returncode in (0,3)
    data=json.loads(p.stdout)
    assert data["diagnostic_only"] is True
    assert data["installation_performed"] is False
    assert data["runtime_acquired"] is False
