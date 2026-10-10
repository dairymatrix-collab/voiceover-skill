"""Deterministic, model-free malformed-input and parser robustness tests.

These seeded tests are a regression corpus, not exhaustive fuzzing or a security audit.
Hypothesis is not installed in the current offline environment, so this suite uses only
Python's standard library and the already-pinned pytest runner.
"""
from __future__ import annotations

import json
import random
import string

import pytest

from ipc_contract import (
    IPCContractError, MAX_INTEGER_DIGITS, MAX_JSON_NESTING, MAX_LINE_BYTES,
    parse_jsonl_message,
)


def _assert_parser_has_bounded_outcomes(raw: bytes) -> None:
    """Parser must either return a dict or fail through its documented exception."""
    try:
        result = parse_jsonl_message(raw)
    except IPCContractError:
        return
    assert isinstance(result, dict)


def test_seeded_random_byte_inputs_never_leak_unexpected_parser_exceptions():
    rng = random.Random(0xD033)
    for _ in range(500):
        size = rng.randrange(0, 256)
        raw = bytes(rng.randrange(256) for _ in range(size))
        if rng.randrange(2):
            raw += b"\n"
        _assert_parser_has_bounded_outcomes(raw)


def test_seeded_unicode_strings_round_trip_through_json_parser():
    rng = random.Random(33033)
    alphabet = string.ascii_letters + string.digits + " café 世界 🌍\t\n"
    for _ in range(150):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 180)))
        raw = json.dumps({"text": value}, ensure_ascii=False).encode("utf-8") + b"\n"
        assert parse_jsonl_message(raw) == {"text": value}


@pytest.mark.parametrize("raw,code", [
    (b'{"n":1e999}\n', "PROTOCOL_NONFINITE_NUMBER"),
    (b'{"n":-1e999}\n', "PROTOCOL_NONFINITE_NUMBER"),
    (b'{"text":"\\ud800"}\n', "PROTOCOL_INVALID_UNICODE"),
    (b'{"\\udfff":"value"}\n', "PROTOCOL_INVALID_UNICODE"),
    (b'{"x":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}\n", "PROTOCOL_NESTING_TOO_DEEP"),
    (b'{"x":' + b"9" * 5000 + b"}\n", "PROTOCOL_INTEGER_TOO_LONG"),
])
def test_known_adversarial_json_inputs_have_stable_errors(raw, code):
    with pytest.raises(IPCContractError) as exc:
        parse_jsonl_message(raw)
    assert exc.value.code == code


def test_valid_json_object_at_size_boundary_is_accepted():
    # The newline is part of the configured limit; padding is valid JSON whitespace.
    base = b'{"ok":true}'
    raw = base[:-1] + b" " * (MAX_LINE_BYTES - len(base) - 1) + b"}\n"
    assert len(raw) == MAX_LINE_BYTES
    assert parse_jsonl_message(raw) == {"ok": True}


def test_one_byte_over_limit_fails_before_json_parse():
    raw = b" " * MAX_LINE_BYTES + b"\n"
    with pytest.raises(IPCContractError) as exc:
        parse_jsonl_message(raw)
    assert exc.value.code == "PROTOCOL_LINE_TOO_LARGE"


def test_nested_json_below_parser_limit_has_bounded_outcome():
    # Keep the nesting intentionally modest; the deeper case is covered above.
    raw = b'{"x":' + b"[" * 100 + b"0" + b"]" * 100 + b"}\n"
    result = parse_jsonl_message(raw)
    assert isinstance(result, dict)
    assert "x" in result


def test_nesting_limit_rejects_before_recursive_json_decode():
    raw = b'{"x":' + b"[" * (MAX_JSON_NESTING + 1) + b"0" + b"]" * (MAX_JSON_NESTING + 1) + b"}\n"
    with pytest.raises(IPCContractError) as exc:
        parse_jsonl_message(raw)
    assert exc.value.code == "PROTOCOL_NESTING_TOO_DEEP"


def test_nesting_at_limit_is_accepted():
    raw = b'{"x":' + b"[" * (MAX_JSON_NESTING - 1) + b"0" + b"]" * (MAX_JSON_NESTING - 1) + b"}\n"
    assert isinstance(parse_jsonl_message(raw), dict)


def test_brackets_and_escaped_quotes_inside_strings_do_not_count_as_nesting():
    raw = b'{"text":"[{[[\\\" ]}} ]"}\n'
    assert parse_jsonl_message(raw)["text"] == '[{[[\" ]}} ]'


def test_integer_digit_limit_is_explicit_and_boundary_is_accepted():
    allowed = b'{"n":' + b"9" * MAX_INTEGER_DIGITS + b"}\n"
    assert parse_jsonl_message(allowed)["n"] > 0
    rejected = b'{"n":' + b"9" * (MAX_INTEGER_DIGITS + 1) + b"}\n"
    with pytest.raises(IPCContractError) as exc:
        parse_jsonl_message(rejected)
    assert exc.value.code == "PROTOCOL_INTEGER_TOO_LONG"


def test_mismatched_brackets_remain_invalid_json_not_nesting_error():
    with pytest.raises(IPCContractError) as exc:
        parse_jsonl_message(b'{"x":[}}\n')
    assert exc.value.code == "PROTOCOL_INVALID_JSON"


def test_repeated_hostile_messages_fail_with_bounded_documented_errors():
    hostile = [
        b'{"x":' + b"[" * (MAX_JSON_NESTING + 5) + b"0" + b"]" * (MAX_JSON_NESTING + 5) + b"}\n",
        b'{"n":' + b"9" * (MAX_INTEGER_DIGITS + 5) + b"}\n",
        b'{"n":1e999}\n',
        b'{"x":\xff}\n',
    ]
    expected = [
        "PROTOCOL_NESTING_TOO_DEEP",
        "PROTOCOL_INTEGER_TOO_LONG",
        "PROTOCOL_NONFINITE_NUMBER",
        "PROTOCOL_INVALID_UTF8",
    ]
    for index in range(1000):
        raw = hostile[index % len(hostile)]
        with pytest.raises(IPCContractError) as exc:
            parse_jsonl_message(raw)
        assert exc.value.code == expected[index % len(expected)]
