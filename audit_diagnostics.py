"""Stable diagnostic codes for evidence-bundle verification failures.

Codes are API: do not renumber/reuse them. New cases get new codes. Raw verifier
messages are retained for debugging but are not intended for programmatic branching.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    code: str
    category: str
    severity: str
    message: str
    remediation: str


_RULES: tuple[tuple[tuple[str, ...], Diagnostic], ...] = (
    (("manifest is missing or unsafe",), Diagnostic("BUNDLE_MANIFEST_MISSING_OR_UNSAFE", "manifest", "error", "Manifest is missing or its path is unsafe.", "Provide the required manifest at the bundle root using its canonical filename.")),
    (("manifest exceeds size limit",), Diagnostic("BUNDLE_MANIFEST_TOO_LARGE", "resource_limit", "error", "Manifest exceeds the verifier's configured size limit.", "Inspect the bundle source and regenerate a bounded manifest.")),
    (("manifest parse failed:",), Diagnostic("BUNDLE_MANIFEST_PARSE_FAILED", "manifest", "error", "Manifest is not valid strict UTF-8 JSON or contains disallowed JSON structures.", "Regenerate the manifest as UTF-8 JSON with unique keys and finite JSON values.")),
    (("manifest schema:", "manifest schema unavailable"), Diagnostic("BUNDLE_MANIFEST_SCHEMA_INVALID", "schema", "error", "Manifest fails schema validation or the verifier schema is unavailable.", "Use the published manifest schema and check the local verifier installation.")),
    (("unsupported manifest version",), Diagnostic("BUNDLE_MANIFEST_FORMAT_UNSUPPORTED", "compatibility", "error", "Manifest version, hash algorithm, or canonicalization is unsupported.", "Regenerate the bundle with a compatible verifier and documented format version.")),
    (("unsafe manifest file path:", "envelope_path is unsafe", "duplicate manifest path:", "unsafe or duplicate"), Diagnostic("BUNDLE_PATH_UNSAFE_OR_DUPLICATE", "path", "error", "A manifest path is unsafe, non-canonical, or duplicated.", "Use unique canonical relative POSIX paths without traversal, drive prefixes, or backslashes.")),
    (("missing or unsafe file:", "manifest lists absent file:"), Diagnostic("BUNDLE_FILE_MISSING_OR_UNSAFE", "inventory", "error", "A listed file is absent, unsafe, symlinked, or not a regular in-bundle file.", "Restore the expected regular file and remove symlinks or paths escaping the bundle.")),
    (("size mismatch:",), Diagnostic("BUNDLE_FILE_SIZE_MISMATCH", "integrity", "error", "A payload file size differs from the manifest.", "Restore the original artifact or regenerate the manifest after an authorized change.")),
    (("SHA-256 mismatch:",), Diagnostic("BUNDLE_FILE_HASH_MISMATCH", "integrity", "error", "A payload file digest differs from the manifest.", "Treat the bundle as changed; verify the source independently before regenerating hashes.")),
    (("unlisted file:",), Diagnostic("BUNDLE_FILE_UNLISTED", "inventory", "error", "The bundle contains a file not listed in the manifest.", "Remove unintended files or rebuild the manifest from the approved bundle contents.")),
    (("symlink is not allowed:",), Diagnostic("BUNDLE_SYMLINK_FORBIDDEN", "path", "error", "The bundle contains a symbolic link.", "Replace symlinks with approved regular files inside the bundle.")),
    (("envelope_sha256 does not match",), Diagnostic("BUNDLE_ENVELOPE_HASH_BINDING_MISMATCH", "binding", "error", "The manifest envelope digest does not match its inventory entry.", "Rebuild the envelope and manifest in the documented order.")),
    (("envelope artifact hashes do not exactly match",), Diagnostic("BUNDLE_ENVELOPE_INVENTORY_MISMATCH", "binding", "error", "Envelope artifact hashes do not exactly match the manifest payload inventory.", "Regenerate envelope artifact entries and manifest from the same finalized payload set.")),
    (("envelope verification failed:", "manifest envelope_path is not in file inventory", "provenance envelope missing from file inventory"), Diagnostic("BUNDLE_ENVELOPE_INVALID", "envelope", "error", "The provenance envelope is missing, invalid, or inconsistent.", "Validate the provenance envelope and ensure its path is included in the manifest inventory.")),
)

_FALLBACK = Diagnostic(
    "BUNDLE_VERIFICATION_FAILED_UNCLASSIFIED", "verification", "error",
    "Verification failed for a condition without a dedicated diagnostic mapping.",
    "Inspect raw_message, preserve the failing bundle, and report the case so a stable code can be added.",
)


def classify_error(raw_message: str) -> dict[str, str]:
    """Return stable code/category/severity/message/remediation plus raw message."""
    for needles, diagnostic in _RULES:
        if any(needle in raw_message for needle in needles):
            selected = diagnostic
            break
    else:
        selected = _FALLBACK
    return {
        "code": selected.code,
        "category": selected.category,
        "severity": selected.severity,
        "message": selected.message,
        "remediation": selected.remediation,
        "raw_message": raw_message,
    }


def classify_errors(raw_messages: list[str]) -> list[dict[str, str]]:
    return [classify_error(message) for message in raw_messages]
