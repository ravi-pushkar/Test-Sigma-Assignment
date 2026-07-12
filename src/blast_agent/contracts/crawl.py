"""Contracts produced while crawling application user interfaces."""

from datetime import datetime
from typing import Literal

from .common import ContractRecord


class ScreenState(ContractRecord):
    url: str
    route_pattern: str
    title: str
    dom_artifact: str
    screenshot_artifact: str
    visible_text_hash: str


class UIElement(ContractRecord):
    screen_id: str
    role: str
    name: str
    locator_evidence: dict[str, str]
    attributes: dict[str, str] = {}
    bounds: tuple[float, float, float, float] | None


class Interaction(ContractRecord):
    source_state_id: str
    target_state_id: str
    element_id: str
    action: Literal["click", "fill", "select", "navigate", "submit"]
    input_class: str | None
    timestamp: datetime
    success: bool


class UserFlow(ContractRecord):
    goal: str
    interaction_ids: list[str]
    start_state_id: str
    end_state_id: str
    discovery_source: Literal["llm_goal", "deterministic", "manual"]
