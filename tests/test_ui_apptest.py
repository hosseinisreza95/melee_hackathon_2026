"""Runs the Streamlit app headlessly (streamlit.testing AppTest) against the fixture API for every page and every
language, and asserts that no page raises. HTTP calls from the UI are routed to the FastAPI TestClient, so no
server or network is needed. This is the 'switching language must never break anything' guarantee."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lpc_regwatch.ui.i18n import LANGS, S, tr  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "src" / "lpc_regwatch" / "ui" / "app.py"
PAGES = ["page.home", "page.compare", "page.map", "page.sisters", "page.watch", "page.registry", "page.sources"]


def test_every_key_has_all_three_languages():
    missing = [(k, lang) for k, v in S.items() for lang in LANGS if not v.get(lang)]
    assert missing == []
    assert tr("pt", "page.home") == "Assistente & visão geral" and tr("xx", "page.home") == "Assistant & vue d'ensemble" and tr("en", "no.such.key") == "no.such.key"
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
    expected = {"page.home": "home.title", "page.compare": "cmp.title", "page.map": "map.title", "page.sisters": "sis.title",
                "page.watch": "watch.title", "page.registry": "reg.title", "page.sources": "src.title"}[page]
    assert title == tr(lang, expected)
    # the disclaimer is on every page, in the selected language
    assert any(tr(lang, "disclaimer") in (m.value or "") for m in at.markdown)


def test_single_language_control_switches_every_page(ui_http):
    """One control (top-right menu) for the whole app: switching it re-renders the current page in the new language,
    and the question page has no second language selector."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=60)
    at.session_state["page"] = "page.compare"
    at.run()
    assert not at.exception
    ctrls = [c for c in at.segmented_control if c.key == "lang_ctl"]
    assert len(ctrls) == 1 and len(at.segmented_control) == 1  # the only segmented control is the language one
    assert not [r for r in at.radio if list(r.options) == list(LANGS)]  # no second language selector anywhere
    assert at.title[0].value == tr("fr", "cmp.title")
    ctrls[0].set_value("pt").run()
    assert not at.exception
    assert at.session_state["lang"] == "pt" and at.session_state["page"] == "page.compare"  # same page, new language
    assert at.title[0].value == tr("pt", "cmp.title")
    # deselecting the control (single mode allows an empty selection) keeps the current language
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    at.segmented_control(key="lang_ctl").set_value(None).run()
    assert not at.exception and at.session_state["lang"] == "fr" and at.title[0].value == tr("fr", "home.title")


def test_chat_assistant_keeps_the_thread(ui_http):
    """Home page: map + conversational assistant. A follow-up without a product name is answered about the previous product."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=90)
    at.run()
    assert not at.exception
    assert at.chat_message and tr("fr", "chat.hello")[:20] in at.chat_message[0].markdown[0].value
    at.chat_input[0].set_value("LALSTOP G46 WG est-il homologué au Canada ?").run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    chat = at.session_state["chat"]
    assert [m["role"] for m in chat] == ["user", "assistant"] and chat[1]["ans"]["context"]["productIds"] == ["P-LPC-G46"]
    assert len(at.chat_message) == 2  # the greeting is replaced by the two turns
    at.chat_input[0].set_value("Et en France ?").run()
    assert not at.exception, [str(e.value)[:300] for e in at.exception]
    ans = at.session_state["chat"][-1]["ans"]
    assert ans["context"]["productIds"] == ["P-LPC-G46"] and ans["context"]["countries"] == ["FR"]
    assert ans["structured"]["caveats"][0].startswith("Contexte repris de la conversation : LALSTOP G46 WG")
    assert [f["registrationNumber"] for f in ans["facts"] if f["type"] == "registration"] == ["2230771"]
    assert len(at.chat_message) == 4 and len(at.dataframe) >= 1
    # the suggestion pills offer follow-ups about the same product
    sugg = [p for p in at.pills if p.key and p.key.startswith("chat_sugg_")]
    assert sugg and tr("fr", "chat.fu_uses") in list(sugg[0].options)
