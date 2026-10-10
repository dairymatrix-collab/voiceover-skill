from audit_diagnostics import classify_error, classify_errors


def test_diagnostic_codes_are_stable_for_known_failure_classes():
    cases = {
        "manifest is missing or unsafe": "BUNDLE_MANIFEST_MISSING_OR_UNSAFE",
        "manifest parse failed: JSONDecodeError": "BUNDLE_MANIFEST_PARSE_FAILED",
        "manifest schema: field invalid": "BUNDLE_MANIFEST_SCHEMA_INVALID",
        "size mismatch: payload/a.wav": "BUNDLE_FILE_SIZE_MISMATCH",
        "SHA-256 mismatch: payload/a.wav": "BUNDLE_FILE_HASH_MISMATCH",
        "unlisted file: payload/extra.txt": "BUNDLE_FILE_UNLISTED",
        "envelope_sha256 does not match envelope file inventory": "BUNDLE_ENVELOPE_HASH_BINDING_MISMATCH",
        "envelope artifact hashes do not exactly match bundle payload files": "BUNDLE_ENVELOPE_INVENTORY_MISMATCH",
    }
    for raw, expected in cases.items():
        first = classify_error(raw)
        second = classify_error(raw)
        assert first["code"] == expected
        assert first == second
        assert first["raw_message"] == raw
        assert first["remediation"]


def test_unmapped_errors_fail_closed_with_explicit_fallback_code():
    diagnostic = classify_error("new verifier condition not yet mapped")
    assert diagnostic["code"] == "BUNDLE_VERIFICATION_FAILED_UNCLASSIFIED"
    assert diagnostic["severity"] == "error"


def test_bulk_classification_preserves_order_and_cardinality():
    raw = ["size mismatch: a", "SHA-256 mismatch: b"]
    diagnostics = classify_errors(raw)
    assert len(diagnostics) == len(raw)
    assert [item["raw_message"] for item in diagnostics] == raw
    assert [item["code"] for item in diagnostics] == [
        "BUNDLE_FILE_SIZE_MISMATCH", "BUNDLE_FILE_HASH_MISMATCH"
    ]
