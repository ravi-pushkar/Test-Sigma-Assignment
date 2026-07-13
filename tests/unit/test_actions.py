"""Deterministic action safety and input-class coverage."""

from blast_agent.contracts import UIElement
from blast_agent.crawl.actions import CrawlRules, candidates_for, fill_key_for


def element(
    element_id: str,
    name: str,
    *,
    role: str = "link",
    attributes: dict[str, str] | None = None,
    screen_id: str = "screen:test",
) -> UIElement:
    return UIElement.model_validate(
        {
            "id": element_id,
            "run_id": "run:test",
            "source": "crawler",
            "source_revision": "abc123",
            "screen_id": screen_id,
            "role": role,
            "name": name,
            "locator_evidence": {"text": name},
            "attributes": attributes or {},
            "bounds": None,
        }
    )


def test_candidates_retain_allowed_and_blocked_elements() -> None:
    elements = [
        element("external", "Gitea", attributes={"href": "https://about.gitea.com"}),
        element("scope", "Explore", attributes={"href": "/explore/repos"}),
        element("admin", "Admin users", attributes={"href": "/admin/users"}),
        element("logout", "Sign out", attributes={"href": "/user/logout"}),
        element("delete", "Delete Repository", role="button"),
        element("form", "Sign In form contents", role="form"),
        element("visited", "Notifications", attributes={"href": "/notifications"}),
        element("logical", "Dashboard #2", attributes={"href": "/"}),
        element("issues", "Issues", attributes={"href": "/demo/demo-repo/issues"}),
        element(
            "username",
            "Username",
            role="textbox",
            attributes={"name": "user_name"},
        ),
    ]

    candidates = candidates_for(
        elements,
        CrawlRules("http://localhost:3000"),
        {("/", "visited")},
        {("/", "link", "Dashboard")},
        "/",
    )
    by_id = {candidate.element_id: candidate for candidate in candidates}

    assert len(candidates) == len(elements)
    assert by_id["external"].reason_blocked == "external-host"
    assert by_id["scope"].reason_blocked == "out-of-scope"
    assert by_id["admin"].reason_blocked == "prohibited-route"
    assert by_id["logout"].reason_blocked == "prohibited-route"
    assert by_id["delete"].reason_blocked == "destructive-action"
    assert by_id["form"].reason_blocked == "not-actionable"
    assert by_id["visited"].reason_blocked == "already-executed"
    assert by_id["logical"].reason_blocked == "already-executed"
    assert by_id["issues"].reason_blocked is None
    assert by_id["issues"].action == "click"
    assert by_id["username"].reason_blocked is None
    assert by_id["username"].action == "fill"


def test_logical_dedup_distinguishes_concrete_issue_paths() -> None:
    subscribe = element("subscribe", "Subscribe", role="button")
    visited_logical = {
        ("/demo/demo-repo/issues/1", "button", "Subscribe")
    }

    issue_four = candidates_for(
        [subscribe],
        CrawlRules("http://localhost:3000"),
        set(),
        visited_logical,
        "/demo/demo-repo/issues/4",
    )[0]
    issue_one = candidates_for(
        [subscribe],
        CrawlRules("http://localhost:3000"),
        set(),
        visited_logical,
        "/demo/demo-repo/issues/1",
    )[0]

    assert issue_four.reason_blocked is None
    assert issue_one.reason_blocked == "already-executed"


def test_fill_key_for_maps_only_fixed_input_classes() -> None:
    assert fill_key_for(element("u", "User", attributes={"name": "user_name"})) == "username"
    assert fill_key_for(element("p", "Pass", attributes={"name": "password"})) == "password"
    assert fill_key_for(element("t", "Title", attributes={"name": "title"})) == "issue_title"
    assert fill_key_for(element("c", "Body", attributes={"name": "content"})) == "issue_body"
    assert fill_key_for(element("ph", "Subject", attributes={"placeholder": "Issue title"})) == "issue_title"
    assert fill_key_for(element("other", "Other", attributes={"name": "labels"})) is None
