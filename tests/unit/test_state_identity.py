"""Unit tests for deterministic crawl-state identity."""

from hashlib import sha256

import pytest

from blast_agent.crawl.state_identity import (
    canonicalize_url,
    route_pattern,
    screen_id_for,
    visible_text_hash,
)
from blast_agent.contracts import stable_id


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "HTTP://LOCALHOST:3000/demo/demo-repo/#overview",
            "http://localhost:3000/demo/demo-repo",
        ),
        ("http://LOCALHOST:3000/", "http://localhost:3000/"),
        (
            "http://localhost:3000/explore?sort=recent&tab=repositories",
            "http://localhost:3000/explore?sort=recent&tab=repositories",
        ),
        (
            "http://localhost:3000/explore?ts=1712345678901&sort=recent",
            "http://localhost:3000/explore?sort=recent",
        ),
        (
            "http://localhost:3000/explore?z=last&a=first#results",
            "http://localhost:3000/explore?a=first&z=last",
        ),
    ],
)
def test_canonicalize_url(url: str, expected: str) -> None:
    assert canonicalize_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:3000/user/login", "/user/login"),
        (
            "http://localhost:3000/demo/demo-repo/issues/new",
            "/{owner}/{repo}/issues/new",
        ),
        (
            "http://localhost:3000/demo/demo-repo/issues/1",
            "/{owner}/{repo}/issues/{number}",
        ),
        (
            "http://localhost:3000/demo/demo-repo/issues",
            "/{owner}/{repo}/issues",
        ),
        ("http://localhost:3000/demo/demo-repo", "/{owner}/{repo}"),
        ("http://localhost:3000/", "/"),
        ("http://localhost:3000/notifications", "/notifications"),
        ("http://localhost:3000/user/settings", "/user/settings"),
        ("http://localhost:3000/projects/123/tasks/456", "/projects/{number}/tasks/{number}"),
    ],
)
def test_route_pattern(url: str, expected: str) -> None:
    assert route_pattern(url) == expected


def test_visible_text_hash_collapses_whitespace() -> None:
    expected = sha256(b"Sign in to Gitea").hexdigest()[:16]

    assert visible_text_hash("  Sign\n\tin   to\r\nGitea  ") == expected
    assert visible_text_hash("Sign in to Gitea") == expected


def test_identity_functions_are_deterministic() -> None:
    url = "HTTP://LOCALHOST:3000/demo/demo-repo/issues/42/?b=2&a=1#comment"

    assert canonicalize_url(url) == canonicalize_url(url)
    assert route_pattern(url) == route_pattern(url)
    assert visible_text_hash("same text") == visible_text_hash("same text")


def test_screen_id_uses_contract_natural_key() -> None:
    url = "http://localhost:3000/user/login"
    text_hash = visible_text_hash("Sign In")

    assert screen_id_for(url, text_hash) == stable_id("screen", url, text_hash)
