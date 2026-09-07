from __future__ import annotations

import hashlib
import ipaddress
import re
import unicodedata
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .models import SafeUrl

SCHEME = re.compile(r"^[a-z][a-z\d+.-]*://", re.IGNORECASE)
NESTED_URL = re.compile(r"(?:https?|hxxps?)://", re.IGNORECASE)
DOMAIN_IN_TEXT = re.compile(
    r"(?<![a-z\d.-])(?:[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?\.)+[a-z]{2,63}(?![a-z\d.-])",
    re.IGNORECASE,
)
HEX_TOKEN = re.compile(r"[a-f\d]{32,}", re.IGNORECASE)
TOKEN_CHARACTERS = re.compile(r"[a-z\d_-]+", re.IGNORECASE)
UUID_PATH_SEGMENT = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
PHONE_PATH_SEGMENT = re.compile(r"\+?[\d(). -]+")
PERCENT_ESCAPE = re.compile(r"%[0-9a-f]{2}", re.IGNORECASE)
MAXIMUM_PUBLIC_PATH_SEGMENT = 64
MINIMUM_TOKEN_PATH_SEGMENT = 24
MINIMUM_NUMERIC_PATH_DIGITS = 9
MAXIMUM_PATH_DECODING_PASSES = 3
SENSITIVE_PATH_KEYS = frozenset(
    {
        "account",
        "accountid",
        "accountnumber",
        "apikey",
        "auth",
        "authentication",
        "authorization",
        "authcode",
        "code",
        "email",
        "id",
        "key",
        "phone",
        "phonenumber",
        "session",
        "sessionid",
        "token",
        "accesstoken",
        "refreshtoken",
        "user",
        "userid",
    }
)
URLSCAN_REPORT_PATH = re.compile(
    r"^/result/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/?$",
    re.IGNORECASE,
)
URLSCAN_SCREENSHOT_PATH = re.compile(
    r"^/screenshots/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.png$",
    re.IGNORECASE,
)


def clean_text(value: object, maximum_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    without_controls = "".join(
        " " if (category := unicodedata.category(char)) == "Cc" else "" if category == "Cf" else char
        for char in value
    )
    cleaned = " ".join(without_controls.split()).strip()
    return cleaned[:maximum_length] if cleaned else None


def refang(value: str) -> str:
    value = re.sub(r"^hxxps:", "https:", value, flags=re.IGNORECASE)
    value = re.sub(r"^hxxp:", "http:", value, flags=re.IGNORECASE)
    return value.replace("[.]", ".").replace("[:]", ":")


def defang_host(hostname: str) -> str:
    without_brackets = hostname[1:-1] if hostname.startswith("[") and hostname.endswith("]") else hostname
    return without_brackets.replace(":", "[:]") if ":" in without_brackets else without_brackets.replace(".", "[.]")


def defang_domains_in_text(value: str) -> str:
    return DOMAIN_IN_TEXT.sub(lambda match: defang_host(match.group(0)), value)


def _sensitive_path_value(value: str) -> bool:
    if (
        "@" in value
        or len(value) > MAXIMUM_PUBLIC_PATH_SEGMENT
        or HEX_TOKEN.fullmatch(value)
        or UUID_PATH_SEGMENT.fullmatch(value)
        or PERCENT_ESCAPE.search(value)
    ):
        return True
    if PHONE_PATH_SEGMENT.fullmatch(value):
        digits = sum(character.isdigit() for character in value)
        if digits >= MINIMUM_NUMERIC_PATH_DIGITS:
            return True
    return len(value) >= MINIMUM_TOKEN_PATH_SEGMENT and bool(TOKEN_CHARACTERS.fullmatch(value))


def _sensitive_path_key(value: str) -> bool:
    return re.sub(r"[^a-z\d]", "", value.lower()) in SENSITIVE_PATH_KEYS


def _sensitive_path_segment(value: str) -> bool:
    candidates = [value]
    fields = value.split(";")
    for index, field in enumerate(fields):
        candidates.append(field)
        if "=" in field:
            key, candidate = field.split("=", 1)
            if candidate and _sensitive_path_key(key):
                return True
            candidates.append(candidate)
        elif (
            index + 1 < len(fields)
            and fields[index + 1]
            and _sensitive_path_key(field)
        ):
            return True
    return any(candidate and _sensitive_path_value(candidate) for candidate in candidates)


def _display_path(value: str) -> str:
    if not value or value == "/":
        return ""
    decoded = value[:2048]
    for _ in range(MAXIMUM_PATH_DECODING_PASSES):
        next_value = unquote(decoded, errors="replace")
        if next_value == decoded:
            break
        decoded = next_value
    nested = NESTED_URL.search(decoded)
    if nested:
        decoded = f"{decoded[: nested.start()]}embedded-url-redacted"
    segments: list[str] = []
    redact_next_value = False
    for segment in decoded.split("/"):
        segment_is_key = bool(segment) and _sensitive_path_key(segment)
        if segment and redact_next_value:
            segments.append("redacted")
        else:
            segments.append("redacted" if _sensitive_path_segment(segment) else segment)
        if segment:
            redact_next_value = segment_is_key
    defanged = defang_domains_in_text("/".join(segments))
    return quote(defanged, safe="/%:@!$&'()*+,;=-._~[]")


def _ascii_hostname(hostname: str) -> str | None:
    try:
        ipaddress.ip_address(hostname)
        return hostname.lower()
    except ValueError:
        pass
    try:
        normalized = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    return normalized if normalized and len(normalized) <= 253 else None


def parse_and_defang_url(value: str) -> SafeUrl | None:
    cleaned = clean_text(refang(value), 4096)
    if not cleaned:
        return None
    candidate = cleaned if SCHEME.match(cleaned) else f"https://{cleaned}"
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or parsed.username is not None or parsed.password is not None:
        return None
    if not parsed.hostname:
        return None
    hostname = _ascii_hostname(parsed.hostname)
    if not hostname:
        return None

    scheme = parsed.scheme.lower()
    display_scheme = "hxxps" if scheme == "https" else "hxxp"
    key_path = "" if parsed.path == "/" else quote(parsed.path[:2048], safe="/%:@!$&'()*+,;=-._~")
    display_path = _display_path(parsed.path)
    port_text = f":{port}" if port is not None else ""
    key_host = f"[{hostname}]" if ":" in hostname else hostname
    display_domain = defang_host(hostname)
    return SafeUrl(
        key=f"{scheme}://{key_host}{port_text}{key_path}",
        display_url=f"{display_scheme}://{display_domain}{port_text}{display_path}",
        display_domain=display_domain,
    )


def stable_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def safe_screenshot_url(value: object) -> str | None:
    cleaned = clean_text(value, 2048)
    if not cleaned:
        return None
    try:
        parsed = urlsplit(cleaned)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or not parsed.hostname
    ):
        return None
    if (
        parsed.hostname.lower() != "urlscan.io"
        or not URLSCAN_SCREENSHOT_PATH.fullmatch(parsed.path)
    ):
        return None
    return urlunsplit(("https", "urlscan.io", parsed.path, "", ""))


def safe_reference_url(value: object) -> str | None:
    cleaned = clean_text(value, 2048)
    if not cleaned:
        return None
    try:
        parsed = urlsplit(cleaned)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != "urlscan.io"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or not URLSCAN_REPORT_PATH.fullmatch(parsed.path)
    ):
        return None
    return urlunsplit(("https", "urlscan.io", f"{parsed.path.rstrip('/')}/", "", ""))


def safe_feed_url(value: str) -> str:
    parsed = urlsplit(value)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("Feed URLs must use HTTPS (HTTP is allowed only for localhost development).")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Feed URLs must not contain credentials.")
    return value
