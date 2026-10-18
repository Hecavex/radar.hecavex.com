from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .brands import normalize_domain
from .safety import clean_text, defang_domains_in_text, defang_host

MAXIMUM_MESSAGE_DOMAINS = 500
MAXIMUM_CERTIFICATE_SAN_SAMPLES = 12
MAXIMUM_CERTIFICATE_TEXT = 512
MAXIMUM_PUBLIC_ISSUER = 200
MAXIMUM_COMMON_NAME = 253
MAXIMUM_SERIAL_HEX = 80
HEX = re.compile(r"^[0-9a-f]+$")
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[a-z\d.-]{1,253}", re.IGNORECASE)
SCHEME = re.compile(r"\bhttps?://", re.IGNORECASE)
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


@dataclass(frozen=True, slots=True)
class CertificateEvidence:
    """Small allowlisted subset of an untrusted CertStream leaf certificate."""

    country_name: str | None
    issuer: str | None
    common_name: str | None
    not_before: str | None
    not_after: str | None
    subject_alt_names: tuple[str, ...]
    serial_number_hex: str | None
    md5: str | None
    sha1: str | None
    sha256: str | None


@dataclass(frozen=True, slots=True)
class ParsedCertStreamMessage:
    domains: tuple[str, ...]
    certificate: CertificateEvidence | None


def _bounded_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum or not normalized.isprintable():
        return None
    return normalized


def public_certificate_text(value: object, maximum: int = MAXIMUM_PUBLIC_ISSUER) -> str | None:
    """Return idempotent, bounded public text with live indicators neutralized."""

    text = clean_text(value, maximum * 2)
    if not text:
        return None
    text = EMAIL.sub("[email redacted]", text).replace("@", "[at]")
    text = SCHEME.sub(lambda match: "hxxps://" if match.group(0).lower().startswith("https") else "hxxp://", text)
    text = IPV4.sub(_defang_ipv4, text)
    return clean_text(defang_domains_in_text(text), maximum)


def _defang_ipv4(match: re.Match[str]) -> str:
    try:
        return defang_host(str(ipaddress.ip_address(match.group(0))))
    except ValueError:
        return match.group(0)


def _mapping_text(value: object, *keys: str, maximum: int = MAXIMUM_CERTIFICATE_TEXT) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        candidate = _bounded_text(value.get(key), maximum)
        if candidate is not None:
            return candidate
    return None


def _issuer(value: object) -> str | None:
    direct = _bounded_text(value, MAXIMUM_CERTIFICATE_TEXT)
    if direct is not None:
        return direct
    aggregated = _mapping_text(value, "aggregated", "name")
    if aggregated is not None:
        return aggregated
    organization = _mapping_text(value, "O", "organizationName", "organization", maximum=256)
    common_name = _mapping_text(value, "CN", "commonName", "common_name", maximum=MAXIMUM_COMMON_NAME)
    parts = [
        label
        for label in (
            f"O={organization}" if organization else None,
            f"CN={common_name}" if common_name else None,
        )
        if label
    ]
    return ", ".join(parts) or None


def _utc_milliseconds_from_epoch(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    try:
        epoch = float(value) if isinstance(value, (int, float, str)) else None
    except ValueError:
        return None
    if epoch is None or not 0 <= epoch <= 10_413_792_000_000:
        return None
    # CertStream normally uses epoch seconds. Tolerate milliseconds without
    # accepting microsecond/nanosecond values from an unexpected payload.
    if epoch >= 100_000_000_000:
        epoch /= 1_000
    try:
        parsed = datetime.fromtimestamp(epoch, UTC)
    except (OverflowError, OSError, ValueError):
        return None
    if not 1970 <= parsed.year <= 2300:
        return None
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hex(value: object, *, exact_length: int | None = None, maximum: int = MAXIMUM_SERIAL_HEX) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        candidate = format(value, "x") if value >= 0 else ""
    elif isinstance(value, str):
        candidate = value.strip().lower().removeprefix("0x").replace(":", "").replace(" ", "")
    else:
        return None
    if not candidate or len(candidate) > maximum or not HEX.fullmatch(candidate):
        return None
    if exact_length is not None and len(candidate) != exact_length:
        return None
    return candidate


def _fingerprint(leaf: dict[str, Any], algorithm: str, length: int) -> str | None:
    nested = leaf.get("fingerprints")
    candidates: list[object] = []
    if isinstance(nested, dict):
        candidates.extend((nested.get(algorithm), nested.get(algorithm.upper())))
    candidates.extend(
        (
            leaf.get(algorithm),
            leaf.get(f"{algorithm}_fingerprint"),
            leaf.get(f"fingerprint_{algorithm}"),
        )
    )
    if algorithm == "sha1":
        # The original CertStream schema calls its SHA-1 value `fingerprint`.
        candidates.append(leaf.get("fingerprint"))
    return next((normalized for value in candidates if (normalized := _hex(value, exact_length=length))), None)


def _domains(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    domains: list[str] = []
    for item in value[:MAXIMUM_MESSAGE_DOMAINS]:
        if isinstance(item, str):
            domains.append(item)
    return tuple(domains)


def _certificate_from_leaf(leaf: object) -> CertificateEvidence | None:
    if not isinstance(leaf, dict):
        return None
    subject = leaf.get("subject")
    country_name = _mapping_text(subject, "C", "countryName", "country_name", maximum=64)
    if country_name is not None and len(country_name) == 2 and country_name.isascii() and country_name.isalpha():
        country_name = country_name.upper()
    else:
        country_name = None
    common_name = _mapping_text(subject, "CN", "commonName", "common_name", maximum=MAXIMUM_COMMON_NAME)
    alt_names = tuple(
        dict.fromkeys(
            domain
            for item in _domains(leaf.get("all_domains"))
            if (domain := normalize_domain(item)) is not None
        )
    )
    evidence = CertificateEvidence(
        country_name=country_name,
        issuer=_issuer(leaf.get("issuer")),
        common_name=common_name,
        not_before=_utc_milliseconds_from_epoch(leaf.get("not_before")),
        not_after=_utc_milliseconds_from_epoch(leaf.get("not_after")),
        subject_alt_names=alt_names,
        serial_number_hex=_hex(leaf.get("serial_number")),
        md5=_fingerprint(leaf, "md5", 32),
        sha1=_fingerprint(leaf, "sha1", 40),
        sha256=_fingerprint(leaf, "sha256", 64),
    )
    if not any(
        (
            evidence.country_name,
            evidence.issuer,
            evidence.common_name,
            evidence.not_before,
            evidence.not_after,
            evidence.subject_alt_names,
            evidence.serial_number_hex,
            evidence.md5,
            evidence.sha1,
            evidence.sha256,
        )
    ):
        return None
    return evidence


def parse_message(value: Any) -> ParsedCertStreamMessage:
    if not isinstance(value, dict):
        return ParsedCertStreamMessage((), None)
    if value.get("message_type") == "dns_entries":
        return ParsedCertStreamMessage(_domains(value.get("data")), None)
    data = value.get("data")
    if value.get("message_type") != "certificate_update" or not isinstance(data, dict):
        return ParsedCertStreamMessage((), None)
    leaf = data.get("leaf_cert")
    candidates: object = leaf.get("all_domains") if isinstance(leaf, dict) else None
    if not isinstance(candidates, list):
        candidates = data.get("dns_entries")
    return ParsedCertStreamMessage(_domains(candidates), _certificate_from_leaf(leaf))


def certificate_for_domain(
    certificate: CertificateEvidence | None,
    registrable_domain: str,
) -> dict[str, object] | None:
    if certificate is None:
        return None
    root = normalize_domain(registrable_domain)
    if root is None:
        return None
    related = sorted(
        domain
        for domain in certificate.subject_alt_names
        if domain == root or domain.endswith(f".{root}")
    )
    common_name = certificate.common_name
    if common_name is not None and (normalized_common_name := normalize_domain(common_name)) is not None:
        wildcard = common_name.strip().startswith("*.")
        common_name = (
            f"*[.]{defang_host(normalized_common_name)}" if wildcard else defang_host(normalized_common_name)
        )
    else:
        common_name = None
    fingerprints = {
        "md5": certificate.md5,
        "sha1": certificate.sha1,
        "sha256": certificate.sha256,
    }
    payload: dict[str, object] = {
        "countryName": certificate.country_name,
        "issuer": public_certificate_text(certificate.issuer),
        "commonName": common_name,
        "notBefore": certificate.not_before,
        "notAfter": certificate.not_after,
        "subjectAltNames": [defang_host(domain) for domain in related[:MAXIMUM_CERTIFICATE_SAN_SAMPLES]],
        "subjectAltNameCount": len(related),
        "serialNumberHex": certificate.serial_number_hex,
        "fingerprints": fingerprints,
    }
    has_content = any(
        payload[field] is not None
        for field in ("countryName", "issuer", "commonName", "notBefore", "notAfter", "serialNumberHex")
    ) or bool(payload["subjectAltNames"]) or any(value is not None for value in fingerprints.values())
    return payload if has_content else None


