from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import idna
import tldextract
from confusable_homoglyphs import categories, confusables  # type: ignore[import-untyped]

from .models import CandidateMatch

LABEL = re.compile(r"^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$", re.IGNORECASE)
EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)
SUSPICIOUS_WORDS = {
    "access",
    "account",
    "atnaujinti",
    "auth",
    "bankas",
    "billing",
    "bank",
    "card",
    "cards",
    "claim",
    "client",
    "confirm",
    "delivery",
    "deposit",
    "draudimas",
    "identity",
    "invoice",
    "klientas",
    "kortele",
    "login",
    "mokejimas",
    "mobile",
    "online",
    "parcel",
    "password",
    "pay",
    "payment",
    "paskyra",
    "patvirtinti",
    "portal",
    "prisijungimas",
    "prisijungti",
    "refund",
    "saskaita",
    "secure",
    "security",
    "sekimas",
    "service",
    "shipment",
    "signin",
    "siunta",
    "support",
    "track",
    "tracking",
    "update",
    "verify",
    "wallet",
}
KNOWN_CT_REWRITE_SUFFIXES = {
    "admin-mcas-df.ms",
    "admin-mcas-gov-df.ms",
    "admin-mcas-gov-df.us",
    "admin-mcas-gov.ms",
    "admin-mcas-gov.us",
    "admin-mcas.ms",
    "admin-rs-mcas-df.ms",
    "admin-rs-mcas.ms",
    "mcas-df.ms",
    "mcas-gov-df.ms",
    "mcas-gov-df.us",
    "mcas-gov.ms",
    "mcas-gov.us",
    "mcas.ms",
    "rs-mcas-df.ms",
    "rs-mcas.ms",
}
UNICODE_SECURITY_PROFILE = {
    "uts46": f"idna-{version('idna')}/nontransitional/std3",
    "uts39": f"confusable-homoglyphs-{version('confusable-homoglyphs')}",
}
IDN_VISUAL_PROFILE = "radar-idn-visual-v1"
IDN_VISUAL_REPLACEMENTS = {"ƙ": ("k",), "ө": ("o", "e"), "ӏ": ("i", "l")}
IGNORED_SCRIPT_ALIASES = frozenset({"COMMON", "INHERITED"})
SHORT_ALIAS_MAXIMUM_LENGTH = 4


@dataclass(frozen=True, slots=True)
class BrandEntry:
    brand: str
    last_reviewed_at: str
    aliases: list[str]
    fuzzy_aliases: list[str]
    excluded_terms: list[str]
    excluded_domains: list[str]
    category: str
    official_domains: list[str]
    sources: list[str]


@dataclass(frozen=True, slots=True)
class BrandRegistry:
    scope: str
    reviewed_at: str
    entries: list[BrandEntry]


def _strings(value: object) -> list[str] | None:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        return None
    return [item.strip() for item in value]


def _optional_strings(value: object) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        return None
    return [item.strip() for item in value]


def normalize_domain(value: str) -> str | None:
    without_wildcard = re.sub(r"^\*\.", "", value.strip(), count=1).removesuffix(".").lower()
    try:
        ascii_domain = idna.encode(
            without_wildcard,
            uts46=True,
            transitional=False,
            std3_rules=True,
        ).decode("ascii").lower()
    except idna.IDNAError:
        return None
    labels = ascii_domain.split(".")
    if not ascii_domain or len(ascii_domain) > 253 or ":" in ascii_domain or len(labels) < 2:
        return None
    if any(not LABEL.fullmatch(label) for label in labels):
        return None
    return ascii_domain


def load_brand_registry(path: Path | None = None) -> BrandRegistry:
    target = path or Path.cwd() / "data" / "brands-lt.json"
    payload: Any = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("Brand registry has an invalid top-level shape.")
    scope = payload.get("scope")
    reviewed_at = payload.get("reviewedAt")
    if not isinstance(scope, str) or not scope.strip() or not isinstance(reviewed_at, str):
        raise ValueError("Brand registry metadata is invalid.")
    try:
        if date.fromisoformat(reviewed_at).isoformat() != reviewed_at:
            raise ValueError
    except ValueError as error:
        raise ValueError("Brand registry reviewedAt must be a valid YYYY-MM-DD date.") from error
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("Brand registry entries are invalid.")

    entries: list[BrandEntry] = []
    seen_brands: set[str] = set()
    seen_aliases: dict[str, str] = {}
    seen_domains: dict[str, str] = {}
    seen_excluded_domains: set[str] = set()
    for index, raw in enumerate(raw_entries, start=1):
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("brand"), str)
            or not isinstance(raw.get("category"), str)
        ):
            raise ValueError(f"Brand registry entry {index} is invalid.")
        aliases = _strings(raw.get("aliases"))
        last_reviewed_at = raw.get("lastReviewedAt")
        fuzzy_aliases = _optional_strings(raw.get("fuzzyAliases"))
        excluded_terms = _optional_strings(raw.get("excludedTerms"))
        excluded_domains = _optional_strings(raw.get("excludedDomains"))
        official = _strings(raw.get("officialDomains"))
        sources = _strings(raw.get("sources"))
        normalized_official = [domain for item in official or [] if (domain := normalize_domain(item))]
        normalized_excluded = [
            domain for item in excluded_domains or [] if (domain := normalize_domain(item))
        ]
        if (
            not aliases
            or not isinstance(last_reviewed_at, str)
            or fuzzy_aliases is None
            or excluded_terms is None
            or excluded_domains is None
            or len(normalized_official) != len(official or [])
            or len(normalized_excluded) != len(excluded_domains)
            or not normalized_official
            or not sources
        ):
            raise ValueError(f"Brand registry entry {index} is invalid.")
        try:
            if date.fromisoformat(last_reviewed_at).isoformat() != last_reviewed_at:
                raise ValueError
        except ValueError as error:
            raise ValueError(f"Brand registry entry {index} has an invalid lastReviewedAt date.") from error
        if any(not _canonical(term) for term in excluded_terms):
            raise ValueError(f"Brand registry entry {index} has an invalid excluded term.")
        brand = raw["brand"].strip()
        if not brand or not raw["category"].strip():
            raise ValueError(f"Brand registry entry {index} is invalid.")
        normalized_lists = (
            [alias.casefold() for alias in aliases],
            [term.casefold() for term in excluded_terms],
            normalized_official,
            normalized_excluded,
            [source.casefold() for source in sources],
        )
        if any(len(values) != len(set(values)) for values in normalized_lists):
            raise ValueError(f"Brand registry entry {index} contains duplicate values.")
        if set(normalized_official).intersection(normalized_excluded):
            raise ValueError(f"Brand registry entry {index} overlaps official and excluded domains.")
        if set(normalized_official).intersection(seen_excluded_domains) or set(normalized_excluded).intersection(
            seen_domains
        ):
            raise ValueError("Brand registry overlaps official and excluded domains.")
        if set(normalized_excluded).intersection(seen_excluded_domains):
            raise ValueError(f"Brand registry entry {index} contains duplicate excluded domains.")
        brand_key = brand.casefold()
        if brand_key in seen_brands:
            raise ValueError(f"Brand registry entry {index} duplicates a brand.")
        seen_brands.add(brand_key)
        aliases_by_canonical = {_canonical(alias): alias for alias in aliases}
        normalized_fuzzy: list[str] = []
        seen_fuzzy: set[str] = set()
        for fuzzy_alias in fuzzy_aliases:
            canonical_fuzzy = _canonical(fuzzy_alias)
            fuzzy_parts = [
                part for item in re.split(r"[\s._-]+", fuzzy_alias) if (part := _canonical(item))
            ]
            if (
                canonical_fuzzy not in aliases_by_canonical
                or canonical_fuzzy in seen_fuzzy
                or len(fuzzy_parts) != 1
                or len(canonical_fuzzy) < 5
            ):
                raise ValueError(f"Brand registry entry {index} has an invalid fuzzy alias.")
            seen_fuzzy.add(canonical_fuzzy)
            normalized_fuzzy.append(fuzzy_alias.strip())
        for source in sources:
            parsed_source = urlsplit(source)
            if parsed_source.scheme != "https" or not parsed_source.hostname or parsed_source.username is not None:
                raise ValueError(f"Brand registry entry {index} has an unsafe source URL.")
        for alias in aliases:
            canonical_alias = _canonical(alias)
            owner = seen_aliases.get(canonical_alias)
            if not canonical_alias or (owner is not None and owner != brand):
                raise ValueError(f"Brand registry alias {alias!r} is ambiguous.")
            seen_aliases[canonical_alias] = brand
        for domain in normalized_official:
            owner = seen_domains.get(domain)
            if owner is not None:
                raise ValueError(f"Official domain {domain!r} belongs to multiple entries.")
            seen_domains[domain] = brand
        seen_excluded_domains.update(normalized_excluded)
        entries.append(
            BrandEntry(
                brand=brand,
                last_reviewed_at=last_reviewed_at,
                aliases=aliases,
                fuzzy_aliases=normalized_fuzzy,
                excluded_terms=excluded_terms,
                excluded_domains=normalized_excluded,
                category=raw["category"].strip(),
                official_domains=normalized_official,
                sources=sources,
            )
        )
    return BrandRegistry(scope=scope, reviewed_at=reviewed_at, entries=entries)


def _canonical(value: str) -> str:
    translated = _uts39_skeleton(unicodedata.normalize("NFKD", value).casefold())
    return "".join(
        character
        for character in translated
        if not unicodedata.combining(character) and character.isascii() and character.isalnum()
    )


def _host_canonical(value: str) -> str:
    """Keep unmapped host characters as mismatches instead of deleting them."""
    return "".join(
        _canonical(character) or ("" if unicodedata.combining(character) else character)
        for character in value
    )


def _ascii_confusable(value: str) -> str | None:
    candidates = confusables.confusables_data.get(value, [])
    ascii_candidates = sorted(
        {
            candidate["c"].casefold()
            for candidate in candidates
            if isinstance(candidate, dict)
            and isinstance(candidate.get("c"), str)
            and candidate["c"].isascii()
            and candidate["c"].isalnum()
        },
        key=lambda candidate: (len(candidate), candidate),
    )
    return ascii_candidates[0] if ascii_candidates else None


def _uts39_skeleton(value: str) -> str:
    """Return an internal comparison skeleton derived from pinned UTS #39 data.

    Skeletons are deliberately never included in public output. They are an
    inexact comparison aid and cannot make a maliciousness determination.
    """

    pieces: list[str] = []
    for character in unicodedata.normalize("NFD", value.casefold()):
        if unicodedata.combining(character):
            continue
        if character.isascii():
            pieces.append(character)
            continue
        pieces.append(_ascii_confusable(character) or character)
    return unicodedata.normalize("NFD", "".join(pieces))


def _canonical_with_origins(value: str) -> tuple[str, tuple[int, ...]]:
    """Return a comparison skeleton and the source index for each character.

    The origin map lets Unicode evidence prove that a non-ASCII code point
    contributed to the alias span. Non-ASCII decoration elsewhere in an IDN
    must not turn an unchanged ASCII alias into a confusable match.
    """

    pieces: list[str] = []
    origins: list[int] = []
    for source_index, character in enumerate(value):
        skeleton = _uts39_skeleton(unicodedata.normalize("NFKD", character).casefold())
        canonical = "".join(
            candidate
            for candidate in skeleton
            if not unicodedata.combining(candidate) and candidate.isascii() and candidate.isalnum()
        )
        pieces.append(canonical)
        origins.extend([source_index] * len(canonical))
    combined = "".join(pieces)
    expected = _canonical(value)
    if combined != expected:
        # Be conservative if a future Unicode normalization rule introduces a
        # cross-code-point mapping that cannot be attributed precisely.
        return expected, ()
    return combined, tuple(origins)


def _unicode_evidence(
    label: str,
    alias: str,
    *,
    affix: str | None = None,
    fold_label: bool = False,
) -> frozenset[str]:
    if label.isascii():
        return frozenset()
    label_skeleton, origins = _canonical_with_origins(label)
    alias_skeleton = _canonical(alias)
    if not alias_skeleton or len(origins) != len(label_skeleton):
        return frozenset()

    canonical_parts = [part for item in label.split("-") if (part := _canonical(item))]
    part_offsets = [0]
    for part in canonical_parts:
        part_offsets.append(part_offsets[-1] + len(part))

    eligible_spans: list[tuple[int, int]] = []
    if affix is None:
        alias_parts = [part for item in re.split(r"[\s._-]+", alias) if (part := _canonical(item))]
        for index in range(len(canonical_parts) - len(alias_parts) + 1):
            if canonical_parts[index : index + len(alias_parts)] == alias_parts:
                eligible_spans.append((part_offsets[index], part_offsets[index + len(alias_parts)]))
    elif fold_label:
        compact = "".join(canonical_parts)
        if compact == alias_skeleton + affix:
            eligible_spans.append((0, len(alias_skeleton)))
        elif compact == affix + alias_skeleton:
            eligible_spans.append((len(affix), len(compact)))
    else:
        for index, part in enumerate(canonical_parts):
            if part == alias_skeleton + affix:
                eligible_spans.append((part_offsets[index], part_offsets[index] + len(alias_skeleton)))
            elif part == affix + alias_skeleton:
                eligible_spans.append((part_offsets[index] + len(affix), part_offsets[index + 1]))

    evidence: set[str] = set()
    for match_start, match_end in eligible_spans:
        source_indices = set(origins[match_start:match_end])
        if source_indices and any(not label[index].isascii() for index in source_indices):
            matched_span = "".join(label[index] for index in sorted(source_indices))
            scripts = categories.unique_aliases(matched_span) - IGNORED_SCRIPT_ALIASES
            evidence.add("unicode-confusable")
            if len(scripts) > 1:
                evidence.add("mixed-script")
            if len(scripts) > 1 or scripts != {"LATIN"}:
                evidence.add("restricted-identifier")

    return frozenset(evidence)


def _edit_distance(left: str, right: str) -> int:
    """Return restricted Damerau-Levenshtein distance for short DNS tokens."""
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 2:
        return 3
    previous_previous: list[int] | None = None
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            distance = min(
                current[right_index - 1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + (left_character != right_character),
            )
            if (
                previous_previous is not None
                and left_index > 1
                and right_index > 1
                and left_character == right[right_index - 2]
                and left[left_index - 2] == right_character
            ):
                distance = min(distance, previous_previous[right_index - 2] + 1)
            current.append(distance)
        previous_previous = previous
        previous = current
    return previous[-1]


def _is_official(domain: str, official_domains: set[str]) -> bool:
    return any(domain == official or domain.endswith(f".{official}") for official in official_domains)


def is_suppressed_domain(value: str, registry: BrandRegistry) -> bool:
    domain = normalize_domain(value)
    if not domain:
        return True
    reviewed = {
        candidate
        for entry in registry.entries
        for candidate in [*entry.official_domains, *entry.excluded_domains]
    }
    return _is_official(domain, reviewed) or _is_official(domain, KNOWN_CT_REWRITE_SUFFIXES)


def is_brand_collision(value: str, brand: str, registry: BrandRegistry) -> bool:
    """Return true when a reviewed exclusion contradicts a proposed brand mapping."""
    domain = normalize_domain(value)
    entry = next((candidate for candidate in registry.entries if candidate.brand == brand), None)
    if not domain or entry is None:
        return True
    grouped_parts = _label_parts(domain)
    candidate_parts = {part for group in grouped_parts for part in group}
    candidate_parts.update("".join(group) for group in grouped_parts)
    excluded = {_canonical(term) for term in entry.excluded_terms}
    return bool(excluded.intersection(candidate_parts))


def _registrable_domain(domain: str) -> str:
    extracted = EXTRACT(domain)
    if not extracted.suffix:
        return domain
    return f"{extracted.domain}.{extracted.suffix}"


def _alias_parts(value: str) -> list[str]:
    return [part for item in re.split(r"[\s._-]+", value) if (part := _canonical(item))]


def _label_groups(domain: str) -> list[tuple[list[str], bool, str]]:
    labels = domain.split(".")
    suffix = EXTRACT(domain).suffix
    suffix_labels = len(suffix.split(".")) if suffix else 1
    meaningful_labels = labels[:-suffix_labels] if len(labels) > suffix_labels else labels
    groups: list[tuple[list[str], bool, str]] = []
    for label in meaningful_labels:
        try:
            decoded_label = idna.decode(label, uts46=True, std3_rules=True)
        except idna.IDNAError:
            decoded_label = label
        parts = [part for item in decoded_label.split("-") if (part := _host_canonical(item))]
        groups.append((parts, label.startswith("xn--"), decoded_label))
    return groups


def _label_parts(domain: str) -> list[list[str]]:
    return [parts for parts, _, _ in _label_groups(domain)]


def _domain_hyphen_count(domain: str) -> int:
    return idna.decode(domain, uts46=True, std3_rules=True).count("-")


def _contains_sequence(parts: list[str], sequence: list[str]) -> bool:
    if not sequence or len(sequence) > len(parts):
        return False
    return any(parts[index : index + len(sequence)] == sequence for index in range(len(parts) - len(sequence) + 1))


def _context_words(parts: list[str], alias_parts: set[str]) -> list[str]:
    return [part for part in parts if part in SUSPICIOUS_WORDS and part not in alias_parts]


def _suspicious_affix(token: str, alias: str) -> str | None:
    if token.startswith(alias) and token != alias:
        suffix = token[len(alias) :]
        if suffix in SUSPICIOUS_WORDS:
            return suffix
    if token.endswith(alias) and token != alias:
        prefix = token[: -len(alias)]
        if prefix in SUSPICIOUS_WORDS:
            return prefix
    return None


def resolve_brand_name(value: str | None, registry: BrandRegistry) -> str | None:
    if not value or not (candidate := _canonical(value)):
        return None
    for entry in registry.entries:
        names = [entry.brand, *entry.aliases]
        if any(_canonical(name) == candidate for name in names):
            return entry.brand
    return None


def match_brand_text(value: str | None, registry: BrandRegistry) -> str | None:
    if not value:
        return None
    tokens = [part for item in re.split(r"[^\w]+", value) if (part := _canonical(item))]
    matches: list[tuple[int, str]] = []
    for entry in registry.entries:
        for alias in entry.aliases:
            parts = _alias_parts(alias)
            compact = "".join(parts)
            if len(compact) >= 5 and _contains_sequence(tokens, parts):
                matches.append((len(compact), entry.brand))
    matched_brands = {brand for _, brand in matches}
    if len(matched_brands) != 1:
        return None
    return matched_brands.pop()


def _score_domain_matches(value: str, registry: BrandRegistry) -> list[CandidateMatch]:
    domain = normalize_domain(value)
    if not domain:
        return []
    if is_suppressed_domain(domain, registry):
        return []

    registrable_domain = _registrable_domain(domain)
    label_groups = _label_groups(domain)
    grouped_parts = [parts for parts, _, _ in label_groups]
    punycode_labels = [is_punycode for _, is_punycode, _ in label_groups]
    decoded_labels = [decoded for _, _, decoded in label_groups]
    canonical_parts = [part for group in grouped_parts for part in group]
    label_compacts = ["".join(group) for group in grouped_parts]
    matches: list[CandidateMatch] = []

    for entry in registry.entries:
        excluded = {_canonical(term) for term in entry.excluded_terms}
        fuzzy_aliases = {_canonical(alias) for alias in entry.fuzzy_aliases}
        if excluded.intersection(canonical_parts) or excluded.intersection(label_compacts):
            continue
        base = 0
        match_reason = ""
        attached_context: list[str] = []
        matched_punycode = False
        matched_unicode_evidence: set[str] = set()
        for raw_alias in entry.aliases:
            alias_parts = _alias_parts(raw_alias)
            alias = "".join(alias_parts)
            if not alias or not alias_parts:
                continue
            exact_groups = [
                index for index, group in enumerate(grouped_parts) if _contains_sequence(group, alias_parts)
            ]
            exact_context_by_group = {
                index: _context_words(grouped_parts[index], set(alias_parts)) for index in exact_groups
            }
            unicode_evidence_by_group = {
                index: _unicode_evidence(decoded_labels[index], raw_alias) for index in exact_groups
            }
            qualifying_exact_groups = [
                index
                for index in exact_groups
                if exact_context_by_group[index]
                or "unicode-confusable" in unicode_evidence_by_group[index]
            ]
            if len(alias) <= SHORT_ALIAS_MAXIMUM_LENGTH:
                # Short aliases are collision-prone. Keep boundary-delimited
                # candidates eligible for the CertStream threshold, but only
                # with same-label context or a real in-span Unicode substitution.
                if qualifying_exact_groups and base < 70:
                    base = 70
                    match_reason = f"exact short brand token: {raw_alias}"
                    attached_context = list(
                        dict.fromkeys(
                            word
                            for index in qualifying_exact_groups
                            for word in exact_context_by_group[index]
                        )
                    )
                    matched_punycode = any(punycode_labels[index] for index in qualifying_exact_groups)
                    matched_unicode_evidence = {
                        code
                        for index in qualifying_exact_groups
                        for code in unicode_evidence_by_group[index]
                    }
                continue
            if qualifying_exact_groups:
                exact_context = list(
                    dict.fromkeys(
                        word
                        for index in qualifying_exact_groups
                        for word in exact_context_by_group[index]
                    )
                )
                if base < 80:
                    base = 80
                    match_reason = f"brand text match: {raw_alias}"
                    attached_context = exact_context
                    matched_punycode = any(punycode_labels[index] for index in qualifying_exact_groups)
                    matched_unicode_evidence = {
                        code
                        for index in qualifying_exact_groups
                        for code in unicode_evidence_by_group[index]
                    }
                continue

            affix = next(
                (
                    (context, index)
                    for index, group in enumerate(grouped_parts)
                    for token in group
                    if (context := _suspicious_affix(token, alias)) is not None
                ),
                None,
            )
            if len(alias) > SHORT_ALIAS_MAXIMUM_LENGTH and affix is not None and base < 78:
                context, group_index = affix
                base = 78
                match_reason = f"brand text with suspicious affix: {raw_alias}"
                attached_context = [context]
                matched_punycode = punycode_labels[group_index]
                matched_unicode_evidence = set(
                    _unicode_evidence(decoded_labels[group_index], raw_alias, affix=context)
                )

            # Attackers frequently split a brand across hyphen-delimited pieces.
            # Fold only one DNS label and require the remaining prefix or suffix
            # to be exactly one reviewed threat word. This is intentionally not
            # a general substring or caller-supplied regular-expression match.
            split_affix = next(
                (
                    (context, index)
                    for index, group in enumerate(grouped_parts)
                    if len(group) >= 2
                    and (context := _suspicious_affix("".join(group), alias)) is not None
                ),
                None,
            )
            if len(alias) > SHORT_ALIAS_MAXIMUM_LENGTH and split_affix is not None and base < 78:
                context, group_index = split_affix
                base = 78
                match_reason = f"brand text split across label: {raw_alias}"
                attached_context = [context]
                matched_punycode = punycode_labels[group_index]
                matched_unicode_evidence = set(
                    _unicode_evidence(
                        decoded_labels[group_index],
                        raw_alias,
                        affix=context,
                        fold_label=True,
                    )
                )

            # Fuzzy evidence is intentionally narrow: one edit (including one
            # adjacent transposition) in a single-word alias, plus a threat word
            # in the same DNS label. Punycode alone is never fuzzy context.
            if _canonical(raw_alias) not in fuzzy_aliases or len(alias_parts) != 1 or len(alias) < 5:
                continue
            for group_index, group in enumerate(grouped_parts):
                fuzzy_context = _context_words(group, set(alias_parts))
                if not fuzzy_context:
                    continue
                alias_digits = "".join(character for character in alias if character.isdigit())
                fuzzy_parts = [
                    part
                    for part in group
                    if part not in SUSPICIOUS_WORDS
                    and part.isascii()
                    and (
                        not alias_digits
                        or "".join(character for character in part if character.isdigit()) == alias_digits
                    )
                ]
                closest = min(
                    (_edit_distance(alias, part) for part in fuzzy_parts),
                    default=3,
                )
                if closest == 1 and base < 68:
                    base = 68
                    match_reason = f"brand lookalike (edit distance {closest}): {raw_alias}"
                    attached_context = fuzzy_context
                    matched_punycode = punycode_labels[group_index]
                    matched_unicode_evidence = set()
        if base == 0:
            continue

        confidence = base
        reasons = [match_reason]
        effective_suspicious = list(dict.fromkeys(attached_context))
        if effective_suspicious:
            confidence += 15
            reasons.append(f"suspicious token: {', '.join(effective_suspicious)}")
        if matched_punycode:
            confidence += 10
            reasons.append("internationalized domain (punycode)")
        for code, explanation in (
            ("unicode-confusable", "Unicode confusable skeleton matched a reviewed alias"),
            ("mixed-script", "mixed-script identifier"),
            ("restricted-identifier", "restricted identifier profile"),
        ):
            if code in matched_unicode_evidence:
                reasons.append(explanation)
        official_tlds = {official.rsplit(".", 1)[-1] for official in entry.official_domains}
        if registrable_domain.rsplit(".", 1)[-1] not in official_tlds:
            confidence += 5
            reasons.append("different top-level domain from registry")
        if _domain_hyphen_count(domain) >= 2:
            confidence += 5
            reasons.append("multiple hyphens")

        result = CandidateMatch(
            domain=domain,
            registrable_domain=registrable_domain,
            brand=entry.brand,
            confidence=min(100, confidence),
            reasons=reasons,
        )
        matches.append(result)
    return matches


def _idn_visual_enabled() -> bool:
    return os.environ.get("HECAVEX_IDN_VISUAL_MATCHING", "true").strip().lower() != "false"


def _visual_equivalence(
    value: str,
    target: str,
    source_offset: int,
    alias_start: int,
    alias_end: int,
    *,
    fold_hyphens: bool = False,
) -> list[dict[str, object]] | None:
    """Compare to one reviewed alias without generating domain permutations."""
    position = 0
    substitutions: list[dict[str, object]] = []
    for index, character in enumerate(value):
        if character == "-" and fold_hyphens:
            continue
        inside_alias = alias_start <= position < alias_end
        choices = (
            IDN_VISUAL_REPLACEMENTS[character]
            if inside_alias and character in IDN_VISUAL_REPLACEMENTS
            else (_host_canonical(character),)
        )
        replacement = next((item for item in choices if target.startswith(item, position)), None)
        if replacement is None:
            return None
        if inside_alias and character in IDN_VISUAL_REPLACEMENTS:
            substitutions.append(
                {"position": source_offset + index, "codePoint": f"U+{ord(character):04X}",
                 "replacement": replacement}
            )
        position += len(replacement)
    return substitutions if position == len(target) and substitutions else None


def _curated_idn_matches(
    value: str, registry: BrandRegistry,
) -> list[tuple[CandidateMatch, dict[str, object]]]:
    if not _idn_visual_enabled() or (domain := normalize_domain(value)) is None:
        return []
    if not any(label.startswith("xn--") for label in domain.split(".")):
        return []
    if is_suppressed_domain(domain, registry):
        return []
    label_groups = _label_groups(domain)
    grouped_parts = [parts for parts, _, _ in label_groups]
    candidate_parts = {part for group in grouped_parts for part in group}
    candidate_parts.update("".join(group) for group in grouped_parts)
    registrable_domain = _registrable_domain(domain)
    decoded_hyphens = sum(label.count("-") for _, _, label in label_groups)
    results: list[tuple[CandidateMatch, dict[str, object]]] = []
    for entry in registry.entries:
        if {_canonical(term) for term in entry.excluded_terms}.intersection(candidate_parts):
            continue
        for label_index, (parts, _, label) in enumerate(label_groups):
            if not any(character in IDN_VISUAL_REPLACEMENTS for character in label):
                continue
            tokens = list(re.finditer(r"[^-]+", label))
            for raw_alias in entry.aliases:
                alias_parts = _alias_parts(raw_alias)
                alias = "".join(alias_parts)
                if not alias:
                    continue
                options: list[tuple[str, int, str, int, int, list[str], bool]] = []
                context = _context_words(parts, set(alias_parts))
                for start in range(len(tokens) - len(alias_parts) + 1):
                    first, last = tokens[start], tokens[start + len(alias_parts) - 1]
                    fragment = label[first.start() : last.end()]
                    options.append((fragment, first.start(), alias, 0, len(alias), context, True))
                if len(alias) > SHORT_ALIAS_MAXIMUM_LENGTH:
                    fragments = [(match.group(), match.start(), False) for match in tokens]
                    if len(tokens) > 1:
                        fragments.append((label, 0, True))
                    for fragment, offset, fold_hyphens in fragments:
                        compact = _host_canonical(fragment)
                        if fold_hyphens:
                            compact = compact.replace("-", "")
                        for word in sorted(SUSPICIOUS_WORDS - set(alias_parts)):
                            if len(compact) != len(alias) + len(word):
                                continue
                            options.append((fragment, offset, alias + word, 0, len(alias), [word], fold_hyphens))
                            options.append((fragment, offset, word + alias, len(word), len(word + alias),
                                            [word], fold_hyphens))
                for fragment, offset, target, alias_start, alias_end, context, fold in options:
                    substitutions = _visual_equivalence(
                        fragment, target, offset, alias_start, alias_end, fold_hyphens=fold,
                    )
                    if substitutions is None:
                        continue
                    score = 70 if len(alias) <= SHORT_ALIAS_MAXIMUM_LENGTH else 80
                    reasons = [f"curated IDN visual match: {raw_alias}", "internationalized domain (punycode)"]
                    score += 10
                    if context:
                        score += 15
                        reasons.append(f"suspicious token: {', '.join(dict.fromkeys(context))}")
                    if registrable_domain.rsplit(".", 1)[-1] not in {
                        official.rsplit(".", 1)[-1] for official in entry.official_domains
                    }:
                        score += 5
                        reasons.append("different top-level domain from registry")
                    if decoded_hyphens >= 2:
                        score += 5
                        reasons.append("multiple hyphens")
                    match = CandidateMatch(domain, registrable_domain, entry.brand, min(100, score), reasons)
                    evidence: dict[str, object] = {
                        "brand": entry.brand, "alias": raw_alias, "matchedLabel": label,
                        "labelIndex": label_index,
                        "labelRole": "registrable" if label_index == len(label_groups) - 1 else "subdomain",
                        "substitutions": substitutions,
                    }
                    results.append((match, evidence))
    return results


def _combined_domain_matches(
    value: str,
    registry: BrandRegistry,
    curated: list[tuple[CandidateMatch, dict[str, object]]] | None = None,
) -> list[CandidateMatch]:
    # Existing valid matches retain their established score and provenance.
    matches = {match.brand: match for match in _score_domain_matches(value, registry)}
    if curated is None:
        curated = _curated_idn_matches(value, registry)
    for match, _ in sorted(curated, key=lambda item: -item[0].confidence):
        matches.setdefault(match.brand, match)
    return list(matches.values())


def idn_match_evidence(value: str, registry: BrandRegistry) -> dict[str, object] | None:
    """Return the winning curated trace using the same admission and rollback rules."""
    curated = _curated_idn_matches(value, registry)
    if not curated:
        return None
    matches = _combined_domain_matches(value, registry, curated)
    if len(matches) != 1 or not any(reason.startswith("curated IDN visual match:") for reason in matches[0].reasons):
        return None
    candidates = [item for item in curated if item[0].brand == matches[0].brand]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0].confidence, int(str(item[1]["labelIndex"])), str(item[1]["alias"])))
    return candidates[0][1]


def domain_match_brands(value: str, registry: BrandRegistry) -> frozenset[str]:
    """Return every independently matching brand before ambiguity is rejected."""
    return frozenset(match.brand for match in _combined_domain_matches(value, registry))


def score_domain(value: str, registry: BrandRegistry) -> CandidateMatch | None:
    matches = _combined_domain_matches(value, registry)
    return matches[0] if len(matches) == 1 else None
