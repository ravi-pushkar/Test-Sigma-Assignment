"""Render QA-readable blast-radius Markdown from deterministic findings."""

from __future__ import annotations

from collections import OrderedDict
import re
from typing import Any

from jinja2 import Environment, FileSystemLoader

from blast_agent.contracts import ImpactFinding


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_BADGES = {"high": "🔴 HIGH", "medium": "🟠 MEDIUM", "low": "🟡 LOW"}


def _sanitize_prose(value: Any, max_length: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_length is not None and len(text) > max_length:
        return f"{text[: max_length - 1]}…"
    return text


def _ordered_entity_ids(
    finding: ImpactFinding, lookup: dict[str, Any]
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for path in finding.path_entity_ids:
        for entity_id in path:
            if entity_id in lookup and entity_id not in seen:
                ordered.append(entity_id)
                seen.add(entity_id)
    for entity_id in finding.affected_entity_ids:
        if entity_id in lookup and entity_id not in seen:
            ordered.append(entity_id)
            seen.add(entity_id)
    return ordered


def _element_labels(
    entity_ids: list[str], lookup: dict[str, Any], limit: int = 6
) -> tuple[list[str], int]:
    counts: OrderedDict[str, int] = OrderedDict()
    for entity_id in entity_ids:
        name = _sanitize_prose(lookup[entity_id], max_length=40) or "Unnamed element"
        counts[name] = counts.get(name, 0) + 1
    labels = [
        f"{name} ({count} places)" if count > 1 else name
        for name, count in counts.items()
    ]
    return labels[:limit], max(0, len(labels) - limit)


def _route_labels(
    entity_ids: list[str], lookup: dict[str, Any], limit: int = 5
) -> tuple[list[str], int]:
    routes = list(
        OrderedDict.fromkeys(
            _sanitize_prose(lookup[entity_id]) or "Unknown route"
            for entity_id in entity_ids
        )
    )
    return routes[:limit], max(0, len(routes) - limit)


def _lookup_tables(context: dict[str, Any]) -> dict[str, dict]:
    nested = context.get("entity_lookups") or {}
    aliases = {
        "elements": "element_names",
        "screens": "screen_routes",
        "flows": "flow_goals",
        "requirements": "requirement_statements",
    }
    tables = {
        key: dict(
            context.get(key)
            or context.get(alias)
            or nested.get(key)
            or nested.get(alias)
            or {}
        )
        for key, alias in aliases.items()
    }
    step_counts = dict(
        context.get("flow_step_counts")
        or nested.get("flow_step_counts")
        or {}
    )
    for flow_id, value in list(tables["flows"].items()):
        if not isinstance(value, dict):
            tables["flows"][flow_id] = {
                "goal": value,
                "step_count": step_counts.get(flow_id, 0),
            }
    return tables


def _flow_details(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "goal": _sanitize_prose(value.get("goal")) or "Unnamed flow",
            "step_count": int(value.get("step_count") or 0),
        }
    return {"goal": _sanitize_prose(value) or "Unnamed flow", "step_count": 0}


def render_report(
    findings: list[ImpactFinding],
    unmapped: list[dict],
    context: dict,
) -> str:
    """Render a Markdown report without deriving claims beyond finding fields."""

    lookups = _lookup_tables(context)
    ordered = sorted(
        findings, key=lambda item: (_SEVERITY_ORDER[item.severity], item.id)
    )
    finding_views: list[dict[str, Any]] = []
    affected_element_ids: set[str] = set()
    affected_screen_ids: set[str] = set()
    affected_flow_ids: set[str] = set()
    affected_requirement_ids: set[str] = set()

    for finding in ordered:
        entity_ids = set(finding.affected_entity_ids)
        element_ids = _ordered_entity_ids(finding, lookups["elements"])
        screen_ids = _ordered_entity_ids(finding, lookups["screens"])
        flow_ids = _ordered_entity_ids(finding, lookups["flows"])
        requirement_ids = _ordered_entity_ids(finding, lookups["requirements"])
        affected_element_ids.update(element_ids)
        affected_screen_ids.update(screen_ids)
        affected_flow_ids.update(flow_ids)
        affected_requirement_ids.update(requirement_ids)

        evidence_paths = finding.path_entity_ids or [
            [finding.changed_symbol_id, entity_id]
            for entity_id in finding.affected_entity_ids
        ]
        element_names, element_names_more = _element_labels(
            element_ids, lookups["elements"]
        )
        routes, routes_more = _route_labels(screen_ids, lookups["screens"])
        finding_views.append(
            {
                "badge": _BADGES[finding.severity],
                "severity": finding.severity,
                "file": finding.summary or "unknown file",
                "element_names": element_names,
                "element_names_more": element_names_more,
                "routes": routes,
                "routes_more": routes_more,
                "flows": [
                    _flow_details(lookups["flows"][key]) for key in flow_ids
                ],
                "confidence_percent": round(finding.confidence * 100),
                "evidence": [" → ".join(path) for path in evidence_paths[:5]],
                "evidence_more": max(0, len(evidence_paths) - 5),
            }
        )

    affected_flows = [
        _flow_details(lookups["flows"][key]) for key in sorted(affected_flow_ids)
    ]
    affected_requirements = [
        str(lookups["requirements"][key])
        for key in sorted(affected_requirement_ids)
    ]
    pr = dict(context.get("pr") or context.get("pr_meta") or {})
    for key in (
        "pr_number",
        "title",
        "base_sha",
        "head_sha",
        "merge_commit_sha",
        "url",
        "files_changed",
    ):
        if key not in pr and key in context:
            pr[key] = context[key]
    pr["pr_number"] = pr.get("pr_number", "unknown")
    pr["title"] = pr.get("title") or "Untitled pull request"
    pr["base_sha_short"] = str(pr.get("base_sha") or "unknown")[:8]
    pr["head_sha_short"] = str(pr.get("head_sha") or "unknown")[:8]
    pr["base_sha"] = pr.get("base_sha") or "unknown"
    pr["head_sha"] = pr.get("head_sha") or "unknown"
    pr["files_changed"] = int(pr.get("files_changed") or 0)

    stats = dict(context.get("crawl_stats") or {})
    stats = {
        "screens": int(stats.get("screens") or 0),
        "elements": int(stats.get("elements") or 0),
        "flows": int(stats.get("flows") or 0),
        "requirements": int(stats.get("requirements") or 0),
    }
    template_context = {
        "pr": pr,
        "findings": finding_views,
        "unmapped": sorted(
            unmapped,
            key=lambda item: (str(item.get("file") or ""), str(item.get("change_type") or "")),
        ),
        "run_id": str(context.get("run_id") or "unknown"),
        "source_revision": str(context.get("source_revision") or "unknown"),
        "generated_at": str(context.get("generated_at") or "unknown"),
        "crawl_stats": stats,
        "affected_element_count": len(affected_element_ids),
        "affected_screen_count": len(affected_screen_ids),
        "affected_flow_count": len(affected_flow_ids),
        "affected_flows": affected_flows,
        "affected_requirements": affected_requirements,
        "requirements_ingested": stats["requirements"] > 0,
    }
    environment = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=False,
        keep_trailing_newline=True,
    )
    return environment.get_template("blast_radius.md.j2").render(**template_context)


__all__ = ["render_report"]
