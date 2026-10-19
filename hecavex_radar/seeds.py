from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from http.client import HTTPMessage
from typing import IO, cast
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .brands import (
    BrandRegistry,
    _canonical,
    is_suppressed_domain,
    normalize_domain,
    score_domain,
)
from .safety import refang, safe_feed_url

MAXIMUM_DOWNLOAD_BYTES = 100 * 1024 * 1024
MAXIMUM_FEED_RECORDS = 500_000
ASCII_DOMAIN_CHARACTERS = "abcdefghijklmnopqrstuvwxyz0123456789"

PHISHDESTROY_URL = (
    "https://raw.githubusercontent.com/phishdestroy/destroylist/"
    "refs/heads/main/rootlist/formats/primary_active/domains.txt"
)
CERTPL_URL = "https://hole.cert.pl/domains/v2/domains.txt"
PHISHING_DATABASE_URL = (
    "https://raw.githubusercontent.com/Phishing-Database/Phishing.Database/"
    "master/phishing-domains-ACTIVE.txt"
)
# GPL-3.0 data: matched in memory as a transient hint, never copied into data/ or published.
HAGEZI_NRD_URL = "https://raw.githubusercontent.com/hagezi/nrd/main/domains/nrd7.txt"
# Seven days of newly registered domains is ~3.6M rows; other feeds keep the default limit.
MAXIMUM_NRD_RECORDS = 6_000_000

BytesFetcher = Callable[[str, dict[str, str], tuple[str, ...]], bytes]


@dataclass(frozen=True, slots=True)
class SeedObservation:
    indicator: str


@dataclass(frozen=True, slots=True)
class IntelligenceSeed:
    domain: str
    brand: str
    confidence: int


@dataclass(frozen=True, slots=True)
class SeedLoadResult:
    seeds: list[IntelligenceSeed]
    configured: int
    completed: int
    failed: int


@dataclass(frozen=True, slots=True)
class _BrandPrefilter:
    alias_pattern: re.Pattern[str] | None
    fuzzy_variants: frozenset[str]


class _AllowlistedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: tuple[str, ...]) -> None:
        self._allowed_hosts = allowed_hosts
        super().__init__()

    def redirect_request(
        self,
        request: Request,
        file_pointer: IO[bytes],
        code: int,
        message: str,
        headers: HTTPMessage,
        new_url: str,
    ) -> Request | None:
        destination = urlsplit(urljoin(request.full_url, new_url))
        hostname = (destination.hostname or "").lower()
        if (
            code not in {301, 302, 303, 307, 308}
            or destination.scheme != "https"
            or hostname not in self._allowed_hosts
            or destination.username is not None
            or destination.password is not None
            or destination.port is not None
        ):
            raise HTTPError(request.full_url, code, "Seed feed returned an unapproved redirect.", headers, file_pointer)
        return super().redirect_request(request, file_pointer, code, message, headers, destination.geturl())


def _fetch_bytes(url: str, headers: dict[str, str], allowed_hosts: tuple[str, ...]) -> bytes:
    safe_url = safe_feed_url(url)
    parsed = urlsplit(safe_url)
    if (
        not parsed.hostname
        or parsed.hostname.lower() not in allowed_hosts
        or parsed.port is not None
    ):
        raise ValueError("Seed feed URL is outside its fixed HTTPS host allow-list.")
    request = Request(safe_url, headers=headers, method="GET")  # noqa: S310 - exact HTTPS hosts are enforced above
    opener = build_opener(_AllowlistedRedirectHandler(allowed_hosts))
    try:
        with opener.open(request, timeout=45) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAXIMUM_DOWNLOAD_BYTES:
                raise ValueError("Seed feed exceeds the download limit.")
            body = cast(bytes, response.read(MAXIMUM_DOWNLOAD_BYTES + 1))
    except HTTPError as error:
        raise ValueError(f"Seed feed request failed with HTTP {error.code}.") from error
    if len(body) > MAXIMUM_DOWNLOAD_BYTES:
        raise ValueError("Seed feed exceeds the download limit.")
    return body


def parse_text_feed(body: bytes, maximum: int = MAXIMUM_FEED_RECORDS) -> list[SeedObservation]:
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("Seed feed returned invalid UTF-8.") from error
    observations: list[SeedObservation] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and not line.startswith(("#", "!")):
            observations.append(SeedObservation(indicator=line))
        if len(observations) >= maximum:
            break
    return observations


def _hostname(value: str) -> str | None:
    candidate = refang(value.strip())
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        hostname = urlsplit(candidate).hostname
    except ValueError:
        return None
    return normalize_domain(hostname) if hostname else None


def _one_edit_variants(value: str) -> set[str]:
    """Return ASCII DNS tokens one restricted Damerau-Levenshtein edit away."""
    variants = {value[:index] + value[index + 1 :] for index in range(len(value))}
    for index in range(len(value)):
        variants.update(
            value[:index] + character + value[index + 1 :]
            for character in ASCII_DOMAIN_CHARACTERS
            if character != value[index]
        )
    for index in range(len(value) + 1):
        variants.update(
            value[:index] + character + value[index:]
            for character in ASCII_DOMAIN_CHARACTERS
        )
    variants.update(
        value[:index] + value[index + 1] + value[index] + value[index + 2 :]
        for index in range(len(value) - 1)
        if value[index] != value[index + 1]
    )
    return variants


def _compile_brand_prefilter(registry: BrandRegistry) -> _BrandPrefilter:
    aliases = {
        canonical
        for entry in registry.entries
        for alias in entry.aliases
        if (canonical := _canonical(alias))
    }
    ordered_aliases = sorted(aliases, key=lambda alias: (-len(alias), alias))
    alias_pattern = (
        re.compile("|".join(re.escape(alias) for alias in ordered_aliases))
        if ordered_aliases
        else None
    )
    fuzzy_variants: set[str] = set()
    for entry in registry.entries:
        for alias in entry.fuzzy_aliases:
            if canonical := _canonical(alias):
                fuzzy_variants.update(
                    normalized
                    for variant in _one_edit_variants(canonical)
                    if (normalized := _canonical(variant))
                )
    return _BrandPrefilter(alias_pattern, frozenset(fuzzy_variants))


def _may_match_reviewed_brand(domain: str, prefilter: _BrandPrefilter) -> bool:
    """Cheap necessary check; ``score_domain`` remains the authoritative matcher."""
    labels = domain.split(".")
    # IDNA decoding can reveal Unicode brand text that is absent from the ASCII
    # A-label, so all punycode candidates must reach the authoritative scorer.
    if any(label.startswith("xn--") for label in labels):
        return True
    canonical_labels = [_canonical(label) for label in labels]
    if prefilter.alias_pattern and any(
        prefilter.alias_pattern.search(label) for label in canonical_labels
    ):
        return True
    return any(
        canonical in prefilter.fuzzy_variants
        for label in labels
        for part in label.split("-")
        if (canonical := _canonical(part))
    )


def _may_reach_matcher(indicator: str, prefilter: _BrandPrefilter) -> bool:
    text = indicator.strip().lower()
    # A bare ASCII hostname has the same labels before and after IDNA normalization, so the
    # cheap prefilter can reject it first; IDNA costs ~50 us per row on multi-million-row feeds.
    if text.isascii() and "/" not in text and not _may_match_reviewed_brand(text, prefilter):
        return False
    domain = _hostname(indicator)
    return domain is not None and _may_match_reviewed_brand(domain, prefilter)


def _seed_from_observation(
    observation: SeedObservation,
    registry: BrandRegistry,
    minimum_confidence: int,
    prefilter: _BrandPrefilter,
) -> IntelligenceSeed | None:
    domain = _hostname(observation.indicator)
    if (
        not domain
        or not _may_match_reviewed_brand(domain, prefilter)
        or is_suppressed_domain(domain, registry)
    ):
        return None
    lexical = score_domain(domain, registry)
    if not lexical or lexical.confidence < minimum_confidence:
        return None
    return IntelligenceSeed(
        domain=domain,
        brand=lexical.brand,
        confidence=lexical.confidence,
    )


def build_intelligence_seeds(
    observations: Iterable[SeedObservation],
    registry: BrandRegistry,
    minimum_confidence: int = 80,
    maximum: int = 250,
) -> list[IntelligenceSeed]:
    combined: dict[tuple[str, str], IntelligenceSeed] = {}
    prefilter = _compile_brand_prefilter(registry)
    for observation in observations:
        seed = _seed_from_observation(observation, registry, minimum_confidence, prefilter)
        if seed is None:
            continue
        key = (seed.domain, seed.brand)
        current = combined.get(key)
        if current is None:
            combined[key] = seed
            continue
        combined[key] = IntelligenceSeed(
            domain=seed.domain,
            brand=seed.brand,
            confidence=max(current.confidence, seed.confidence),
        )
    return sorted(
        combined.values(),
        key=lambda seed: (-seed.confidence, seed.domain, seed.brand),
    )[:maximum]


def _enabled(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() == "true"


def _bounded(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        parsed = default
    return max(minimum, min(maximum, parsed))


def load_intelligence_seeds(
    registry: BrandRegistry,
    fetcher: BytesFetcher = _fetch_bytes,
) -> SeedLoadResult:
    """Load transient discovery hints. Provider names and raw feed rows are never published."""
    minimum = _bounded(os.environ.get("INTELLIGENCE_SEED_MIN_CONFIDENCE"), 80, 70, 100)
    maximum = _bounded(os.environ.get("INTELLIGENCE_SEED_LIMIT"), 250, 0, 1_000)
    if maximum == 0:
        return SeedLoadResult([], 0, 0, 0)

    observations: list[SeedObservation] = []
    prefilter = _compile_brand_prefilter(registry)
    configured = 0
    completed = 0
    failed = 0

    def load(
        enabled: bool,
        url: str,
        headers: dict[str, str],
        hosts: tuple[str, ...],
        parser: Callable[[bytes], list[SeedObservation]],
    ) -> None:
        nonlocal configured, completed, failed
        if not enabled:
            return
        configured += 1
        try:
            # Keep only rows that can reach the matcher, so a multi-million-row feed is not held.
            observations.extend(
                observation for observation in parser(fetcher(url, headers, hosts))
                if _may_reach_matcher(observation.indicator, prefilter)
            )
            completed += 1
        except (OSError, RuntimeError, ValueError):
            failed += 1

    load(
        _enabled("PHISHDESTROY_SEED_ENABLED", default=True),
        PHISHDESTROY_URL,
        {"Accept": "text/plain", "User-Agent": "hecavex-radar/0.1"},
        ("raw.githubusercontent.com",),
        parse_text_feed,
    )
    load(
        _enabled("CERTPL_SEED_ENABLED", default=True),
        CERTPL_URL,
        {"Accept": "text/plain", "User-Agent": "hecavex-radar/0.1"},
        ("hole.cert.pl",),
        parse_text_feed,
    )
    load(
        _enabled("PHISHING_DATABASE_SEED_ENABLED", default=True),
        PHISHING_DATABASE_URL,
        {"Accept": "text/plain", "User-Agent": "hecavex-radar/0.1"},
        ("raw.githubusercontent.com",),
        parse_text_feed,
    )
    load(
        _enabled("HAGEZI_NRD_SEED_ENABLED", default=True),
        HAGEZI_NRD_URL,
        {"Accept": "text/plain", "User-Agent": "hecavex-radar/0.1"},
        ("raw.githubusercontent.com",),
        lambda body: parse_text_feed(body, MAXIMUM_NRD_RECORDS),
    )

    return SeedLoadResult(
        seeds=build_intelligence_seeds(observations, registry, minimum, maximum),
        configured=configured,
        completed=completed,
        failed=failed,
    )
