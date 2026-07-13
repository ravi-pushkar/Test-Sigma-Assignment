"""Live autonomous login-flow coverage against the local Gitea instance."""

import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import sync_playwright

from blast_agent.contracts import Interaction, ScreenState, UIElement, UserFlow
from blast_agent.crawl import (
    DEFAULT_GOALS,
    ArtifactStore,
    CrawlAgent,
    CrawlRules,
    FallbackPolicy,
    PageExtractor,
)


BASE_URL = "http://localhost:3000"
SOURCE_REVISION = "daf581fa892320f5d495b4073d6812b0ad8ddfc8"


def _gitea_is_reachable() -> bool:
    try:
        with urlopen(f"{BASE_URL}/api/healthz", timeout=2) as response:
            return 200 <= response.status < 500
    except (OSError, URLError):
        return False


pytestmark = pytest.mark.skipif(
    not _gitea_is_reachable(),
    reason="local Gitea is not reachable on localhost:3000",
)


def test_fallback_agent_completes_login_flow(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    agent = CrawlAgent(
        FallbackPolicy(),
        store,
        PageExtractor("agent-it-run", SOURCE_REVISION, BASE_URL),
        CrawlRules(BASE_URL),
        decision_log_path=tmp_path / "decisions.jsonl",
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            flows = agent.run(page, [DEFAULT_GOALS[0]])
        finally:
            browser.close()

    assert len(flows) == 1
    flow = flows[0]
    sidecar_path = (
        tmp_path
        / "records"
        / "flow_results"
        / f"{flow.id.replace(':', '_')}.json"
    )
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["succeeded"] is True
    assert len(flow.interaction_ids) >= 2

    decision_lines = (tmp_path / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(decision_lines) >= 2
    assert all(isinstance(json.loads(line), dict) for line in decision_lines)

    model_by_directory = {
        "screens": ScreenState,
        "elements": UIElement,
        "interactions": Interaction,
        "flows": UserFlow,
    }
    for directory, model in model_by_directory.items():
        record_paths = list((tmp_path / "records" / directory).glob("*.json"))
        assert record_paths
        for record_path in record_paths:
            record = model.model_validate_json(record_path.read_text(encoding="utf-8"))
            assert model.model_validate_json(record.model_dump_json()) == record
