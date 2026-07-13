"""Live extraction coverage against the local Gitea instance."""

from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import sync_playwright

from blast_agent.contracts import ScreenState
from blast_agent.crawl import ArtifactStore, PageExtractor


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


def test_extracts_and_persists_live_login_page(tmp_path: Path) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(f"{BASE_URL}/user/login", wait_until="networkidle")
            extracted = PageExtractor(
                run_id="it-run",
                source_revision=SOURCE_REVISION,
            ).extract(page)
        finally:
            browser.close()

    assert extracted.screen.route_pattern == "/user/login"
    assert isinstance(extracted.screen, ScreenState)
    assert any(
        element.role == "textbox"
        and "user_name" in element.locator_evidence.get("css", "")
        for element in extracted.elements
    )
    assert any("Sign In" in element.name for element in extracted.elements)
    assert any(
        element.locator_evidence.get("href") == "https://about.gitea.com"
        for element in extracted.elements
    )
    assert len({element.id for element in extracted.elements}) == len(extracted.elements)

    store = ArtifactStore(tmp_path)
    store.save_screen(extracted)
    store.save_elements(extracted.elements)

    dom_path = tmp_path / extracted.screen.dom_artifact
    screenshot_path = tmp_path / extracted.screen.screenshot_artifact
    screen_record = (
        tmp_path
        / "records"
        / "screens"
        / f"{extracted.screen.id.replace(':', '_')}.json"
    )
    element_records = list((tmp_path / "records" / "elements").glob("*.json"))

    assert dom_path.is_file() and dom_path.stat().st_size > 0
    assert screenshot_path.is_file() and screenshot_path.stat().st_size > 0
    assert screen_record.is_file() and screen_record.stat().st_size > 0
    assert element_records
    assert all(path.stat().st_size > 0 for path in element_records)
