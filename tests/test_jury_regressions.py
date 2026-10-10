"""Regressions found by the jury-style test campaign (10/10): every question of the starter kit must get a usable answer."""
import pytest


@pytest.mark.parametrize("q,lang", [("Quand expire LALSTOP CONTANS WG ?", "fr"), ("When does LALSTOP G46 WG expire?", "en"),
                                    ("Quelles autorisations expirent dans les 12 prochains mois ?", "fr")])
def test_expiry_questions_never_crash(api_client, q, lang):
    r = api_client.post("/ask", json={"question": q, "language": lang})
    assert r.status_code == 200, r.text[:300]
    assert r.json()["answer"]


@pytest.mark.parametrize("q", ["Dans quels pays le produit pilote est-il homologué ?", "Quels produits pourraient être des produits sœurs ?",
                               "In which countries are the pilot products registered?"])
def test_kit_pilot_wording_resolves_the_pilots(api_client, q):
    d = api_client.post("/ask", json={"question": q, "language": "fr"}).json()
    if "pilot" in q:
        assert "ce produit" not in d["answer"] and "this product" not in d["answer"], d["answer"][:300]


def test_common_words_are_not_product_names(api_client):
    from lpc_regwatch.api.ask import STOP_WORDS
    assert {"entre", "deux", "comparer", "between", "pilote", "champs", "incertains"} <= STOP_WORDS


def test_withdrawn_use_is_never_authorised():
    from types import SimpleNamespace
    from lpc_regwatch.api.queries import use_withdrawn
    assert use_withdrawn(SimpleNamespace(use_status_original="Retrait"))
    assert use_withdrawn(SimpleNamespace(use_status_original="Withdrawn"))
    assert not use_withdrawn(SimpleNamespace(use_status_original="Autorisé"))
    assert not use_withdrawn(SimpleNamespace(use_status_original=None))


def test_withdrawn_use_warning_is_localized():
    from lpc_regwatch.api.ask import localize_warning
    w = "FR 2230771: 3 withdrawn use(s) excluded from the authorised uses."
    assert localize_warning(w, "fr") == "FR 2230771 : 3 usage(s) retiré(s) (« Retrait » dans la source) exclu(s) des usages autorisés."
    assert localize_warning(w, "en") == w
