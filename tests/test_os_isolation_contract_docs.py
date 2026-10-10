from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "OS_ISOLATION_CAPABILITY_CONTRACT.md"
README = ROOT / "README.md"
REPORT = ROOT / "FINAL_TEST_EVIDENCE_REPORT.md"


def test_isolation_contract_explicitly_says_design_only():
    text = CONTRACT.read_text(encoding="utf-8")
    assert "design/documentation only" in text
    assert "NOT IMPLEMENTED / NOT RUN" in text
    assert "NOT VERIFIED" in text
    assert "not a security boundary" in text


def test_platform_matrix_covers_linux_windows_and_macos():
    text = CONTRACT.read_text(encoding="utf-8")
    for platform in ("Linux cgroup v2", "Windows Job Object", "macOS sandbox"):
        assert platform in text


def test_contract_defines_fail_closed_and_cleanup_evidence():
    text = CONTRACT.read_text(encoding="utf-8")
    assert "Fail-closed behavior" in text
    assert "CLEANUP_INCOMPLETE" in text
    assert "containment unit is confirmed empty" in text
    assert "network is denied by default" in text.lower()


def test_user_facing_docs_keep_sandbox_claim_gated():
    readme = README.read_text(encoding="utf-8")
    report = REPORT.read_text(encoding="utf-8")
    assert "OS_ISOLATION_CAPABILITY_CONTRACT.md" in readme
    assert "D0-49" in readme
    assert "D0-49" in report
    assert "OPEN / HOLD" in report


def test_d0_50_provider_interface_is_documented_without_claiming_implementation():
    contract = CONTRACT.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    assert "D0-50 platform-neutral provider interface" in contract
    assert "does **not** implement a Linux, Windows, or macOS isolation backend" in contract
    assert "no platform provider is implemented" in readme.lower()
    assert "fail-closed capability negotiation" in readme
