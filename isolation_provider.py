"""Platform-neutral OS isolation provider contract (no OS provider implemented).

This module defines the fail-closed capability negotiation surface for a future
trusted supervisor. It intentionally does not launch processes or imply that the
current host is sandboxed. A provider must supply target-platform evidence before
it can pass the gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class ProviderContractError(ValueError):
    """Provider metadata or policy request is malformed."""


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


PRODUCTION_REQUIRED_CAPABILITIES = frozenset({
    "process_tree_containment",
    "cpu_time_limit",
    "memory_limit",
    "filesystem_policy",
    "network_policy",
    "least_privilege_identity",
    "cleanup_confirmation",
    "bounded_observability",
})


@dataclass(frozen=True)
class CapabilityReport:
    provider_id: str
    provider_version: str
    platform: str
    status: VerificationStatus
    capabilities: Mapping[str, bool]
    limitations: tuple[str, ...] = ()
    verification_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("provider_id", "provider_version", "platform"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ProviderContractError(f"{field_name} must be a non-empty string")
        if not isinstance(self.status, VerificationStatus):
            raise ProviderContractError("status must be a VerificationStatus")
        if not isinstance(self.capabilities, Mapping):
            raise ProviderContractError("capabilities must be a mapping")
        for key, value in self.capabilities.items():
            if not isinstance(key, str) or not key.strip():
                raise ProviderContractError("capability names must be non-empty strings")
            if type(value) is not bool:
                raise ProviderContractError(f"capability {key!r} must be an explicit bool")
        for field_name in ("limitations", "verification_evidence"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or any(not isinstance(item, str) or not item.strip() for item in value):
                raise ProviderContractError(f"{field_name} must be a tuple of non-empty strings")


@dataclass(frozen=True)
class IsolationPolicy:
    required_capabilities: frozenset[str] = field(default_factory=lambda: PRODUCTION_REQUIRED_CAPABILITIES)
    deny_network_by_default: bool = True
    allow_secrets_in_environment: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.required_capabilities, frozenset) or any(
            not isinstance(item, str) or not item.strip() for item in self.required_capabilities
        ):
            raise ProviderContractError("required_capabilities must be a frozenset of non-empty strings")
        if type(self.deny_network_by_default) is not bool or type(self.allow_secrets_in_environment) is not bool:
            raise ProviderContractError("policy switches must be explicit booleans")
        if self.allow_secrets_in_environment:
            raise ProviderContractError("secrets in worker environments are prohibited by this contract")


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    provider_id: str
    target_platform: str
    missing_capabilities: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class JobHandle:
    """Opaque provider job identity; callers must not infer an OS PID from it."""
    provider_id: str
    token: str

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.token.strip():
            raise ProviderContractError("job handle provider_id and token must be non-empty")


@dataclass(frozen=True)
class JobInspection:
    containment_empty: bool
    effective_capabilities: Mapping[str, bool]
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.containment_empty) is not bool:
            raise ProviderContractError("containment_empty must be an explicit bool")
        if not isinstance(self.effective_capabilities, Mapping) or any(
            not isinstance(k, str) or type(v) is not bool for k, v in self.effective_capabilities.items()
        ):
            raise ProviderContractError("effective_capabilities must map strings to explicit booleans")


@dataclass(frozen=True)
class WaitResult:
    terminal: bool
    exit_code: int | None
    containment_empty: bool
    reason_code: str

    def __post_init__(self) -> None:
        if type(self.terminal) is not bool or type(self.containment_empty) is not bool:
            raise ProviderContractError("terminal and containment_empty must be explicit booleans")
        if self.exit_code is not None and (isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)):
            raise ProviderContractError("exit_code must be an integer or None")
        if not isinstance(self.reason_code, str) or not self.reason_code.strip():
            raise ProviderContractError("reason_code must be non-empty")
        if self.containment_empty and not self.terminal:
            raise ProviderContractError("a non-terminal job cannot claim confirmed empty containment")


@runtime_checkable
class IsolationProvider(Protocol):
    """Required provider operations. Implementations must be trusted deployment code."""

    def capability_report(self) -> CapabilityReport: ...

    def launch(
        self, argv: Sequence[str], *, cwd: str, env: Mapping[str, str],
        limits: Mapping[str, int | float], policy: IsolationPolicy,
    ) -> JobHandle: ...

    def terminate(self, job: JobHandle, *, reason: str) -> None: ...

    def wait(self, job: JobHandle, *, deadline_monotonic: float) -> WaitResult: ...

    def inspect(self, job: JobHandle) -> JobInspection: ...

    def cleanup(self, job: JobHandle) -> None: ...


def negotiate_provider(
    report: CapabilityReport,
    *,
    target_platform: str,
    policy: IsolationPolicy | None = None,
) -> GateDecision:
    """Return an explicit fail-closed decision; never infer unknown capabilities."""
    if not isinstance(report, CapabilityReport):
        raise ProviderContractError("report must be a CapabilityReport")
    if not isinstance(target_platform, str) or not target_platform.strip():
        raise ProviderContractError("target_platform must be a non-empty string")
    policy = policy or IsolationPolicy()
    if not isinstance(policy, IsolationPolicy):
        raise ProviderContractError("policy must be an IsolationPolicy")

    reasons: list[str] = []
    missing = tuple(sorted(cap for cap in policy.required_capabilities if report.capabilities.get(cap) is not True))
    if report.platform.casefold() != target_platform.casefold():
        reasons.append("TARGET_PLATFORM_MISMATCH")
    if report.status is not VerificationStatus.VERIFIED:
        reasons.append("PROVIDER_NOT_VERIFIED")
    if not report.verification_evidence:
        reasons.append("VERIFICATION_EVIDENCE_MISSING")
    if missing:
        reasons.append("REQUIRED_CAPABILITIES_MISSING")
    if policy.deny_network_by_default and report.capabilities.get("network_policy") is not True:
        if "NETWORK_DENIAL_NOT_VERIFIED" not in reasons:
            reasons.append("NETWORK_DENIAL_NOT_VERIFIED")
    return GateDecision(
        allowed=not reasons,
        provider_id=report.provider_id,
        target_platform=target_platform,
        missing_capabilities=missing,
        reasons=tuple(reasons),
    )


def require_provider(
    provider: IsolationProvider,
    *,
    target_platform: str,
    policy: IsolationPolicy | None = None,
) -> GateDecision:
    """Gate a provider before any production launch; errors fail closed."""
    if not isinstance(provider, IsolationProvider):
        raise ProviderContractError("provider does not implement the isolation contract")
    report = provider.capability_report()
    decision = negotiate_provider(report, target_platform=target_platform, policy=policy)
    if not decision.allowed:
        return decision
    return decision
