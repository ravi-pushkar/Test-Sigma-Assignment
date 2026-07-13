"""Deterministic action generation and safety checks for crawl elements."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from urllib.parse import urljoin, urlsplit

from blast_agent.contracts import UIElement

from .policy import CandidateAction


FILL_VALUES: dict[str, str] = {
    "username": "demo-user",
    "password": "DemoUser2026!",
    "issue_title": "Crawler-created issue for flow F2",
    "issue_body": (
        "Created autonomously by the crawl agent while exercising the issue "
        "creation flow."
    ),
}


@dataclass(slots=True)
class CrawlRules:
    """Routes and labels that bound an autonomous crawl."""

    base_url: str
    allowed_exact: set[str] = field(
        default_factory=lambda: {"/", "/issues", "/notifications"}
    )
    allowed_prefixes: tuple[str, ...] = ("/user/login", "/demo")
    prohibited_prefixes: tuple[str, ...] = (
        "/admin",
        "/user/settings",
        "/user/logout",
        "/api",
    )
    destructive_keywords: tuple[str, ...] = (
        "delete",
        "remove",
        "transfer",
        "archive",
        "wipe",
        "purge",
    )


def candidates_for(
    elements: list[UIElement],
    rules: CrawlRules,
    visited_pairs: set[tuple[str, str]],
    visited_logical: set[tuple[str, str, str]],
    url_path: str | None = None,
) -> list[CandidateAction]:
    """Represent every element as a candidate, retaining blocked evidence."""

    base_host = urlsplit(rules.base_url).hostname
    candidates: list[CandidateAction] = []

    for element in elements:
        href = element.attributes.get("href")
        role = element.role.casefold()
        reason_blocked: str | None = (
            "not-actionable" if role == "form" else None
        )

        if href and reason_blocked is None:
            parsed_href = urlsplit(urljoin(rules.base_url, href))
            path = parsed_href.path or "/"
            if parsed_href.hostname != base_host:
                reason_blocked = "external-host"
            elif any(path.startswith(prefix) for prefix in rules.prohibited_prefixes):
                reason_blocked = "prohibited-route"
            elif not (
                path in rules.allowed_exact
                or any(path.startswith(prefix) for prefix in rules.allowed_prefixes)
            ):
                reason_blocked = "out-of-scope"

        if reason_blocked is None and any(
            keyword.casefold() in element.name.casefold()
            for keyword in rules.destructive_keywords
        ):
            reason_blocked = "destructive-action"
        base_name = re.sub(r" #\d+$", "", element.name)
        logical_visited = (
            (url_path, element.role, base_name) in visited_logical
            if url_path is not None
            else any(
                role == element.role and name == base_name
                for _route, role, name in visited_logical
            )
        )
        if reason_blocked is None and (
            (
                (url_path, element.id) in visited_pairs
                if url_path is not None
                else any(element_id == element.id for _path, element_id in visited_pairs)
            )
            or logical_visited
        ):
            reason_blocked = "already-executed"

        element_type = element.attributes.get("type", "").casefold()
        if role in {"textbox", "combobox"}:
            action = "fill"
        elif role == "button" and element_type == "submit":
            action = "submit"
        else:
            action = "click"

        candidates.append(
            CandidateAction(
                element_id=element.id,
                role=element.role,
                name=element.name,
                href=href,
                action=action,
                reason_blocked=reason_blocked,
                fill_value_key=fill_key_for(element),
            )
        )

    return candidates


def fill_key_for(element: UIElement) -> str | None:
    """Return the fixed input class for a fillable element, if known."""

    name_to_key = {
        "user_name": "username",
        "password": "password",
        "title": "issue_title",
        "content": "issue_body",
    }
    if key := name_to_key.get(element.attributes.get("name", "")):
        return key
    if "title" in element.attributes.get("placeholder", "").casefold():
        return "issue_title"
    return None


__all__ = ["FILL_VALUES", "CrawlRules", "candidates_for", "fill_key_for"]
