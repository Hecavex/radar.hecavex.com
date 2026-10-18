from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from hecavex_radar.certstream import public_certificate_text
from hecavex_radar.safety import DOMAIN_IN_TEXT, defang_domains_in_text

# Shared with scripts/published-defanging.test.mjs so the Python and JS host patterns cannot drift.
PARITY = json.loads((Path(__file__).parent / "fixtures" / "defang-parity.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("text", "expected"), PARITY["defanged"])
def test_defangs_every_host_form(text: str, expected: str) -> None:
    assert defang_domains_in_text(text) == expected
    assert DOMAIN_IN_TEXT.search(expected) is None
    assert defang_domains_in_text(expected) == expected


@pytest.mark.parametrize("text", PARITY["unchanged"])
def test_leaves_non_host_text_unchanged(text: str) -> None:
    assert defang_domains_in_text(text) == text


def test_free_text_callers_inherit_trailing_dot_defanging() -> None:
    assert public_certificate_text("Issued for ns1.example.com.") == "Issued for ns1[.]example[.]com."


def test_chains_longer_than_the_label_bound_are_fully_defanged() -> None:
    result = defang_domains_in_text("ab." * 300 + "cd")
    assert "." not in result.replace("[.]", "")
    assert DOMAIN_IN_TEXT.search(result) is None


@pytest.mark.parametrize(
    "text",
    ["1." * 5000, "a." * 5000, "a-" * 5000, ("a" * 62 + ".") * 160 + "1"],
    ids=["digits", "letters", "hyphens", "long-labels"],
)
def test_adversarial_input_is_linear(text: str) -> None:
    started = time.perf_counter()
    defang_domains_in_text(text)
    assert time.perf_counter() - started < 1.0
