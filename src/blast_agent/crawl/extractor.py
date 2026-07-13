"""Extraction of validated crawl contracts from a settled Playwright page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Page

from blast_agent.contracts import ScreenState, UIElement, stable_id

from .state_identity import (
    canonicalize_url,
    route_pattern,
    screen_id_for,
    visible_text_hash,
)


_INTERACTIVE_ELEMENT_SCRIPT = r"""
() => Array.from(document.querySelectorAll(
  'a[href], button, input, select, textarea, [role=button], [role=link], ' +
  '[role=tab], [role=menuitem], form'
)).map((element) => {
  const tag = element.tagName.toLowerCase();
  const inputType = tag === 'input'
    ? (element.getAttribute('type') || 'text').toLowerCase()
    : '';
  const inferredRoles = {
    a: 'link',
    button: 'button',
    input: (inputType === 'submit' || inputType === 'button') ? 'button' : 'textbox',
    select: 'combobox',
    textarea: 'textbox',
    form: 'form',
  };
  const role = element.getAttribute('role') || inferredRoles[tag] || tag;
  const candidates = [
    element.getAttribute('aria-label'),
    (element.innerText || '').trim().slice(0, 80),
    element.getAttribute('placeholder'),
    tag === 'input' && inputType === 'submit' ? element.value : null,
    element.getAttribute('title'),
    element.getAttribute('name'),
    tag,
  ];
  const name = candidates.find((candidate) => candidate && candidate.trim()) || tag;
  const attrs = {};
  for (const attribute of [
    'href', 'id', 'class', 'name', 'type', 'data-testid', 'action', 'method'
  ]) {
    if (element.hasAttribute(attribute)) {
      attrs[attribute] = element.getAttribute(attribute);
    }
  }
  const rect = element.getBoundingClientRect();
  return {
    tag,
    role,
    name,
    attrs,
    bounds: [rect.x, rect.y, rect.width, rect.height],
    visible: element.offsetParent !== null || rect.width * rect.height > 0,
  };
}).filter((element) => element.visible)
"""


@dataclass(frozen=True, slots=True)
class ExtractedScreen:
    """Artifacts and validated records captured from one browser state."""

    screen: ScreenState
    elements: list[UIElement]
    html: str
    screenshot_png: bytes
    visible_text: str


class PageExtractor:
    """Convert a load-settled Playwright page into deterministic contracts."""

    def __init__(
        self,
        run_id: str,
        source_revision: str,
        base_url: str = "http://localhost:3000",
    ) -> None:
        self.run_id = run_id
        self.source_revision = source_revision
        self.base_url = base_url

    def extract(self, page: Page) -> ExtractedScreen:
        html = page.content()
        visible_text = page.inner_text("body")
        title = page.title()
        url = canonicalize_url(page.url)
        text_hash = visible_text_hash(visible_text)
        screen_id = screen_id_for(url, text_hash)
        file_id = screen_id.replace(":", "_")

        screen = ScreenState.model_validate(
            {
                "id": screen_id,
                "run_id": self.run_id,
                "source": "crawler",
                "source_revision": self.source_revision,
                "url": url,
                "route_pattern": route_pattern(url),
                "title": title,
                "dom_artifact": f"dom/{file_id}.html",
                "screenshot_artifact": f"screenshots/{file_id}.png",
                "visible_text_hash": text_hash,
            }
        )

        raw_elements: list[dict[str, Any]] = page.evaluate(_INTERACTIVE_ELEMENT_SCRIPT)
        elements = self._validated_elements(screen_id, raw_elements)
        screenshot_png = page.screenshot(full_page=True)
        return ExtractedScreen(
            screen=screen,
            elements=elements,
            html=html,
            screenshot_png=screenshot_png,
            visible_text=visible_text,
        )

    def _validated_elements(
        self, screen_id: str, raw_elements: list[dict[str, Any]]
    ) -> list[UIElement]:
        collision_counts: dict[tuple[str, str], int] = {}
        used_names: set[tuple[str, str]] = set()
        elements: list[UIElement] = []

        for raw in raw_elements:
            role = str(raw["role"])
            original_name = str(raw["name"])
            natural_key = (role.strip().casefold(), original_name.strip().casefold())
            occurrence = collision_counts.get(natural_key, 0) + 1
            name = original_name if occurrence == 1 else f"{original_name} #{occurrence}"
            while (role.strip().casefold(), name.strip().casefold()) in used_names:
                occurrence += 1
                name = f"{original_name} #{occurrence}"
            collision_counts[natural_key] = occurrence
            used_names.add((role.strip().casefold(), name.strip().casefold()))

            attributes = {str(key): str(value) for key, value in raw["attrs"].items()}
            locator_evidence = self._locator_evidence(
                tag=str(raw["tag"]),
                role=role,
                name=name,
                attributes=attributes,
            )
            element_id = stable_id("element", screen_id, role, name)
            elements.append(
                UIElement.model_validate(
                    {
                        "id": element_id,
                        "run_id": self.run_id,
                        "source": "crawler",
                        "source_revision": self.source_revision,
                        "screen_id": screen_id,
                        "role": role,
                        "name": name,
                        "locator_evidence": locator_evidence,
                        "attributes": attributes,
                        "bounds": tuple(float(value) for value in raw["bounds"]),
                    }
                )
            )

        return elements

    @staticmethod
    def _locator_evidence(
        *, tag: str, role: str, name: str, attributes: dict[str, str]
    ) -> dict[str, str]:
        evidence: dict[str, str] = {}
        if test_id := attributes.get("data-testid"):
            evidence["testid"] = test_id
        if element_id := attributes.get("id"):
            evidence["css"] = f"#{element_id}"
        elif input_name := attributes.get("name"):
            if tag in {"input", "select", "textarea"}:
                evidence["css"] = f'{tag}[name="{input_name}"]'
        if role == "link" and (href := attributes.get("href")):
            evidence["href"] = href
        if name:
            evidence["text"] = name
        if not evidence:
            evidence["css"] = tag
        return evidence


__all__ = ["ExtractedScreen", "PageExtractor"]
