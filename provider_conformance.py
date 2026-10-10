"""Model-free conformance runner for trusted isolation-provider implementations.

This module does not implement a sandbox. It only tests a provider supplied by
trusted deployment code and emits a machine-readable evidence record. Evidence
records are reports, not cryptographic attestations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import time
from typing import Any, Mapping, Sequence

from isolation_provider import (
    CapabilityReport,
    IsolationPolicy,
    JobHandle,
    IsolationProvider,
    ProviderContractError,
    VerificationStatus,
    negotiate_provider,
)


EVIDENCE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    status: str
    detail: str

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}:
            raise ValueError("invalid check status")
        if not self.check_id.strip() or not self.detail.strip():
            raise ValueError("check_id and detail must be non-empty")


@dataclass(frozen=True)
class ConformanceEvidence:
    schema_version: str
    generated_at: str
    provider_id: str
    provider_version: str
    target_platform: str
    provider_status: str
    gate_allowed: bool
    gate_reasons: tuple[str, ...]
    capability_report: Mapping[str, Any]
    checks: tuple[CheckResult, ...]
    overall_status: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "target_platform": self.target_platform,
            "provider_status": self.provider_status,
            "gate_allowed": self.gate_allowed,
            "gate_reasons": list(self.gate_reasons),
            "capability_report": dict(self.capability_report),
            "checks": [asdict(check) for check in self.checks],
            "overall_status": self.overall_status,
            "limitations": list(self.limitations),
        }
        errors = validate_evidence_payload(payload)
        if errors:
            raise ProviderContractError("invalid conformance evidence: " + "; ".join(errors))
        return payload

    def to_json(self) -> str:
        return canonical_evidence_json(self.to_dict())


def canonical_evidence_json(payload: Mapping[str, Any]) -> str:
    """Return canonical JSON for hashing/transport; this is not a signature."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def evidence_sha256(payload: Mapping[str, Any]) -> str:
    """Hash canonical evidence bytes. Trust must come from an external channel."""
    return hashlib.sha256(canonical_evidence_json(payload).encode("utf-8")).hexdigest()


def verify_evidence_sha256(payload: Mapping[str, Any], expected_digest: str) -> bool:
    """Compare a canonical evidence digest to a separately trusted expected value."""
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        return False
    try:
        int(expected_digest, 16)
    except ValueError:
        return False
    return hmac.compare_digest(evidence_sha256(payload), expected_digest.lower())


def parse_evidence_json(raw: str) -> dict[str, Any]:
    """Parse evidence JSON while rejecting duplicate object keys at every depth."""
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"invalid JSON constant: {token}")))
    if not isinstance(value, dict):
        raise ValueError("evidence JSON root must be an object")
    errors = validate_evidence_payload(value)
    if errors:
        raise ValueError("invalid evidence payload: " + "; ".join(errors))
    return value


def validate_evidence_payload(payload: Mapping[str, Any]) -> list[str]:
    """Validate cross-field semantics beyond what JSON Schema can express."""
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["evidence root must be an object"]
    required = {
        "schema_version", "generated_at", "provider_id", "provider_version", "target_platform",
        "provider_status", "gate_allowed", "gate_reasons", "capability_report", "checks",
        "overall_status", "limitations",
    }
    missing = sorted(required - set(payload))
    if missing:
        return ["missing required fields: " + ", ".join(missing)]
    if payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    if type(payload.get("gate_allowed")) is not bool:
        errors.append("gate_allowed must be boolean")
    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append("checks must be a non-empty array")
        checks = []
    seen: set[str] = set()
    statuses: list[str] = []
    for index, check in enumerate(checks):
        if not isinstance(check, Mapping):
            errors.append(f"checks[{index}] must be an object")
            continue
        check_id, status, detail = check.get("check_id"), check.get("status"), check.get("detail")
        if not isinstance(check_id, str) or not check_id.strip():
            errors.append(f"checks[{index}] has invalid check_id")
        elif check_id in seen:
            errors.append(f"duplicate check_id: {check_id}")
        else:
            seen.add(check_id)
        if not isinstance(status, str) or status not in {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}:
            errors.append(f"checks[{index}] has invalid status")
        else:
            statuses.append(status)
        if not isinstance(detail, str) or not detail.strip():
            errors.append(f"checks[{index}] has empty detail")

    report = payload.get("capability_report")
    if not isinstance(report, Mapping):
        errors.append("capability_report must be an object")
    else:
        for top, nested in (("provider_id", "provider_id"), ("provider_version", "provider_version"), ("provider_status", "status")):
            if payload.get(top) != report.get(nested):
                errors.append(f"{top} conflicts with capability_report.{nested}")
        if report.get("platform") != payload.get("target_platform"):
            errors.append("capability_report.platform conflicts with target_platform")

    gate_allowed = payload.get("gate_allowed")
    reasons = payload.get("gate_reasons")
    if not isinstance(reasons, list) or any(not isinstance(reason, str) or not reason.strip() for reason in reasons):
        errors.append("gate_reasons must be an array of non-empty strings")
        reasons = []
    if gate_allowed is False:
        if not reasons:
            errors.append("denied gate must include at least one reason")
        if payload.get("overall_status") != "BLOCKED":
            errors.append("denied gate requires overall_status BLOCKED")
        if any(check.get("check_id") == "launch" and check.get("status") == "PASS" for check in checks if isinstance(check, Mapping)):
            errors.append("denied gate cannot claim launch PASS")
        if any(check.get("check_id") == "launch_wait_inspect_cleanup" and check.get("status") != "NOT_RUN" for check in checks if isinstance(check, Mapping)):
            errors.append("denied gate lifecycle check must be NOT_RUN")
        gate_check = next((c for c in checks if isinstance(c, Mapping) and c.get("check_id") == "fail_closed_gate"), None)
        if gate_check is None or gate_check.get("status") != "BLOCKED":
            errors.append("denied gate requires fail_closed_gate BLOCKED")
    elif gate_allowed is True:
        if reasons:
            errors.append("allowed gate must not include denial reasons")
        gate_check = next((c for c in checks if isinstance(c, Mapping) and c.get("check_id") == "fail_closed_gate"), None)
        if gate_check is None or gate_check.get("status") != "PASS":
            errors.append("allowed gate requires fail_closed_gate PASS")
        if payload.get("overall_status") == "BLOCKED":
            errors.append("allowed gate cannot have overall_status BLOCKED")

    if payload.get("overall_status") == "PASS" and any(status != "PASS" for status in statuses):
        errors.append("overall PASS contradicts non-PASS check status")
    if payload.get("overall_status") == "FAIL" and not any(status == "FAIL" for status in statuses):
        errors.append("overall FAIL requires at least one failed check")
    if payload.get("overall_status") == "BLOCKED" and gate_allowed is not False:
        errors.append("overall BLOCKED requires gate denial")
    if not isinstance(payload.get("overall_status"), str) or payload.get("overall_status") not in {"PASS", "FAIL", "BLOCKED"}:
        errors.append("invalid overall_status")
    if gate_allowed is True and statuses and all(status == "PASS" for status in statuses) and payload.get("overall_status") != "PASS":
        errors.append("all checks PASS requires overall_status PASS")
    return errors


def _report_dict(report: CapabilityReport) -> dict[str, Any]:
    return {
        "provider_id": report.provider_id,
        "provider_version": report.provider_version,
        "platform": report.platform,
        "status": report.status.value,
        "capabilities": dict(sorted(report.capabilities.items())),
        "limitations": list(report.limitations),
        "verification_evidence": list(report.verification_evidence),
    }


def run_provider_conformance(
    provider: IsolationProvider,
    *,
    target_platform: str,
    probe_argv: Sequence[str],
    cwd: str,
    env: Mapping[str, str],
    limits: Mapping[str, int | float],
    timeout_seconds: float = 10.0,
    policy: IsolationPolicy | None = None,
) -> ConformanceEvidence:
    """Run a trusted provider against one trusted, harmless probe command.

    The caller is responsible for choosing the probe executable/arguments and
    a safe test directory. No command is assembled from untrusted user input.
    """
    if not isinstance(provider, IsolationProvider):
        raise ProviderContractError("provider does not implement the isolation contract")
    if not isinstance(probe_argv, Sequence) or isinstance(probe_argv, (str, bytes)) or not probe_argv:
        raise ProviderContractError("probe_argv must be a non-empty sequence of trusted strings")
    if any(not isinstance(arg, str) or not arg for arg in probe_argv):
        raise ProviderContractError("probe_argv entries must be non-empty strings")
    if not isinstance(cwd, str) or not cwd or not isinstance(env, Mapping):
        raise ProviderContractError("cwd must be non-empty and env must be a mapping")
    if not isinstance(limits, Mapping) or any(
        not isinstance(key, str) or not key or isinstance(value, bool) or
        not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
        for key, value in limits.items()
    ):
        raise ProviderContractError("limits must map non-empty strings to positive finite numbers")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ProviderContractError("timeout_seconds must be a positive finite number")

    report = provider.capability_report()
    if not isinstance(report, CapabilityReport):
        raise ProviderContractError("capability_report() must return CapabilityReport")
    decision = negotiate_provider(report, target_platform=target_platform, policy=policy)
    checks: list[CheckResult] = [
        CheckResult("capability_report_shape", "PASS", "provider returned a valid CapabilityReport"),
        CheckResult("fail_closed_gate", "PASS" if decision.allowed else "BLOCKED",
                    "provider gate allowed probe" if decision.allowed else ";".join(decision.reasons)),
    ]
    limitations = list(report.limitations)
    if not decision.allowed:
        checks.append(CheckResult("launch_wait_inspect_cleanup", "NOT_RUN", "gate denied launch; no probe was started"))
        overall = "BLOCKED"
    else:
        job: JobHandle | None = None
        terminal = False
        exit_code: int | None = None
        containment_empty = False
        try:
            job = provider.launch(probe_argv, cwd=cwd, env=env, limits=limits, policy=policy or IsolationPolicy())
            if not isinstance(job, JobHandle):
                raise ProviderContractError("launch() must return JobHandle")
            checks.append(CheckResult("launch", "PASS", "provider returned an opaque JobHandle"))
            before = provider.inspect(job)
            if not before.effective_capabilities or any(value is not True for value in before.effective_capabilities.values()):
                checks.append(CheckResult("effective_capabilities", "FAIL", "inspection omitted capabilities or reported a false capability"))
            else:
                checks.append(CheckResult("effective_capabilities", "PASS", "inspection reports explicit true values for returned effective capabilities"))
            result = provider.wait(job, deadline_monotonic=time.monotonic() + float(timeout_seconds))
            if not result.terminal:
                provider.terminate(job, reason="CONFORMANCE_TIMEOUT")
                checks.append(CheckResult("terminate", "PASS", "non-terminal probe was asked to terminate"))
                result = provider.wait(job, deadline_monotonic=time.monotonic() + min(float(timeout_seconds), 2.0))
            terminal = result.terminal
            exit_code = result.exit_code
            containment_empty = result.containment_empty
            checks.append(CheckResult("terminal_wait", "PASS" if terminal else "FAIL", result.reason_code))
            inspection = provider.inspect(job)
            containment_empty = containment_empty and inspection.containment_empty
            checks.append(CheckResult("containment_empty", "PASS" if containment_empty else "FAIL",
                                      "terminal result and inspection both confirm empty containment" if containment_empty else "provider did not confirm empty containment"))
            checks.append(CheckResult("probe_exit", "PASS" if terminal and exit_code == 0 else "FAIL",
                                      f"exit_code={exit_code!r}"))
        except Exception as exc:
            checks.append(CheckResult("provider_operation", "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}"))
        finally:
            if job is not None:
                try:
                    provider.cleanup(job)
                    checks.append(CheckResult("cleanup", "PASS", "cleanup() returned without raising"))
                except Exception as exc:
                    checks.append(CheckResult("cleanup", "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}"))
        overall = "PASS" if all(c.status == "PASS" for c in checks) else "FAIL"

    return ConformanceEvidence(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        provider_id=report.provider_id,
        provider_version=report.provider_version,
        target_platform=target_platform,
        provider_status=report.status.value,
        gate_allowed=decision.allowed,
        gate_reasons=decision.reasons,
        capability_report=_report_dict(report),
        checks=tuple(checks),
        overall_status=overall,
        limitations=tuple(limitations),
    )
