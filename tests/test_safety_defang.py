from __future__ import annotations

import pytest

from hecavex_radar.certstream import public_certificate_text
from hecavex_radar.safety import DOMAIN_IN_TEXT, defang_domains_in_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("see example.com today", "see example[.]com today"),
        ("Login at example.com.", "Login at example[.]com."),
        ("ns1.example.com.", "ns1[.]example[.]com."),
        # A hyphen after the TLD is treated as more label text: defang the dot.
        ("example.com-x", "example[.]com-x"),
        ("example.com.1", "example[.]com.1"),
        ("пример.рф", "пример[.]рф"),
        ("вход на пример.рф.", "вход на пример[.]рф."),
        ("example。com", "example[.]com"),
        ("example．com", "example[.]com"),
        ("example｡com", "example[.]com"),
        ("ｅｘａｍｐｌｅ．ｃｏｍ", "ｅｘａｍｐｌｅ[.]ｃｏｍ"),
        ("xn--e1afmkfd.xn--p1ai", "xn--e1afmkfd[.]xn--p1ai"),
        ("login.xn--p1ai/path", "login[.]xn--p1ai/path"),
        ("münchen.de", "münchen[.]de"),
    ],
)
def test_defangs_every_host_form(text: str, expected: str) -> None:
    assert defang_domains_in_text(text) == expected
    assert DOMAIN_IN_TEXT.search(expected) is None
    assert defang_domains_in_text(expected) == expected


@pytest.mark.parametrize(
    "text",
    ["Hello. World", "version 1.25 and 10.0.0.1", "e.g. this, i.e. that", "already example[.]com", "U.S.A."],
)
def test_leaves_non_host_text_unchanged(text: str) -> None:
    assert defang_domains_in_text(text) == text


def test_free_text_callers_inherit_trailing_dot_defanging() -> None:
    assert public_certificate_text("Issued for ns1.example.com.") == "Issued for ns1[.]example[.]com."
