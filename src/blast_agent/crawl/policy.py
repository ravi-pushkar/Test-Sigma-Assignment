"""Action-selection policies for goal-directed crawling."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Protocol
from urllib.parse import urlsplit

from blast_agent.contracts import ScreenState
from blast_agent.llm import GeminiClient


@dataclass(frozen=True, slots=True)
class RecipeStep:
    keyword: str = ""
    skip_if_route: str | None = None
    prefix: bool = False
    navigate_to: str | None = None


GOAL_RECIPES: dict[str, list[RecipeStep]] = {
    "sign in": [
        RecipeStep("sign in", skip_if_route="/user/login"),
        RecipeStep("user_name"),
        RecipeStep("password"),
        RecipeStep("sign in"),
    ],
    "create a new issue": [
        RecipeStep(
            "demo/demo-repo", skip_if_route="/{owner}/{repo}", prefix=True
        ),
        RecipeStep("new issue", skip_if_route="/{owner}/{repo}/issues/new"),
        RecipeStep("title"),
        RecipeStep("content"),
        RecipeStep("create issue"),
    ],
    "subscribe": [
        RecipeStep(navigate_to="/demo/demo-repo/issues/1"),
        RecipeStep("subscribe"),
        RecipeStep("watch"),
    ],
}


@dataclass(frozen=True, slots=True)
class CandidateAction:
    element_id: str
    role: str
    name: str
    href: str | None
    action: Literal["click", "fill", "submit", "navigate"]
    reason_blocked: str | None = None
    fill_value_key: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    element_id: str | None
    action: str | None
    rationale: str
    source: Literal["llm", "deterministic", "stop"]
    fill_value_key: str | None = None
    navigate_to: str | None = None


class ActionPolicy(Protocol):
    def decide(
        self,
        goal: str,
        screen: ScreenState,
        candidates: list[CandidateAction],
        trajectory: list[str],
    ) -> PolicyDecision: ...


class LLMPolicy:
    """Ask Gemini for one action, while enforcing local safety constraints."""

    RESPONSE_SCHEMA = {
        "type": "OBJECT",
        "properties": {
            "rationale": {"type": "STRING"},
            "index": {"type": "INTEGER"},
        },
        "required": ["rationale", "index"],
    }

    def __init__(
        self, client: GeminiClient, fallback: FallbackPolicy | None = None
    ) -> None:
        self.client = client
        self.fallback = fallback or FallbackPolicy()

    def decide(
        self,
        goal: str,
        screen: ScreenState,
        candidates: list[CandidateAction],
        trajectory: list[str],
    ) -> PolicyDecision:
        viable = [candidate for candidate in candidates if not candidate.reason_blocked]
        response = self.client.generate_json(
            self._prompt(goal, screen, viable, trajectory), self.RESPONSE_SCHEMA
        )
        index = response.get("index")
        rationale = str(response.get("rationale", ""))

        if index == -1:
            return PolicyDecision(None, None, rationale, "stop")
        if (
            isinstance(index, int)
            and not isinstance(index, bool)
            and 0 <= index < len(viable)
        ):
            chosen = viable[index]
            return PolicyDecision(
                chosen.element_id, chosen.action, rationale, "llm"
            )

        fallback = self.fallback.decide(goal, screen, viable, trajectory)
        fallback_rationale = (
            f"llm-out-of-range: {rationale}; deterministic-fallback: "
            f"{fallback.rationale}"
        )
        return PolicyDecision(
            fallback.element_id,
            fallback.action,
            fallback_rationale,
            fallback.source,
            fallback.fill_value_key,
            fallback.navigate_to,
        )

    @staticmethod
    def _prompt(
        goal: str,
        screen: ScreenState,
        candidates: list[CandidateAction],
        trajectory: list[str],
    ) -> str:
        lines = [
            f"Goal: {goal}",
            f"Current route: {screen.route_pattern}",
            f"Current title: {screen.title}",
            "Candidates:",
        ]
        lines.extend(
            f"{index}. role={candidate.role}; name={candidate.name}; "
            f"href={candidate.href or '-'}"
            for index, candidate in enumerate(candidates)
        )
        lines.append("Recent trajectory:")
        lines.extend(f"- {step}" for step in trajectory[-6:])
        lines.append(
            "First write your brief rationale, then give the index consistent with it. "
            "Choose the single next action that makes progress toward the goal. "
            "Navigation toward the right page counts as progress. Choose index -1 ONLY "
            "if the goal is already complete in the current state (verify against the "
            "screen title/route), never merely because no candidate directly accomplishes "
            "the goal in one step."
        )
        return "\n".join(lines)


class FallbackPolicy:
    """Select an action using stable goal hints and link-order fallbacks."""

    def __init__(
        self, goal_recipes: dict[str, list[RecipeStep]] | None = None
    ) -> None:
        self.goal_recipes = GOAL_RECIPES if goal_recipes is None else goal_recipes

    def decide(
        self,
        goal: str,
        screen: ScreenState,
        candidates: list[CandidateAction],
        trajectory: list[str],
    ) -> PolicyDecision:
        viable = [
            candidate
            for candidate in candidates
            if not candidate.reason_blocked
        ]
        recipe = self._recipe_for_goal(goal)
        if decision := self._decide_from_recipe(recipe, screen, candidates):
            return decision
        if screen.route_pattern == "/user/login" and recipe != GOAL_RECIPES["sign in"]:
            if decision := self._decide_from_recipe(
                GOAL_RECIPES["sign in"], screen, candidates
            ):
                return decision

        for candidate in viable:
            if candidate.role.casefold() == "link":
                return PolicyDecision(
                    candidate.element_id,
                    candidate.action,
                    "first unvisited non-blocked link rule",
                    "deterministic",
                )

        return PolicyDecision(
            None,
            None,
            "no viable unvisited candidate",
            "stop",
        )

    def _recipe_for_goal(self, goal: str) -> list[RecipeStep]:
        normalized_goal = goal.lower()
        for goal_phrase, recipe in self.goal_recipes.items():
            if goal_phrase in normalized_goal:
                return recipe
        if "watch" in normalized_goal:
            return self.goal_recipes.get("subscribe", [])
        return []

    @staticmethod
    def _decide_from_recipe(
        recipe: list[RecipeStep],
        screen: ScreenState,
        candidates: list[CandidateAction],
    ) -> PolicyDecision | None:
        for step in recipe:
            if step.navigate_to is not None:
                if (urlsplit(screen.url).path or "/") == step.navigate_to:
                    continue
                return PolicyDecision(
                    None,
                    "navigate",
                    f"recipe navigation to '{step.navigate_to}'",
                    "deterministic",
                    navigate_to=step.navigate_to,
                )
            if step.skip_if_route is not None:
                route_matches = (
                    screen.route_pattern.startswith(step.skip_if_route)
                    if step.prefix
                    else screen.route_pattern == step.skip_if_route
                )
                if route_matches:
                    continue
            keyword = step.keyword
            matches = [
                candidate
                for candidate in candidates
                if candidate.reason_blocked is None
                and not (
                    keyword in {"subscribe", "watch"}
                    and candidate.name.lower().startswith("un")
                )
                and (
                    keyword in candidate.name.lower()
                    or keyword in (candidate.href or "").lower()
                )
            ]
            if not matches:
                continue
            exact_name_matches = [
                candidate
                for candidate in matches
                if candidate.name.strip().casefold() == keyword.strip().casefold()
            ]
            if exact_name_matches:
                matches = exact_name_matches
            if keyword in {"user_name", "password", "title", "content"}:
                matches.sort(key=lambda candidate: candidate.action != "fill")
            else:
                matches.sort(
                    key=lambda candidate: candidate.action not in {"click", "submit"}
                )
                if keyword in {"submit", "create issue", "sign in"}:
                    matches.sort(
                        key=lambda candidate: not (
                            candidate.role.lower() == "button"
                            or candidate.action == "submit"
                        )
                    )
            chosen = matches[0]
            return PolicyDecision(
                chosen.element_id,
                chosen.action,
                f"recipe keyword '{keyword}' matched candidate '{chosen.name}'",
                "deterministic",
                chosen.fill_value_key,
            )
        return None

    @classmethod
    def _executed_pairs(cls, trajectory: list[str]) -> set[tuple[str, str]]:
        return {
            (role.casefold(), cls._base_name(name).casefold())
            for role, name, _href in cls._trajectory_entries(trajectory)
        }

    @classmethod
    def _trajectory_entries(
        cls, trajectory: list[str]
    ) -> list[tuple[str, str, str]]:
        entries: list[tuple[str, str, str]] = []
        for step in trajectory:
            match = re.search(
                r" \| role=(.*?) \| name=(.*?) \| href=(.*)$", step
            )
            if match:
                entries.append((match.group(1), match.group(2), match.group(3)))
        return entries

    @classmethod
    def _candidate_pair(cls, candidate: CandidateAction) -> tuple[str, str]:
        return (
            candidate.role.casefold(),
            cls._base_name(candidate.name).casefold(),
        )

    @staticmethod
    def _base_name(name: str) -> str:
        return re.sub(r" #\d+$", "", name)

__all__ = [
    "GOAL_RECIPES",
    "ActionPolicy",
    "CandidateAction",
    "FallbackPolicy",
    "LLMPolicy",
    "PolicyDecision",
    "RecipeStep",
]
