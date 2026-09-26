"""The commitment scheme must be identical in every language that speaks it.

The contract hashes in Python; the frontend hashes in TypeScript with Web
Crypto. If those two ever disagree -- by a separator, by a truncation rule, by
the case of an address -- the digests stop matching and an entrant's fee is
taken for a commitment that can never be opened. That is the most expensive
possible bug in this design, and it would not show up in either codebase alone,
because each is self-consistent.

So neither side is tested against the other. Both are tested against
``tests/vectors/commit_vectors.json``, a fixed file of known answers. The same
file is checked by ``scripts/check_commit_vectors.mjs`` against the frontend's
implementation.
"""

import json
from pathlib import Path

import pytest

from tests.conftest import commitment, scale_price

VECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "vectors" / "commit_vectors.json").read_text(
        encoding="utf-8"
    )
)
CASES = VECTORS["vectors"]


@pytest.mark.parametrize("case", CASES, ids=[c["forecast"] for c in CASES])
def test_the_test_harness_reproduces_the_vectors(case):
    """The independent implementation in conftest matches the fixed answers."""
    assert str(scale_price(case["forecast"])) == case["scaled"]
    assert (
        commitment(case["round_id"], case["address"], case["forecast"], case["salt"])
        == case["commitment"]
    )


@pytest.mark.parametrize("case", CASES, ids=[c["forecast"] for c in CASES])
def test_the_contract_reproduces_the_vectors(mod, case):
    """The shipped contract's own helpers match the fixed answers."""
    assert mod._dec_to_scaled(case["forecast"]) == int(case["scaled"])
    assert (
        mod._commitment(
            case["round_id"], case["address"], int(case["scaled"]), case["salt"]
        )
        == case["commitment"]
    )


def test_vectors_cover_the_cases_that_actually_break_clients():
    """A vector file that only holds easy numbers proves nothing."""
    forecasts = [c["forecast"] for c in CASES]
    assert "0.1" in forecasts, "a value with no exact float representation"
    assert any(f.startswith(".") for f in forecasts), "a bare leading dot"
    assert any(len(f.split(".")[-1]) > 8 for f in forecasts), "over-precise input"
    assert any("." not in f for f in forecasts), "an integer price"
    assert any(any(ch.isupper() for ch in c["address"]) is False for c in CASES)


def test_truncation_is_not_rounding(mod):
    """A client that rounds instead of truncating produces dead commitments."""
    # 117.999999995 truncates to 117.99999999, it does not round to .00000000.
    assert mod._dec_to_scaled("117.999999995") == 11799999999
    assert scale_price("117.999999995") == 11799999999


def test_address_case_changes_the_digest(mod):
    """Checksummed input must not silently produce an unrevealable entry."""
    lower = "0xabcdef0123456789abcdef0123456789abcdef01"
    upper = lower.upper().replace("0X", "0x")
    assert mod._commitment(1, lower, 100000000, "a" * 16) != mod._commitment(
        1, upper, 100000000, "a" * 16
    )
