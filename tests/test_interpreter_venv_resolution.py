from __future__ import annotations

from pathlib import Path
import sys

import tts_runtime_preflight as preflight


def test_discovery_preserves_active_venv_path_and_installed_numpy():
    active = Path(sys.executable).absolute()
    report = preflight.discover_interpreters([str(active)])
    record = next((item for item in report["interpreters"]
                   if item["executable"] == str(active)), None)
    assert record is not None
    assert record["status"] == "PASS"
    assert record["modules"]["numpy"] is True
