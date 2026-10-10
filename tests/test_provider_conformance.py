import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from isolation_provider import (
    CapabilityReport, IsolationPolicy, JobHandle, JobInspection, PRODUCTION_REQUIRED_CAPABILITIES,
    VerificationStatus, WaitResult, ProviderContractError,
)
from provider_conformance import run_provider_conformance


class FakeProvider:
    def __init__(self, *, allowed=True, terminal=True, exit_code=0, empty=True, fail_cleanup=False):
        self.allowed = allowed
        self.terminal = terminal
        self.exit_code = exit_code
        self.empty = empty
        self.fail_cleanup = fail_cleanup
        self.calls = []

    def capability_report(self):
        self.calls.append("capability_report")
        return CapabilityReport(
            provider_id="fake-test-provider", provider_version="1.0-test", platform="test-os",
            status=VerificationStatus.VERIFIED if self.allowed else VerificationStatus.UNVERIFIED,
            capabilities={key: True for key in PRODUCTION_REQUIRED_CAPABILITIES},
            limitations=("fake provider; no OS isolation performed",),
            verification_evidence=("fixture://fake-provider",),
        )

    def launch(self, argv, *, cwd, env, limits, policy):
        self.calls.append("launch")
        return JobHandle("fake-test-provider", "job-1")

    def terminate(self, job, *, reason):
        self.calls.append("terminate")
        self.terminal = True
        self.exit_code = -9
        self.empty = True

    def wait(self, job, *, deadline_monotonic):
        self.calls.append("wait")
        return WaitResult(self.terminal, self.exit_code if self.terminal else None, self.empty if self.terminal else False,
                          "EXITED" if self.terminal else "DEADLINE_EXPIRED")

    def inspect(self, job):
        self.calls.append("inspect")
        return JobInspection(self.empty, {key: True for key in PRODUCTION_REQUIRED_CAPABILITIES})

    def cleanup(self, job):
        self.calls.append("cleanup")
        if self.fail_cleanup:
            raise RuntimeError("simulated cleanup failure")


def run(provider):
    return run_provider_conformance(
        provider, target_platform="test-os", probe_argv=[sys.executable, "-c", "pass"],
        cwd=str(Path.cwd()), env={"PATH": sys.executable.rsplit("/", 1)[0]},
        limits={"cpu_seconds": 2, "memory_bytes": 64 * 1024 * 1024}, timeout_seconds=1,
    )


def test_verified_fake_provider_emits_schema_valid_pass_evidence():
    evidence = run(FakeProvider())
    payload = evidence.to_dict()
    schema = json.loads((Path(__file__).parents[1] / "schemas/provider-conformance-evidence-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(payload)
    assert evidence.overall_status == "PASS"
    assert {c.check_id for c in evidence.checks} >= {"launch", "terminal_wait", "containment_empty", "cleanup"}


def test_unverified_provider_fails_closed_without_launch():
    provider = FakeProvider(allowed=False)
    evidence = run(provider)
    assert evidence.overall_status == "BLOCKED"
    assert "launch" not in provider.calls
    assert any(c.status == "NOT_RUN" for c in evidence.checks)


def test_nonzero_probe_exit_fails_conformance_but_cleanup_runs():
    provider = FakeProvider(exit_code=7)
    evidence = run(provider)
    assert evidence.overall_status == "FAIL"
    assert "cleanup" in provider.calls
    assert next(c for c in evidence.checks if c.check_id == "probe_exit").status == "FAIL"


def test_incomplete_containment_fails_conformance():
    evidence = run(FakeProvider(empty=False))
    assert evidence.overall_status == "FAIL"
    assert next(c for c in evidence.checks if c.check_id == "containment_empty").status == "FAIL"


def test_cleanup_exception_is_recorded_as_failure():
    evidence = run(FakeProvider(fail_cleanup=True))
    assert evidence.overall_status == "FAIL"
    assert next(c for c in evidence.checks if c.check_id == "cleanup").status == "FAIL"


def test_nonterminal_job_gets_terminate_request_and_second_wait():
    provider = FakeProvider(terminal=False)
    evidence = run(provider)
    assert "terminate" in provider.calls
    assert provider.calls.count("wait") == 2
    assert evidence.overall_status == "FAIL"  # exit code is intentionally nonzero after terminate


@pytest.mark.parametrize("kwargs", [
    {"probe_argv": []}, {"probe_argv": "python -c pass"}, {"timeout_seconds": 0},
    {"limits": {"cpu": True}},
])
def test_invalid_probe_parameters_are_rejected(kwargs):
    args = dict(target_platform="test-os", probe_argv=[sys.executable, "-c", "pass"],
                cwd=str(Path.cwd()), env={}, limits={"cpu": 1}, timeout_seconds=1)
    args.update(kwargs)
    with pytest.raises(ProviderContractError):
        run_provider_conformance(FakeProvider(), **args)


def test_evidence_json_is_stable_key_order_and_round_trips():
    evidence = run(FakeProvider())
    encoded = evidence.to_json()
    assert encoded.startswith('{"capability_report":')
    assert json.loads(encoded)["overall_status"] == "PASS"


def test_semantic_validator_rejects_duplicate_check_ids_and_false_pass_claims():
    from copy import deepcopy
    from provider_conformance import validate_evidence_payload

    payload = run(FakeProvider()).to_dict()
    duplicated = deepcopy(payload)
    duplicated["checks"].append(dict(duplicated["checks"][0]))
    assert any("duplicate check_id" in error for error in validate_evidence_payload(duplicated))

    false_pass = deepcopy(payload)
    false_pass["checks"][0]["status"] = "FAIL"
    assert any("overall PASS contradicts" in error for error in validate_evidence_payload(false_pass))


def test_semantic_validator_rejects_denied_gate_with_launch_pass_or_missing_reason():
    from copy import deepcopy
    from provider_conformance import validate_evidence_payload

    payload = run(FakeProvider(allowed=False)).to_dict()
    missing_reason = deepcopy(payload)
    missing_reason["gate_reasons"] = []
    assert any("denied gate must include" in error for error in validate_evidence_payload(missing_reason))

    false_launch = deepcopy(payload)
    false_launch["checks"].append({"check_id": "launch", "status": "PASS", "detail": "forged"})
    assert any("denied gate cannot claim launch PASS" in error for error in validate_evidence_payload(false_launch))


def test_semantic_validator_rejects_provider_metadata_mismatch():
    from copy import deepcopy
    from provider_conformance import validate_evidence_payload

    payload = run(FakeProvider()).to_dict()
    payload = deepcopy(payload)
    payload["provider_id"] = "different-provider"
    assert any("provider_id conflicts" in error for error in validate_evidence_payload(payload))


def test_canonical_digest_detects_tampering_when_expected_digest_is_external():
    from copy import deepcopy
    from provider_conformance import evidence_sha256, verify_evidence_sha256

    payload = run(FakeProvider()).to_dict()
    trusted_digest = evidence_sha256(payload)
    assert verify_evidence_sha256(payload, trusted_digest)
    modified = deepcopy(payload)
    modified["checks"][0]["detail"] += " altered"
    assert not verify_evidence_sha256(modified, trusted_digest)
    assert not verify_evidence_sha256(payload, "not-a-digest")


def test_evidence_json_parser_rejects_duplicate_json_object_keys():
    from provider_conformance import parse_evidence_json

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        parse_evidence_json('{"schema_version":"1.0","schema_version":"1.0"}')


def test_evidence_json_parser_validates_semantic_consistency():
    from provider_conformance import parse_evidence_json

    payload = run(FakeProvider()).to_dict()
    encoded = json.dumps(payload)
    assert parse_evidence_json(encoded)["overall_status"] == "PASS"
    payload["overall_status"] = "BLOCKED"
    with pytest.raises(ValueError, match="allowed gate cannot have overall_status BLOCKED"):
        parse_evidence_json(json.dumps(payload))
