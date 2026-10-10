"""Runs the Streamlit app headlessly (streamlit.testing AppTest) against the fixture API for every page and every
language, and asserts that no page raises. HTTP calls from the UI are routed to the FastAPI TestClient, so no
server or network is needed. This is the 'switching language must never break anything' guarantee."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lpc_regwatch.ui.i18n import LANGS, S, tr  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "src" / "lpc_regwatch" / "ui" / "app.py"
PAGES = ["page.overview", "page.compare", "page.map", "page.ask", "page.sisters", "page.watch", "page.registry", "page.sources"]


def test_every_key_has_all_three_languages():
    missing = [(k, lang) for k, v in S.items() for lang in LANGS if not v.get(lang)]
    assert missing == []
    assert tr("pt", "page.overview") == "Visão geral" and tr("xx", "page.overview") == "Vue d'ensemble" and tr("en", "no.such.key") == "no.such.key"
    assert tr("en", "warnings.n", n=3) == "3 warning(s) — missing or uncertain data"


@pytest.fixture()
def ui_http(api_client, monkeypatch):
    """Route httpx.get/post used by the UI to the FastAPI test client."""
    import httpx

    class _Resp:
        def __init__(self, r):
            self._r = r
            self.status_code = r.status_code
            self.content = r.content
            self.text = r.text

        def json(self):
            return self._r.json()

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(f"status {self.status_code}", request=None, response=None)

    def _get(url, params=None, timeout=None, **kw):
        return _Resp(api_client.get(url.replace("http://localhost:8000", ""), params=params))

    def _post(url, json=None, files=None, timeout=None, **kw):
        return _Resp(api_client.post(url.replace("http://localhost:8000", ""), json=json, files=files))

    monkeypatch.setattr(httpx, "get", _get)
    monkeypatch.setattr(httpx, "post", _post)
    monkeypatch.setenv("API_BASE_URL", "http://localhost:8000")
    return api_client


@pytest.mark.parametrize("lang", list(LANGS))
@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_in_every_language(ui_http, lang, page):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60)
    at.session_state["lang"] = lang
    at.session_state["page"] = page
    at.run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    title = at.title[0].value if at.title else ""
    expected = {"page.overview": "ov.title", "page.compare": "cmp.title", "page.map": "map.title", "page.ask": "ask.title", "page.sisters": "sis.title",
                "page.watch": "watch.title", "page.registry": "reg.title", "page.sources": "src.title"}[page]
    assert title == tr(lang, expected)
    # the disclaimer is on every page, in the selected language
    assert any(tr(lang, "disclaimer") in (m.value or "") for m in at.markdown)
