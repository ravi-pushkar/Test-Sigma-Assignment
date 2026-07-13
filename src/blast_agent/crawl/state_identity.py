"""Deterministic identities for browser-observed application states."""

from __future__ import annotations

from hashlib import sha256
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from blast_agent.contracts.common import stable_id


_RESERVED_FIRST_SEGMENTS = frozenset(
    {
        "user",
        "admin",
        "api",
        "explore",
        "notifications",
        "milestones",
        "issues",
        "org",
        "repo",
        "login",
        "assets",
        "attachments",
        "-",
    }
)

_ROUTE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^/user/login/?$"), "/user/login"),
    (
        re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/new/?$"),
        "/{owner}/{repo}/issues/new",
    ),
    (
        re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/\d+/?$"),
        "/{owner}/{repo}/issues/{number}",
    ),
    (
        re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/?$"),
        "/{owner}/{repo}/issues",
    ),
    (
        re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/?$"),
        "/{owner}/{repo}",
    ),
    (re.compile(r"^/?$"), "/"),
)

_UUID_VALUE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_LONG_INTEGER_VALUE = re.compile(r"^\d{10,}$")
_ISO_TIMESTAMP_VALUE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$",
    re.IGNORECASE,
)
_LONG_HEX_VALUE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)
_OPAQUE_TOKEN_VALUE = re.compile(r"^[A-Za-z0-9_-]{24,}$")


def _is_volatile_query_value(value: str) -> bool:
    """Recognize values normally generated uniquely for a request or session."""

    return any(
        pattern.fullmatch(value)
        for pattern in (
            _UUID_VALUE,
            _LONG_INTEGER_VALUE,
            _ISO_TIMESTAMP_VALUE,
            _LONG_HEX_VALUE,
            _OPAQUE_TOKEN_VALUE,
        )
    )


def _normalized_netloc(url: str) -> tuple[str, str, str, str, str]:
    """Return the urlsplit parts with only the host portion case-normalized."""

    parsed = urlsplit(url)
    host = parsed.hostname
    if host is None:
        return (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )

    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"

    normalized_host = host.lower()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{userinfo}{normalized_host}{port}"
    return parsed.scheme.lower(), netloc, parsed.path, parsed.query, parsed.fragment


def canonicalize_url(url: str) -> str:
    """Normalize URL identity while discarding fragments and volatile values."""

    scheme, netloc, path, query, _fragment = _normalized_netloc(url)
    if path != "/":
        path = path.rstrip("/")

    stable_query_items = [
        (key, value)
        for key, value in parse_qsl(query, keep_blank_values=True)
        if not _is_volatile_query_value(value)
    ]
    stable_query_items.sort(key=lambda item: (item[0], item[1]))
    normalized_query = urlencode(stable_query_items, doseq=True)

    return urlunsplit((scheme, netloc, path, normalized_query, ""))


def route_pattern(url: str) -> str:
    """Return a stable Gitea route pattern for a URL."""

    path = urlsplit(url).path or "/"
    for rule, pattern in _ROUTE_RULES:
        match = rule.fullmatch(path)
        if match is None:
            continue
        owner = match.groupdict().get("owner")
        if owner is not None and owner.casefold() in _RESERVED_FIRST_SEGMENTS:
            continue
        return pattern

    segments = path.split("/")
    return "/".join("{number}" if segment.isdigit() else segment for segment in segments)


def visible_text_hash(text: str) -> str:
    """Hash text after normalizing all whitespace runs."""

    normalized = " ".join(text.split())
    return sha256(normalized.encode("utf-8")).hexdigest()[:16]


def screen_id_for(canonical_url: str, text_hash: str) -> str:
    """Build the documented ScreenState natural-key identifier."""

    return stable_id("screen", canonical_url, text_hash)


__all__ = [
    "canonicalize_url",
    "route_pattern",
    "screen_id_for",
    "visible_text_hash",
]
