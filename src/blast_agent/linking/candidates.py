"""Pure, deterministic cross-layer link candidate generators."""

from __future__ import annotations

from dataclasses import dataclass, field

from blast_agent.contracts import CodeSymbol, Requirement, ScreenState, UIElement


@dataclass(frozen=True)
class Signal:
    """One piece of evidence supporting a candidate link."""

    kind: str
    evidence: str
    weight: float


@dataclass
class LinkCandidate:
    """A possible trace link together with its supporting signals."""

    source_entity_id: str
    target_entity_id: str
    link_type: str
    signals: list[Signal] = field(default_factory=list)


CandidateKey = tuple[str, str, str]


def _add_signal(
    candidates: dict[CandidateKey, LinkCandidate],
    source_entity_id: str,
    target_entity_id: str,
    link_type: str,
    signal: Signal,
) -> None:
    key = (source_entity_id, target_entity_id, link_type)
    candidate = candidates.setdefault(
        key,
        LinkCandidate(source_entity_id, target_entity_id, link_type),
    )
    candidate.signals.append(signal)


def _ui_link_type(symbol: CodeSymbol) -> str | None:
    if (
        symbol.kind in {"template", "template_block", "ts_module"}
        or symbol.file.endswith(".ts")
    ):
        return "rendered_by"
    if symbol.kind in {"function", "method", "type", "route"}:
        return "handled_by"
    return None


def ui_code_candidates(
    elements: list[UIElement],
    screens: list[ScreenState],
    symbols: list[CodeSymbol],
) -> list[LinkCandidate]:
    """Match concrete UI evidence to anchors mined from code symbols."""

    candidates: dict[CandidateKey, LinkCandidate] = {}
    for symbol in symbols:
        link_type = _ui_link_type(symbol)
        if link_type is None:
            continue

        for anchor in symbol.ui_anchors:
            prefix, separator, value = anchor.partition(":")
            if not separator:
                continue

            if prefix == "text":
                normalized = value.strip().casefold()
                for element in elements:
                    if element.name.strip().casefold() == normalized:
                        _add_signal(
                            candidates,
                            element.id,
                            symbol.id,
                            link_type,
                            Signal("text-exact", f"text:{value}", 0.65),
                        )
            elif prefix == "href":
                for element in elements:
                    if element.attributes.get("href") == value:
                        _add_signal(
                            candidates,
                            element.id,
                            symbol.id,
                            link_type,
                            Signal("href-exact", f"href:{value}", 0.7),
                        )
            elif prefix == "css" and value.startswith("#"):
                for element in elements:
                    if element.locator_evidence.get("css") == value:
                        _add_signal(
                            candidates,
                            element.id,
                            symbol.id,
                            link_type,
                            Signal("css-id", f"css:{value}", 0.55),
                        )
            elif prefix == "route" and link_type == "handled_by":
                for screen in screens:
                    if screen.route_pattern == value:
                        _add_signal(
                            candidates,
                            screen.id,
                            symbol.id,
                            "handled_by",
                            Signal("route-exact", f"route:{value}", 0.75),
                        )
            # template_name anchors cannot be resolved statically.

    return list(candidates.values())


def requirement_ui_candidates(
    requirements: list[Requirement],
    elements: list[UIElement],
    screens: list[ScreenState],
) -> list[LinkCandidate]:
    """Match requirement clues and object words to observed UI elements."""

    del screens  # Screen text is represented only by a hash in the current contract.
    candidates: dict[CandidateKey, LinkCandidate] = {}
    for requirement in requirements:
        object_words = [
            word.casefold()
            for word in requirement.object.split()
            if len(word) > 3
        ]
        for element in elements:
            element_name = element.name.strip().casefold()
            for clue in requirement.acceptance_clues:
                normalized_clue = clue.strip().casefold()
                if normalized_clue and normalized_clue == element_name:
                    _add_signal(
                        candidates,
                        requirement.id,
                        element.id,
                        "implements",
                        Signal("clue-element-exact", clue, 0.6),
                    )
                elif normalized_clue and normalized_clue in element_name:
                    _add_signal(
                        candidates,
                        requirement.id,
                        element.id,
                        "implements",
                        Signal("clue-element-sub", clue, 0.35),
                    )

            if object_words and all(word in element_name for word in object_words):
                _add_signal(
                    candidates,
                    requirement.id,
                    element.id,
                    "implements",
                    Signal("object-words", requirement.object, 0.3),
                )

    return list(candidates.values())


__all__ = [
    "LinkCandidate",
    "Signal",
    "requirement_ui_candidates",
    "ui_code_candidates",
]
