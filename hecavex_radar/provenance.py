from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from .models import BrandEvidence, ReasonCode

REASON_CODES = frozenset(
    {
        "brand-domain-match",
        "brand-title-match",
        "provider-verdict",
        "primary-html-hash-pivot",
        "brand-exact-token",
        "brand-joined-affix",
        "brand-split-token",
        "brand-lookalike-edit",
        "suspicious-context",
        "punycode",
        "different-tld",
        "multiple-hyphens",
        "unicode-confusable",
        "mixed-script",
        "restricted-identifier",
        "hecavex-public-export",
        "manual-review",
        "first-publication",
        "source-status-change",
    }
)

BRAND_EVIDENCE_REASON: dict[BrandEvidence, ReasonCode] = {
    "domain": "brand-domain-match",
    "title": "brand-title-match",
    "verdict": "provider-verdict",
    "primary-html-sha256": "primary-html-hash-pivot",
}


def normalize_reason_codes(values: Iterable[object] | None) -> list[ReasonCode]:
    if values is None:
        return []
    return [
        cast(ReasonCode, value)
        for value in dict.fromkeys(values)
        if isinstance(value, str) and value in REASON_CODES
    ][:16]


def reason_codes_from_match(reasons: Iterable[str]) -> list[ReasonCode]:
    codes: list[str] = []
    for reason in reasons:
        lowered = reason.casefold()
        if lowered.startswith(("brand text match:", "exact short brand token:")):
            codes.append("brand-exact-token")
        elif lowered.startswith("curated idn visual match:"):
            codes.append("brand-domain-match")
        elif lowered.startswith("brand text with suspicious affix:"):
            codes.append("brand-joined-affix")
        elif lowered.startswith("brand text split across label:"):
            codes.append("brand-split-token")
        elif lowered.startswith("brand lookalike (edit distance 1):"):
            codes.append("brand-lookalike-edit")
        elif lowered.startswith("suspicious token:"):
            codes.append("suspicious-context")
        elif lowered == "internationalized domain (punycode)":
            codes.append("punycode")
        elif lowered == "different top-level domain from registry":
            codes.append("different-tld")
        elif lowered == "multiple hyphens":
            codes.append("multiple-hyphens")
        elif lowered == "unicode confusable skeleton matched a reviewed alias":
            codes.append("unicode-confusable")
        elif lowered == "mixed-script identifier":
            codes.append("mixed-script")
        elif lowered == "restricted identifier profile":
            codes.append("restricted-identifier")
    return normalize_reason_codes(codes)


def reason_codes_from_evidence(values: Iterable[BrandEvidence]) -> list[ReasonCode]:
    return normalize_reason_codes(BRAND_EVIDENCE_REASON[value] for value in values)
