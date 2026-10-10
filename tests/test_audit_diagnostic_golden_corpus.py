"""Golden regression corpus and mapping coverage for audit diagnostics."""
import json
from pathlib import Path

from audit_diagnostics import _FALLBACK, _RULES, classify_error

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "tests" / "fixtures" / "audit-diagnostics-v1.json"
MATRIX_PATH = ROOT / "AUDIT_DIAGNOSTIC_COVERAGE_MATRIX.md"


def load_corpus():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert corpus["corpus_version"] == "1.0"
    assert isinstance(corpus["cases"], list) and corpus["cases"]
    return corpus["cases"]


def test_golden_corpus_matches_complete_structured_diagnostic():
    cases = load_corpus()
    seen_raw = set()
    for case in cases:
        raw = case["raw_message"]
        assert raw not in seen_raw, f"duplicate golden raw message: {raw!r}"
        seen_raw.add(raw)
        expected = {**case["expected"], "raw_message": raw}
        assert classify_error(raw) == expected


def test_every_rule_needle_and_public_code_has_golden_coverage():
    cases = load_corpus()
    raw_messages = {case["raw_message"] for case in cases}
    codes = {case["expected"]["code"] for case in cases}
    for needles, diagnostic in _RULES:
        for needle in needles:
            assert needle + " representative verifier failure" in raw_messages
        assert diagnostic.code in codes
    assert _FALLBACK.code in codes
    assert len(codes) == len({case["expected"]["code"] for case in cases})


def test_codes_are_unique_across_rules_and_matrix_documents_every_rule():
    rule_codes = [diagnostic.code for _, diagnostic in _RULES]
    assert len(rule_codes) == len(set(rule_codes)), "stable diagnostic codes must be unique"
    matrix = MATRIX_PATH.read_text(encoding="utf-8")
    for code in [*rule_codes, _FALLBACK.code]:
        assert f"`{code}`" in matrix, f"coverage matrix omits {code}"


def test_golden_corpus_contains_fallback_only_for_unknown_class():
    cases = load_corpus()
    fallback_cases = [c for c in cases if c["expected"]["code"] == _FALLBACK.code]
    assert len(fallback_cases) == 1
    assert classify_error("a newly introduced verifier condition") ["code"] == _FALLBACK.code


def test_no_literal_needle_shadowing_between_distinct_rules():
    """A shorter needle must not silently steal a longer rule's messages."""
    flattened = [
        (rule_index, needle, diagnostic.code)
        for rule_index, (needles, diagnostic) in enumerate(_RULES)
        for needle in needles
    ]
    collisions = []
    for left_index, left, left_code in flattened:
        for right_index, right, right_code in flattened:
            if left_index >= right_index:
                continue
            if left_code != right_code and (left in right or right in left):
                collisions.append((left, left_code, right, right_code))
    assert collisions == [], f"diagnostic matcher shadowing detected: {collisions!r}"


def test_first_match_precedence_is_deterministic_for_all_rule_pairs():
    """When a raw string contains needles from two rules, declared order wins."""
    for left_index, (left_needles, left_diagnostic) in enumerate(_RULES):
        for right_index in range(left_index + 1, len(_RULES)):
            right_needles, _ = _RULES[right_index]
            raw = f"{left_needles[0]} | {right_needles[0]}"
            matching_indices = [
                index for index, (needles, _) in enumerate(_RULES)
                if any(needle in raw for needle in needles)
            ]
            assert matching_indices and matching_indices[0] == left_index
            assert classify_error(raw)["code"] == left_diagnostic.code
