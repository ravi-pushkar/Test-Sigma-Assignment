"""Unit tests for Gemini JSON generation and crawl action policies."""

import json
from pathlib import Path
from typing import Any

import pytest

from blast_agent.contracts import ScreenState
from blast_agent.crawl import ArtifactStore, CrawlAgent, CrawlRules, PageExtractor
from blast_agent.crawl.policy import CandidateAction, FallbackPolicy, LLMPolicy
from blast_agent.llm import GeminiClient, LLMUnavailable


def gemini_response(value: dict[str, Any]) -> dict[str, Any]:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(value)}]}}]}


def screen() -> ScreenState:
    return ScreenState.model_validate(
        {
            "id": "screen:test",
            "run_id": "run:test",
            "source": "crawler",
            "source_revision": "abc123",
            "url": "http://localhost:3000/demo/repo/issues",
            "route_pattern": "/{owner}/{repo}/issues",
            "title": "Issues",
            "dom_artifact": "dom/test.html",
            "screenshot_artifact": "screenshots/test.png",
            "visible_text_hash": "deadbeef",
        }
    )


def test_generate_json_parses_structured_json() -> None:
    captured: dict[str, Any] = {}

    def transport(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        captured.update(url=url, body=body, headers=headers)
        return 200, gemini_response({"index": 1, "rationale": "best next step"})

    client = GeminiClient("secret", transport=transport)
    result = client.generate_json("choose", {"type": "OBJECT"})

    assert result == {"index": 1, "rationale": "best next step"}
    assert captured["headers"]["x-goog-api-key"] == "secret"
    assert captured["body"]["generationConfig"] == {
        "responseMimeType": "application/json",
        "responseSchema": {"type": "OBJECT"},
        "temperature": 0.0,
    }


def test_generate_json_retries_429_then_succeeds() -> None:
    statuses = iter([429, 429, 200])
    delays: list[float] = []

    def transport(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        status = next(statuses)
        payload = gemini_response({"ok": True}) if status == 200 else {}
        return status, payload

    client = GeminiClient(
        "secret",
        transport=transport,
        sleep=delays.append,
        min_interval_seconds=0,
    )

    assert client.generate_json("prompt", {}) == {"ok": True}
    assert delays == [15, 30]


def test_generate_json_raises_after_five_retryable_failures() -> None:
    attempts = 0
    delays: list[float] = []

    def transport(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        nonlocal attempts
        attempts += 1
        return 429, {"error": {"message": "rate limited"}}

    client = GeminiClient(
        "secret",
        transport=transport,
        sleep=delays.append,
        min_interval_seconds=0,
    )

    with pytest.raises(LLMUnavailable):
        client.generate_json("prompt", {})

    assert attempts == 5
    assert delays == [15, 30, 45, 60]


def test_generate_json_throttles_consecutive_calls_and_retries() -> None:
    now = [0.0]
    delays: list[float] = []
    call_times: list[float] = []

    def clock() -> float:
        return now[0]

    def sleep(delay: float) -> None:
        delays.append(delay)
        now[0] += delay

    def successful_transport(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        call_times.append(clock())
        return 200, gemini_response({"ok": True})

    client = GeminiClient(
        "secret",
        transport=successful_transport,
        sleep=sleep,
        min_interval_seconds=10,
        clock=clock,
    )
    assert client.generate_json("first", {}) == {"ok": True}
    now[0] += 3
    assert client.generate_json("second", {}) == {"ok": True}

    assert call_times == [0.0, 10.0]
    assert delays == pytest.approx([7.0])

    retry_now = [0.0]
    retry_delays: list[float] = []
    retry_call_times: list[float] = []
    statuses = iter([429, 200])

    def retry_clock() -> float:
        return retry_now[0]

    def retry_sleep(delay: float) -> None:
        retry_delays.append(delay)
        retry_now[0] += delay

    def retry_transport(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        retry_call_times.append(retry_clock())
        status = next(statuses)
        return status, gemini_response({"ok": True}) if status == 200 else {}

    retrying_client = GeminiClient(
        "secret",
        transport=retry_transport,
        sleep=retry_sleep,
        min_interval_seconds=20,
        clock=retry_clock,
    )
    assert retrying_client.generate_json("retry", {}) == {"ok": True}

    assert retry_call_times == [0.0, 20.0]
    assert retry_delays == pytest.approx([15.0, 5.0])


def test_llm_policy_maps_index_and_excludes_blocked_candidates() -> None:
    captured_prompt = ""

    def transport(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        nonlocal captured_prompt
        captured_prompt = body["contents"][0]["parts"][0]["text"]
        return 200, gemini_response({"index": 1, "rationale": "open the form"})

    candidates = [
        CandidateAction("blocked", "link", "Admin", "/admin", "click", "unsafe"),
        CandidateAction("issues", "link", "Issues", "/demo/repo/issues", "click"),
        CandidateAction("new", "link", "New Issue", "/demo/repo/issues/new", "click"),
    ]
    policy = LLMPolicy(GeminiClient("secret", transport=transport))

    decision = policy.decide("Create issue", screen(), candidates, [])

    assert decision.element_id == "new"
    assert decision.action == "click"
    assert decision.rationale == "open the form"
    assert decision.source == "llm"
    assert "Admin" not in captured_prompt
    assert "/admin" not in captured_prompt


def test_llm_policy_negative_one_stops() -> None:
    def transport(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        return 200, gemini_response({"index": -1, "rationale": "goal complete"})

    decision = LLMPolicy(GeminiClient("secret", transport=transport)).decide(
        "Create issue", screen(), [], []
    )

    assert decision.element_id is None
    assert decision.action is None
    assert decision.rationale == "goal complete"
    assert decision.source == "stop"


def test_fallback_policy_rescans_login_recipe_from_the_start() -> None:
    policy = FallbackPolicy()
    root_screen = screen().model_copy(update={"route_pattern": "/"})
    login_screen = screen().model_copy(update={"route_pattern": "/user/login"})
    goal = "Sign in to the local Gitea as demo-user using the sign-in form"

    def candidates(
        *, username_blocked=False, password_blocked=False, button_blocked=False
    ):
        return [
            CandidateAction("home", "link", "Home", "/", "click"),
            CandidateAction(
                "username",
                "textbox",
                "user_name",
                None,
                "fill",
                "already-executed" if username_blocked else None,
            ),
            CandidateAction(
                "password",
                "textbox",
                "password",
                None,
                "fill",
                "already-executed" if password_blocked else None,
            ),
            CandidateAction(
                "sign-in",
                "button",
                "Sign In",
                None,
                "submit",
                "already-executed" if button_blocked else None,
            ),
            CandidateAction("remember", "checkbox", "remember", None, "click"),
        ]

    navbar = [
        CandidateAction("home", "link", "Home", "/", "click"),
        CandidateAction(
            "navbar-sign-in", "link", "Sign In", "/user/login", "click"
        ),
    ]

    zeroth = policy.decide(goal, root_screen, navbar, [])
    first = policy.decide(goal, login_screen, candidates(), [])
    second = policy.decide(
        goal, login_screen, candidates(username_blocked=True), []
    )
    third = policy.decide(
        goal,
        login_screen,
        candidates(username_blocked=True, password_blocked=True),
        [],
    )

    assert zeroth.element_id == "navbar-sign-in"
    assert zeroth.action == "click"
    assert first.element_id == "username"
    assert first.action == "fill"
    assert second.element_id == "password"
    assert second.action == "fill"
    assert third.element_id == "sign-in"
    assert third.action == "submit"
    assert third.rationale == "recipe keyword 'sign in' matched candidate 'Sign In'"


def test_fallback_policy_skips_repository_navigation_on_repository_route() -> None:
    policy = FallbackPolicy()
    repository_screen = screen().model_copy(
        update={"route_pattern": "/{owner}/{repo}"}
    )
    candidates = [
        CandidateAction(
            "repo", "link", "demo-repo", "/demo/demo-repo", "click"
        ),
        CandidateAction(
            "rss", "link", "RSS Feed", "/demo/demo-repo.rss", "click"
        ),
        CandidateAction(
            "issues", "link", "Issues", "/demo/demo-repo/issues", "click"
        ),
        CandidateAction(
            "new-issue",
            "link",
            "New Issue",
            "/demo/demo-repo/issues/new",
            "click",
        ),
    ]

    decision = policy.decide(
        "Create a new issue in demo/demo-repo", repository_screen, candidates, []
    )

    assert decision.element_id == "new-issue"
    assert decision.rationale == (
        "recipe keyword 'new issue' matched candidate 'New Issue'"
    )


def test_fallback_policy_prefers_exact_name_over_substring() -> None:
    policy = FallbackPolicy()
    issue_screen = screen().model_copy(
        update={
            "route_pattern": "/{owner}/{repo}/issues/{number}",
            "url": "http://localhost:3000/demo/demo-repo/issues/1",
        }
    )
    candidates = [
        CandidateAction("unsubscribe", "button", "Unsubscribe", None, "click"),
        CandidateAction("subscribe", "button", "Subscribe", None, "click"),
    ]

    decision = policy.decide(
        "Subscribe to notifications for this issue", issue_screen, candidates, []
    )
    unsubscribe_only = policy.decide(
        "Subscribe to notifications for this issue",
        issue_screen,
        [candidates[0]],
        [],
    )

    assert decision.element_id == "subscribe"
    assert unsubscribe_only.element_id is None
    assert unsubscribe_only.source == "stop"


def test_fallback_policy_prefers_click_over_fill_for_issue_title() -> None:
    policy = FallbackPolicy()
    issues_screen = screen().model_copy(
        update={
            "route_pattern": "/{owner}/{repo}/issues",
            "url": "http://localhost:3000/demo/demo-repo/issues/1",
        }
    )
    title = "Sidebar labels are not saved on first click"
    candidates = [
        CandidateAction("checkbox", "textbox", title, None, "fill"),
        CandidateAction(
            "issue-link",
            "link",
            title,
            "/demo/demo-repo/issues/1",
            "click",
        ),
    ]

    decision = policy.decide(
        "Subscribe to notifications for the issue titled " + title,
        issues_screen,
        candidates,
        [],
    )

    assert decision.element_id == "issue-link"
    assert decision.action == "click"


def test_fallback_policy_navigates_to_f3_issue_and_skips_when_on_path() -> None:
    policy = FallbackPolicy()
    off_path = screen().model_copy(
        update={"url": "http://localhost:3000/demo/demo-repo/issues"}
    )
    on_path = screen().model_copy(
        update={
            "url": "http://localhost:3000/demo/demo-repo/issues/1",
            "route_pattern": "/{owner}/{repo}/issues/{number}",
        }
    )

    navigation = policy.decide(
        "Subscribe to notifications for this issue", off_path, [], []
    )
    subscribe = policy.decide(
        "Subscribe to notifications for this issue",
        on_path,
        [CandidateAction("subscribe", "button", "Subscribe", None, "click")],
        [],
    )

    assert navigation.element_id is None
    assert navigation.action == "navigate"
    assert navigation.navigate_to == "/demo/demo-repo/issues/1"
    assert navigation.source == "deterministic"
    assert subscribe.element_id == "subscribe"
    assert subscribe.navigate_to is None


def test_fallback_policy_uses_generic_link_after_login_recipe_is_blocked() -> None:
    policy = FallbackPolicy()
    login_screen = screen().model_copy(update={"route_pattern": "/user/login"})
    candidates = [
        CandidateAction("home", "link", "Home", "/", "click"),
        CandidateAction(
            "username", "textbox", "user_name", None, "fill", "already-executed"
        ),
        CandidateAction(
            "password", "textbox", "password", None, "fill", "already-executed"
        ),
        CandidateAction(
            "sign-in", "button", "Sign In", None, "submit", "already-executed"
        ),
        CandidateAction("remember", "checkbox", "remember", None, "click"),
    ]

    fourth = policy.decide(
        "Sign in to the local Gitea as demo-user using the sign-in form",
        login_screen,
        candidates,
        [],
    )

    assert fourth.element_id == "home"
    assert fourth.action == "click"
    assert fourth.rationale == "first unvisited non-blocked link rule"


def test_crawl_agent_latches_fallback_after_llm_unavailable(tmp_path: Path) -> None:
    class UnavailablePolicy:
        def __init__(self) -> None:
            self.calls = 0

        def decide(self, goal, screen, candidates, trajectory):
            self.calls += 1
            raise LLMUnavailable("quota exhausted")

    policy = UnavailablePolicy()
    agent = CrawlAgent(
        policy,
        ArtifactStore(tmp_path),
        PageExtractor("run:test", "abc123"),
        CrawlRules("http://localhost:3000"),
    )
    candidates = [
        CandidateAction("login", "button", "Sign In", None, "submit")
    ]

    first = agent.decide_with_fallback(
        "Sign in as demo-user", screen(), candidates, []
    )
    second = agent.decide_with_fallback(
        "Sign in as demo-user", screen(), candidates, []
    )

    assert policy.calls == 1
    assert first.element_id == "login"
    assert second.element_id == "login"
    assert first.source == second.source == "deterministic"
    assert first.rationale.startswith("llm-unavailable-fallback: ")
    assert second.rationale.startswith("llm-unavailable-fallback: ")
