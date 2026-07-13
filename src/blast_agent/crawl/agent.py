"""Autonomous, policy-directed crawl loop with deterministic execution bounds."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from blast_agent.contracts import (
    Interaction,
    ScreenState,
    UIElement,
    UserFlow,
    stable_id,
)
from blast_agent.llm import LLMUnavailable

from .actions import FILL_VALUES, CrawlRules, candidates_for, fill_key_for
from .artifact_store import ArtifactStore
from .extractor import ExtractedScreen, PageExtractor
from .policy import (
    ActionPolicy,
    CandidateAction,
    FallbackPolicy,
    PolicyDecision,
)


@dataclass(frozen=True, slots=True)
class FlowGoal:
    key: str
    goal: str
    success_check: Callable[[Page], bool]


def _signed_in(page: Page) -> bool:
    return page.locator('.avatar, [aria-label*="profile" i]').count() > 0 or (
        "demo-user" in page.content() and "/user/login" not in page.url
    )


def _issue_created(page: Page) -> bool:
    return bool(re.search(r"/demo/demo-repo/issues/\d+", page.url)) and (
        "Crawler-created issue for flow F2" in page.content()
    )


def _issue_watched(page: Page) -> bool:
    content = page.content()
    return "/demo/demo-repo/issues/1" in page.url and (
        "Unwatch" in content or "Unsubscribe" in content
    )


DEFAULT_GOALS = [
    FlowGoal(
        "F1",
        "Sign in to the local Gitea as demo-user using the sign-in form",
        _signed_in,
    ),
    FlowGoal(
        "F2",
        'Create a new issue in the demo/demo-repo repository titled "Crawler-created issue for flow F2"',
        _issue_created,
    ),
    FlowGoal(
        "F3",
        'In demo/demo-repo, open the issue titled "Sidebar labels are not saved on first click" '
        "and subscribe to notifications for it using the Watch/Subscribe button in the "
        "issue sidebar.",
        _issue_watched,
    ),
]


class CrawlAgent:
    """Run flow goals sequentially in one browser session."""

    TOTAL_ACTION_LIMIT = 80

    def __init__(
        self,
        policy: ActionPolicy,
        store: ArtifactStore,
        extractor: PageExtractor,
        rules: CrawlRules,
        max_actions_per_flow: int = 15,
        max_seconds: float = 900.0,
        decision_log_path: Path | None = None,
    ) -> None:
        self.policy = policy
        self.store = store
        self.extractor = extractor
        self.rules = rules
        self.max_actions_per_flow = max_actions_per_flow
        self.max_seconds = max_seconds
        self.decision_log_path = decision_log_path or store.root / "decisions.jsonl"
        self.decision_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.decision_log_path.write_text("", encoding="utf-8")
        self._fallback_policy: FallbackPolicy | None = None
        self._use_fallback_for_current_flow = False

    def run(self, page: Page, goals: list[FlowGoal]) -> list[UserFlow]:
        started_at = time.monotonic()
        deadline = started_at + self.max_seconds
        total_actions = 0
        saved_screen_ids: set[str] = set()
        flows: list[UserFlow] = []

        for goal in goals:
            self._use_fallback_for_current_flow = False
            visited_pairs: set[tuple[str, str]] = set()
            visited_logical: set[tuple[str, str, str]] = set()
            self._navigate_to_base(page, deadline)
            current = self.extractor.extract(page)
            self._save_screen_once(current, saved_screen_ids)
            start_state_id = current.screen.id
            interaction_ids: list[str] = []
            trajectory: list[str] = []
            actions_used = 0
            succeeded = False
            used_llm_action = False

            while (
                actions_used < self.max_actions_per_flow
                and total_actions < self.TOTAL_ACTION_LIMIT
                and time.monotonic() < deadline
            ):
                if goal.success_check(page):
                    succeeded = True
                    break

                candidates = candidates_for(
                    current.elements,
                    self.rules,
                    visited_pairs,
                    visited_logical,
                    urlsplit(current.screen.url).path or "/",
                )
                viable = [candidate for candidate in candidates if not candidate.reason_blocked]
                blocked_count = len(candidates) - len(viable)
                decision = self.decide_with_fallback(
                    goal.goal, current.screen, viable, trajectory
                )
                candidate = next(
                    (
                        item
                        for item in viable
                        if item.element_id == decision.element_id
                    ),
                    None,
                )
                element_name = (
                    candidate.name
                    if candidate is not None
                    else decision.navigate_to
                    if decision.action == "navigate"
                    else None
                )
                self._append_decision(
                    step=total_actions + 1,
                    goal=goal,
                    source=current,
                    element_name=element_name,
                    action=decision.action or "stop",
                    decision_source=decision.source,
                    rationale=decision.rationale,
                    blocked_count=blocked_count,
                )
                if decision.source == "stop" or (
                    decision.element_id is None and decision.action != "navigate"
                ):
                    break

                if decision.action == "navigate" and decision.navigate_to is not None:
                    element = self._navigation_element(current, decision.navigate_to)
                    self.store.save_record(element, "elements")
                    candidate = CandidateAction(
                        element.id,
                        element.role,
                        element.name,
                        decision.navigate_to,
                        "navigate",
                    )
                else:
                    if candidate is None:
                        break
                    element = next(
                        item
                        for item in current.elements
                        if item.id == candidate.element_id
                    )

                source = current
                action_success, input_class = self._execute(page, element, candidate)
                actions_used += 1
                total_actions += 1
                used_llm_action = used_llm_action or decision.source == "llm"
                current = self.extractor.extract(page)
                self._save_screen_once(current, saved_screen_ids)

                interaction = self._interaction(
                    source,
                    current,
                    element,
                    candidate.action,
                    input_class,
                    action_success,
                )
                self.store.save_record(interaction, "interactions")
                interaction_ids.append(interaction.id)
                source_path = urlsplit(source.screen.url).path or "/"
                visited_pairs.add((source_path, element.id))
                base_name = re.sub(r" #\d+$", "", element.name)
                visited_logical.add(
                    (source_path, element.role, base_name)
                )
                trajectory.append(
                    f"{source.screen.route_pattern}: {candidate.action} {element.id}"
                    f" | role={element.role} | name={base_name}"
                    f" | href={candidate.href or ''}"
                )

            if not succeeded and goal.success_check(page):
                succeeded = True

            flow = self._flow(
                goal.goal,
                interaction_ids,
                start_state_id,
                current.screen.id,
                used_llm_action,
            )
            self.store.save_record(flow, "flows")
            self._save_flow_result(flow, goal, succeeded, actions_used)
            flows.append(flow)

        return flows

    def _navigation_element(
        self, source: ExtractedScreen, navigate_to: str
    ) -> UIElement:
        element_id = stable_id(
            "element", source.screen.id, "navigation", navigate_to
        )
        return UIElement.model_validate(
            {
                "id": element_id,
                "run_id": self.extractor.run_id,
                "source": "crawler",
                "source_revision": self.extractor.source_revision,
                "screen_id": source.screen.id,
                "role": "navigation",
                "name": navigate_to,
                "locator_evidence": {"href": navigate_to},
                "attributes": {"href": navigate_to},
                "bounds": None,
            }
        )

    def decide_with_fallback(
        self,
        goal: str,
        screen: ScreenState,
        candidates: list[CandidateAction],
        trajectory: list[str],
    ) -> PolicyDecision:
        """Choose an action, latching fallback for the flow after an LLM outage."""

        if self._use_fallback_for_current_flow:
            return self._unavailable_fallback_decision(
                goal, screen, candidates, trajectory
            )
        try:
            return self.policy.decide(goal, screen, candidates, trajectory)
        except LLMUnavailable:
            self._use_fallback_for_current_flow = True
            return self._unavailable_fallback_decision(
                goal, screen, candidates, trajectory
            )

    def _unavailable_fallback_decision(
        self,
        goal: str,
        screen: ScreenState,
        candidates: list[CandidateAction],
        trajectory: list[str],
    ) -> PolicyDecision:
        if self._fallback_policy is None:
            self._fallback_policy = FallbackPolicy()
        fallback = self._fallback_policy.decide(
            goal, screen, candidates, trajectory
        )
        return PolicyDecision(
            fallback.element_id,
            fallback.action,
            f"llm-unavailable-fallback: {fallback.rationale}",
            "deterministic",
            fallback.fill_value_key,
            fallback.navigate_to,
        )

    def _navigate_to_base(self, page: Page, deadline: float) -> None:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        try:
            page.goto(
                self.rules.base_url,
                wait_until="networkidle",
                timeout=min(15_000, remaining_ms),
            )
        except PlaywrightTimeoutError:
            pass

    def _save_screen_once(
        self, extracted: ExtractedScreen, saved_screen_ids: set[str]
    ) -> None:
        if extracted.screen.id in saved_screen_ids:
            return
        self.store.save_screen(extracted)
        self.store.save_elements(extracted.elements)
        saved_screen_ids.add(extracted.screen.id)

    @staticmethod
    def _locator(page: Page, element: UIElement) -> Locator:
        evidence = element.locator_evidence
        role = element.role.casefold()
        if role in {"button", "link"}:
            role_name = re.sub(r" #\d+$", "", element.name)
            exact_role_locator = page.get_by_role(
                role, name=role_name, exact=True
            ).first
            if exact_role_locator.count() > 0:
                return exact_role_locator
            substring_role_locator = page.get_by_role(
                role, name=role_name
            ).first
            if substring_role_locator.count() > 0:
                return substring_role_locator
        if css := evidence.get("css"):
            return page.locator(css)
        if test_id := evidence.get("testid"):
            return page.get_by_test_id(test_id)
        if href := evidence.get("href"):
            return page.locator(f"[href={json.dumps(href)}]")
        return page.get_by_text(element.name, exact=False)

    def _execute(
        self, page: Page, element: UIElement, candidate: CandidateAction
    ) -> tuple[bool, str | None]:
        input_class = fill_key_for(element) if candidate.action == "fill" else None
        try:
            if candidate.action == "navigate":
                page.goto(
                    f"{self.rules.base_url.rstrip('/')}{candidate.href}",
                    wait_until="networkidle",
                    timeout=15_000,
                )
                return True, None
            locator = self._locator(page, element)
            if candidate.action == "fill":
                if input_class is None:
                    return False, None
                locator.fill(FILL_VALUES[input_class])
            else:
                locator.click()
                page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            return False, input_class
        return True, input_class

    def _interaction(
        self,
        source: ExtractedScreen,
        target: ExtractedScreen,
        element: UIElement,
        action: str,
        input_class: str | None,
        success: bool,
    ) -> Interaction:
        interaction_id = stable_id(
            "interaction",
            source.screen.id,
            element.id,
            action,
            target.screen.id,
        )
        return Interaction.model_validate(
            {
                "id": interaction_id,
                "run_id": self.extractor.run_id,
                "source": "crawler",
                "source_revision": self.extractor.source_revision,
                "source_state_id": source.screen.id,
                "target_state_id": target.screen.id,
                "element_id": element.id,
                "action": action,
                "input_class": input_class,
                "timestamp": datetime.now(UTC),
                "success": success,
            }
        )

    def _flow(
        self,
        goal: str,
        interaction_ids: list[str],
        start_state_id: str,
        end_state_id: str,
        used_llm_action: bool,
    ) -> UserFlow:
        flow_id = stable_id("flow", goal, start_state_id, end_state_id)
        return UserFlow.model_validate(
            {
                "id": flow_id,
                "run_id": self.extractor.run_id,
                "source": "crawler",
                "source_revision": self.extractor.source_revision,
                "goal": goal,
                "interaction_ids": interaction_ids,
                "start_state_id": start_state_id,
                "end_state_id": end_state_id,
                "discovery_source": "llm_goal" if used_llm_action else "deterministic",
            }
        )

    def _append_decision(
        self,
        *,
        step: int,
        goal: FlowGoal,
        source: ExtractedScreen,
        element_name: str | None,
        action: str,
        decision_source: str,
        rationale: str,
        blocked_count: int,
    ) -> None:
        entry = {
            "step": step,
            "goal": goal.key,
            "screen_route": source.screen.route_pattern,
            "element_name": element_name,
            "action": action,
            "source": decision_source,
            "rationale": rationale,
            "blocked_count": blocked_count,
        }
        self.decision_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.decision_log_path.open("a", encoding="utf-8") as decision_log:
            decision_log.write(json.dumps(entry, sort_keys=True) + "\n")

    def _save_flow_result(
        self,
        flow: UserFlow,
        goal: FlowGoal,
        succeeded: bool,
        actions_used: int,
    ) -> None:
        result_path = (
            self.store.root
            / "records"
            / "flow_results"
            / f"{flow.id.replace(':', '_')}.json"
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "flow_id": flow.id,
                    "key": goal.key,
                    "succeeded": succeeded,
                    "actions_used": actions_used,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )


__all__ = ["DEFAULT_GOALS", "CrawlAgent", "FlowGoal"]
