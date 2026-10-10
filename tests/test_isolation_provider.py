from dataclasses import replace

import pytest

from isolation_provider import (
    CapabilityReport,
    IsolationPolicy,
    JobHandle,
    JobInspection,
    ProviderContractError,
    VerificationStatus,
    WaitResult,
    negotiate_provider,
    PRODUCTION_REQUIRED_CAPABILITIES,
)


def verified_report(**overrides):
    values = dict(
        provider_id="test-provider",
        provider_version="0.0-test",
        platform="linux-x86_64",
        status=VerificationStatus.VERIFIED,
        capabilities={key: True for key in PRODUCTION_REQUIRED_CAPABILITIES},
        limitations=("test double only",),
        verification_evidence=("test-fixture://provider-evidence",),
    )
    values.update(overrides)
    return CapabilityReport(**values)


def test_all_required_explicit_capabilities_and_matching_platform_allow_gate():
    decision = negotiate_provider(verified_report(), target_platform="linux-x86_64")
    assert decision.allowed is True
    assert decision.missing_capabilities == ()
    assert decision.reasons == ()


@pytest.mark.parametrize("status", [VerificationStatus.UNVERIFIED])
def test_unverified_provider_fails_closed(status):
    decision = negotiate_provider(verified_report(status=status), target_platform="linux-x86_64")
    assert not decision.allowed
    assert "PROVIDER_NOT_VERIFIED" in decision.reasons


def test_missing_capability_is_not_inferred_from_unknown():
    caps = dict(verified_report().capabilities)
    del caps["network_policy"]
    decision = negotiate_provider(verified_report(capabilities=caps), target_platform="linux-x86_64")
    assert not decision.allowed
    assert "network_policy" in decision.missing_capabilities
    assert "NETWORK_DENIAL_NOT_VERIFIED" in decision.reasons


def test_false_capability_fails_closed():
    caps = dict(verified_report().capabilities)
    caps["memory_limit"] = False
    decision = negotiate_provider(verified_report(capabilities=caps), target_platform="linux-x86_64")
    assert not decision.allowed
    assert "memory_limit" in decision.missing_capabilities


def test_target_platform_mismatch_fails_closed():
    decision = negotiate_provider(verified_report(), target_platform="windows-x64")
    assert not decision.allowed
    assert "TARGET_PLATFORM_MISMATCH" in decision.reasons


def test_missing_evidence_fails_closed_even_if_status_claims_verified():
    decision = negotiate_provider(verified_report(verification_evidence=()), target_platform="linux-x86_64")
    assert not decision.allowed
    assert "VERIFICATION_EVIDENCE_MISSING" in decision.reasons


def test_secrets_environment_policy_is_rejected():
    with pytest.raises(ProviderContractError):
        IsolationPolicy(allow_secrets_in_environment=True)


@pytest.mark.parametrize("bad", ["", " ", None, 7])
def test_report_requires_nonempty_identity_fields(bad):
    with pytest.raises(ProviderContractError):
        verified_report(provider_id=bad)


def test_capabilities_must_be_explicit_booleans():
    caps = dict(verified_report().capabilities)
    caps["memory_limit"] = 1
    with pytest.raises(ProviderContractError):
        verified_report(capabilities=caps)


def test_wait_result_cannot_claim_empty_before_terminal():
    with pytest.raises(ProviderContractError):
        WaitResult(terminal=False, exit_code=None, containment_empty=True, reason_code="RUNNING")


def test_job_handle_requires_provider_and_opaque_token():
    assert JobHandle("p", "opaque-token").token == "opaque-token"
    with pytest.raises(ProviderContractError):
        JobHandle("p", " ")


def test_inspection_requires_explicit_boolean_capabilities():
    with pytest.raises(ProviderContractError):
        JobInspection(containment_empty=True, effective_capabilities={"network_policy": 1})


def test_production_capability_set_is_stable_and_nonempty():
    assert len(PRODUCTION_REQUIRED_CAPABILITIES) == 8
    assert "process_tree_containment" in PRODUCTION_REQUIRED_CAPABILITIES
    assert "cleanup_confirmation" in PRODUCTION_REQUIRED_CAPABILITIES
