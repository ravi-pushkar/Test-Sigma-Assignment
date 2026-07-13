"""Command-line entry points for blast-agent."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from playwright.sync_api import sync_playwright
import typer

from blast_agent.code_index import (
    PR_META,
    acquire_diff,
    index_pr,
    restore_diff_snapshot,
)
from blast_agent.crawl import (
    DEFAULT_GOALS,
    ArtifactStore,
    CrawlAgent,
    CrawlRules,
    FallbackPolicy,
    LLMPolicy,
    PageExtractor,
)
from blast_agent.evals.runner import evaluate
from blast_agent.llm import LLMUnavailable, client_from_env
from blast_agent.linking import link_run
from blast_agent.graph import GraphWriter, record_absences
from blast_agent.ingest import CachedLLM, ingest_docs, restore_docs_snapshots
from blast_agent.reasoning import compute_impacts, fetch_entity_lookups, render_report


SOURCE_REVISION = "daf581fa892320f5d495b4073d6812b0ad8ddfc8"

SLUG_TO_URI = {
    "issues-prs_labels.html": "https://docs.gitea.com/1.27/usage/issues-prs/labels",
    "issues-prs_automatically-linked-references.html": (
        "https://docs.gitea.com/1.27/usage/issues-prs/automatically-linked-references"
    ),
    "issues-prs_issue-pull-request-templates.html": (
        "https://docs.gitea.com/1.27/usage/issues-prs/issue-pull-request-templates"
    ),
}

app = typer.Typer(help="Autonomous application crawl and trace agent.")


def _default_run_id() -> str:
    return datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")


@app.command()
def crawl(
    base_url: str = typer.Option("http://localhost:3000", "--base-url"),
    run_id: str = typer.Option(_default_run_id(), "--run-id"),
    goals: str = typer.Option("F1,F2,F3", "--goals"),
    no_llm: bool = typer.Option(False, "--no-llm"),
    headed: bool = typer.Option(False, "--headed"),
    max_seconds: float = typer.Option(900.0, "--max-seconds"),
) -> None:
    """Exercise selected Gitea user flows in one browser session."""

    requested_keys = [key.strip().upper() for key in goals.split(",") if key.strip()]
    known_goals = {goal.key: goal for goal in DEFAULT_GOALS}
    unknown = [key for key in requested_keys if key not in known_goals]
    if unknown or not requested_keys:
        allowed = ", ".join(known_goals)
        invalid = ", ".join(unknown) if unknown else "empty goal list"
        raise typer.BadParameter(f"invalid goals ({invalid}); choose from {allowed}")
    selected_goals = [known_goals[key] for key in requested_keys]

    policy = FallbackPolicy()
    if not no_llm:
        try:
            policy = LLMPolicy(client_from_env())
        except LLMUnavailable as exc:
            typer.echo(f"Warning: {exc}; using deterministic fallback policy.", err=True)

    run_root = Path("data/runs") / run_id
    store = ArtifactStore(run_root)
    extractor = PageExtractor(run_id, SOURCE_REVISION, base_url)
    agent = CrawlAgent(
        policy,
        store,
        extractor,
        CrawlRules(base_url),
        max_seconds=max_seconds,
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            flows = agent.run(page, selected_goals)
        finally:
            browser.close()

    any_failed = False
    for flow, goal in zip(flows, selected_goals, strict=True):
        result_path = (
            run_root
            / "records"
            / "flow_results"
            / f"{flow.id.replace(':', '_')}.json"
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        succeeded = bool(result["succeeded"])
        any_failed = any_failed or not succeeded
        typer.echo(
            f"{goal.key}: succeeded={str(succeeded).lower()} "
            f"actions={result['actions_used']}"
        )

    if any_failed:
        raise typer.Exit(code=1)


@app.command("index-code")
def index_code(
    run_id: str = typer.Option("code-index", "--run-id"),
    repo_dir: Path = typer.Option(Path("third_party/gitea"), "--repo-dir"),
    diff_file: Path = typer.Option(
        Path("data/raw/code/pr-37045.diff"), "--diff-file"
    ),
) -> None:
    """Index changed code symbols and UI anchors from a pull-request diff."""

    if not diff_file.is_file() and restore_diff_snapshot(diff_file):
        typer.echo("PR diff restored from committed fixture")

    if diff_file.is_file():
        diff_text = diff_file.read_text(encoding="utf-8")
    else:
        diff_text = acquire_diff(
            repo_dir, str(PR_META["base_sha"]), str(PR_META["head_sha"])
        )
    store = ArtifactStore(Path("data/runs") / run_id)
    summary = index_pr(repo_dir, diff_text, run_id, store)
    typer.echo(json.dumps(summary, sort_keys=True))


@app.command("ingest-docs")
def ingest_docs_command(
    run_id: str = typer.Option(..., "--run-id"),
    docs_dir: Path = typer.Option(Path("data/raw/docs"), "--docs-dir"),
    cache_dir: Path = typer.Option(Path("data/cache/llm"), "--cache-dir"),
    source_revision: str = typer.Option(SOURCE_REVISION, "--source-revision"),
) -> None:
    """Extract testable requirements from saved documentation pages."""

    if restore_docs_snapshots(docs_dir):
        typer.echo("docs snapshots restored from committed fixtures")

    snapshot_paths: list[tuple[Path, str]] = []
    for path in sorted(docs_dir.glob("*.html")):
        uri = SLUG_TO_URI.get(path.name)
        if uri is None:
            raise typer.BadParameter(
                f"no original URI mapping for documentation snapshot {path.name!r}"
            )
        snapshot_paths.append((path, uri))
    if not snapshot_paths:
        raise typer.BadParameter(f"no HTML snapshots found in {docs_dir}")

    try:
        client = client_from_env()
    except LLMUnavailable as exc:
        typer.echo(
            f"LLM unavailable ({exc}); attempting cache-only ingestion.",
            err=True,
        )
        client = None

    try:
        counts = ingest_docs(
            snapshot_paths,
            CachedLLM(client, cache_dir),
            run_id,
            source_revision,
            ArtifactStore(Path("data/runs") / run_id),
        )
    except LLMUnavailable as exc:
        typer.echo(f"Unable to ingest docs: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(counts, sort_keys=True))


@app.command()
def link(
    run_id: str = typer.Option(..., "--run-id"),
    code_run_id: str = typer.Option("code-index", "--code-run-id"),
    docs_run_id: str | None = typer.Option(None, "--docs-run-id"),
) -> None:
    """Generate deterministic links between requirements, UI, and code."""

    counts = link_run(
        Path("data/runs") / run_id,
        run_id,
        Path("data/runs") / code_run_id,
        Path("data/runs") / docs_run_id if docs_run_id is not None else None,
    )
    typer.echo(json.dumps(counts, sort_keys=True))


@app.command("load-graph")
def load_graph(
    run_id: str = typer.Option(..., "--run-id"),
    code_run_id: str = typer.Option("code-index", "--code-run-id"),
    docs_run_id: str | None = typer.Option(None, "--docs-run-id"),
) -> None:
    """Load crawl and code artifacts into Neo4j."""

    run_root = Path("data/runs") / run_id
    screen_paths = sorted((run_root / "records" / "screens").glob("*.json"))
    if not screen_paths:
        raise typer.BadParameter(f"run {run_id!r} has no screen records")
    screen = json.loads(screen_paths[0].read_text(encoding="utf-8"))
    source_revision = str(screen["source_revision"])
    docs_run_root = (
        Path("data/runs") / docs_run_id if docs_run_id is not None else None
    )
    record_absences(run_root, run_id, source_revision, docs_run_root)

    writer = GraphWriter.from_env()
    try:
        writer.load_run(
            run_root,
            Path("data/runs") / code_run_id,
            docs_run_root,
        )
        typer.echo(json.dumps(writer.counts(), sort_keys=True))
    finally:
        writer.driver.close()


def _record_dicts(run_root: Path, kind: str) -> list[dict]:
    record_dir = run_root / "records" / kind
    if not record_dir.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(record_dir.glob("*.json"))
    ]


def _local_entity_lookups(
    run_root: Path, docs_run_root: Path | None = None
) -> dict[str, dict]:
    requirements_root = docs_run_root if docs_run_root is not None else run_root
    return {
        "elements": {
            str(record["id"]): str(record.get("name") or "Unnamed element")
            for record in _record_dicts(run_root, "elements")
        },
        "screens": {
            str(record["id"]): str(record.get("route_pattern") or "Unknown route")
            for record in _record_dicts(run_root, "screens")
        },
        "flows": {
            str(record["id"]): {
                "goal": str(record.get("goal") or "Unnamed flow"),
                "step_count": len(record.get("interaction_ids") or []),
            }
            for record in _record_dicts(run_root, "flows")
        },
        "requirements": {
            str(record["id"]): str(
                record.get("statement") or "Unnamed requirement"
            )
            for record in _record_dicts(requirements_root, "requirements")
        },
    }


@app.command("analyze-pr")
def analyze_pr(
    run_id: str = typer.Option(..., "--run-id"),
    code_run_id: str = typer.Option("code-index", "--code-run-id"),
    docs_run_id: str | None = typer.Option(None, "--docs-run-id"),
    pr_number: int = typer.Option(37045, "--pr"),
    out: Path | None = typer.Option(None, "--out"),
) -> None:
    """Compute, persist, and render a deterministic PR blast-radius report."""

    run_root = Path("data/runs") / run_id
    screens = _record_dicts(run_root, "screens")
    if not screens:
        raise typer.BadParameter(f"run {run_id!r} has no screen records")
    source_revision = str(screens[0]["source_revision"])
    report_path = out or run_root / "report" / "blast-radius.md"
    docs_run_root = (
        Path("data/runs") / docs_run_id if docs_run_id is not None else None
    )

    writer = GraphWriter.from_env()
    try:
        findings, unmapped = compute_impacts(
            writer.driver, pr_number, run_id, source_revision
        )
        graph_lookups = fetch_entity_lookups(writer.driver, findings)
    finally:
        writer.driver.close()

    store = ArtifactStore(run_root)
    for finding in findings:
        store.save_record(finding, "impacts")

    local_lookups = _local_entity_lookups(run_root, docs_run_root)
    for kind, values in local_lookups.items():
        graph_lookups[kind].update(values)

    stats = {
        kind: len(_record_dicts(run_root, kind))
        for kind in ("screens", "elements", "flows")
    }
    stats["requirements"] = len(
        _record_dicts(docs_run_root or run_root, "requirements")
    )
    changes = [
        record
        for record in _record_dicts(Path("data/runs") / code_run_id, "pr_changes")
        if int(record.get("pr_number", -1)) == pr_number
    ]
    pr = {
        **PR_META,
        "pr_number": pr_number,
        "url": f"https://github.com/go-gitea/gitea/pull/{pr_number}",
        "files_changed": len(changes),
    }
    report = render_report(
        findings,
        unmapped,
        {
            "pr": pr,
            "run_id": run_id,
            "source_revision": source_revision,
            "generated_at": datetime.now(UTC).isoformat(),
            "crawl_stats": stats,
            "entity_lookups": graph_lookups,
        },
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    severity_counts = {
        severity: sum(finding.severity == severity for finding in findings)
        for severity in ("high", "medium", "low")
    }
    typer.echo(
        json.dumps(
            {
                "findings": len(findings),
                **severity_counts,
                "unmapped": len(unmapped),
                "report_path": str(report_path),
            },
            sort_keys=True,
        )
    )


@app.command("eval")
def eval_command(
    run_id: str = typer.Option(..., "--run-id"),
    code_run_id: str = typer.Option("code-index", "--code-run-id"),
    docs_run_id: str | None = typer.Option(None, "--docs-run-id"),
    stability_run_ids: str | None = typer.Option(None, "--stability-run-ids"),
    gold: Path = typer.Option(
        Path("tests/fixtures/goldens/gold_set.json"), "--gold"
    ),
) -> None:
    """Evaluate persisted runs against the hand-labeled golden set."""

    runs_root = Path("data/runs")
    stability_roots = [
        runs_root / item.strip()
        for item in (stability_run_ids or "").split(",")
        if item.strip()
    ]
    verdict = evaluate(
        runs_root / run_id,
        runs_root / code_run_id,
        runs_root / docs_run_id if docs_run_id is not None else None,
        gold,
        stability_roots,
    )
    typer.echo(json.dumps(verdict, indent=2, sort_keys=True))
    if not verdict["overall_pass"]:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
