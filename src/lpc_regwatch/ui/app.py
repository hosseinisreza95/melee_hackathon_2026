"""Streamlit workbench — a THIN client of the API (no direct database access, no business logic here).

Why: cahier §16 forbids logic locked in the UI; everything shown comes from the same endpoints that
Power Platform / Copilot Studio would call. API base URL from env API_BASE_URL.
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx
import pandas as pd
import plotly.express as px
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
PILOTS = ["P-LPC-CONTANS", "P-LPC-G46", "P-LPC-M52"]
ALL_COUNTRIES = ["CA", "US", "FR", "BR", "DE", "BE", "MX", "UY"]
COUNTRY_LABEL = {"CA": "Canada", "US": "États-Unis", "FR": "France", "BR": "Brésil", "DE": "Allemagne", "BE": "Belgique", "MX": "Mexique", "UY": "Uruguay"}
ISO3 = {"CA": "CAN", "US": "USA", "FR": "FRA", "BR": "BRA", "DE": "DEU", "BE": "BEL", "MX": "MEX", "UY": "URY"}
STATUS_BADGE = {"active": "🟢 active", "expired": "🟠 expired", "withdrawn": "🔴 withdrawn", "pending": "🟡 pending", "unknown": "⚪ unknown"}

st.set_page_config(page_title="LPC Regulatory Watch", page_icon="🌱", layout="wide")


@st.cache_data(ttl=120, show_spinner=False)
def api_get(path: str, params: dict | None = None):
    r = httpx.get(f"{API}{path}", params=params, timeout=120)
    if r.status_code == 404:
        return {"__404__": r.json()}
    r.raise_for_status()
    return r.json()


def api_post(path: str, body: dict):
    r = httpx.post(f"{API}{path}", json=body, timeout=180)
    r.raise_for_status()
    return r.json()


def fmt_dt(s: str | None) -> str:
    if not s:
        return "—"
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return s


def disclaimer_box(text: str | None):
    st.caption("⚠️ " + (text or "This prototype is not an official regulatory source. Regulatory Affairs validation is required."))


def warnings_box(warnings: list[str]):
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} avertissement(s) — données manquantes ou incertaines", expanded=False):
            for w in warnings:
                st.markdown(f"- {w}")


# ---------------------------------------------------------------------------------- sidebar
try:
    health = api_get("/health")
except Exception as e:  # noqa: BLE001
    st.error(f"API injoignable sur {API} : {e}")
    st.stop()

st.sidebar.title("🌱 LPC Regulatory Watch")
st.sidebar.caption(f"API {API} · v{health.get('version')} · {health.get('registrations')} enregistrements · "
                   f"IA {'activée (' + str(health.get('aiProvider')) + ')' if health.get('aiEnabled') else 'désactivée (réponses déterministes)'}")
page = st.sidebar.radio("Vue", ["Comparaison", "Carte", "Question", "Produits sœurs & revue", "Veille (changements, échéances)", "Sources & qualité"])
products = api_get("/products", {"limit": 500})["items"]
prod_label = {p["productId"]: f"{p['commercialName']}  ({', '.join(p['countries']) or 'aucun pays'})" for p in products}
ordered = PILOTS + sorted([p["productId"] for p in products if p["productId"] not in PILOTS], key=lambda i: prod_label[i])
st.sidebar.markdown("---")
st.sidebar.caption("Produits pilotes : LALSTOP CONTANS WG · LALSTOP G46 WG · LALGUARD M52 OD")
st.sidebar.caption("Sources : Santé Canada PPID · US EPA PPLS · ANSES E-Phy · MAPA AGROFIT")
with st.sidebar.expander("Limites connues"):
    for line in ["4 sources : un produit absent est « non trouvé dans la source », jamais « non homologué ».",
                 "Dose CA/US : uniquement via l'étiquette PDF (extraction IA, à vérifier).",
                 "Codes EPPO : candidats `to_verify` ; Brésil : produits actifs seulement, sans dates.",
                 "Hypothèses « produit sœur » : à confirmer par Regulatory Affairs.",
                 "Prototype sans authentification ; design Entra ID documenté."]:
        st.markdown(f"- {line}")
    st.caption("Détails : docs/LIMITATIONS.md")


def product_picker(key: str) -> str:
    q = st.text_input("Rechercher un produit (nom, alias, micro-organisme)", key=f"q_{key}", placeholder="ex. CONTANS, PRESTOP, Clonostachys rosea")
    if q:
        res = api_get("/products", {"q": q, "limit": 50})
        if not res["items"]:
            st.warning(res["warnings"][0])
            return st.selectbox("Produit", ordered, format_func=lambda i: prod_label.get(i, i), key=f"sel_{key}")
        opts = [p["productId"] for p in res["items"]]
        return st.selectbox("Produit", opts, format_func=lambda i: f"{prod_label.get(i, i)}  · trouvé via {next(p['matchedOn'] for p in res['items'] if p['productId'] == i)}", key=f"sel_{key}")
    return st.selectbox("Produit", ordered, format_func=lambda i: prod_label.get(i, i), key=f"sel_{key}")


def uses_table(reg: dict) -> pd.DataFrame:
    rows = []
    for u in reg["uses"]:
        rows.append({
            "Pays": reg["countryCode"], "N°": reg["registrationNumber"],
            "Culture (original)": u["cropOriginal"], "Culture (normalisée)": u["cropNormalized"], "EPPO culture": f"{u['eppoCropCode'] or '—'} [{u['eppoCropStatus']}]",
            "Cible (original)": u["targetOriginal"], "Cible (normalisée)": u["targetNormalized"], "EPPO cible": u["eppoTargetCode"] or "—",
            "Dose": f"{u['doseValue']} {u['doseUnitOriginal']}" if u["doseValue"] is not None else "— (non structurée)",
            "Dose normalisée": f"{u['doseValueNormalized']} {u['doseUnitNormalized']}" if u["doseValueNormalized"] is not None else "—",
            "DAR (j)": u["phiDays"], "Max appl.": u["maxApplications"], "BBCH": f"{u['growthStageMin'] or ''}-{u['growthStageMax'] or ''}" if u["growthStageMin"] or u["growthStageMax"] else "",
            "Appariement": u["pairing"], "Extraction": u["evidence"]["extractionMethod"], "Confiance": u["evidence"]["confidence"],
            "Validation": u["evidence"]["validationStatus"], "Restrictions (original)": (u["restrictionsOriginal"] or "")[:200],
            "Source": u["evidence"]["sourceId"], "Collecté le": fmt_dt(u["evidence"]["collectedAt"]), "URL": u["evidence"]["sourceUrl"],
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------- pages
if page == "Comparaison":
    st.title("Comparaison produit × pays × usage")
    col1, col2 = st.columns([2, 2])
    with col1:
        pid = product_picker("cmp")
    with col2:
        countries = st.multiselect("Pays", ALL_COUNTRIES, default=["CA", "US", "FR", "BR"], format_func=lambda c: f"{COUNTRY_LABEL.get(c, c)} ({c})")
    if pid and countries:
        data = api_get("/compare", {"productId": pid, "countries": ",".join(countries)})
        if "__404__" in data:
            st.error(data["__404__"]["message"])
            st.stop()
        st.subheader(data.get("commercialName") or pid)
        cols = st.columns(len(countries))
        regs_by_cc: dict[str, list] = {}
        for r in data["registrations"]:
            regs_by_cc.setdefault(r["countryCode"], []).append(r)
        for c, cc in zip(cols, countries):
            cov = next(x for x in data["coverage"] if x["countryCode"] == cc)
            with c:
                st.markdown(f"**{COUNTRY_LABEL.get(cc, cc)} ({cc})**")
                if cov["coverage"] == "found":
                    for r in regs_by_cc.get(cc, []):
                        st.markdown(f"{STATUS_BADGE.get(r['statusNormalized'], r['statusNormalized'])}  \n"
                                    f"n° **{r['registrationNumber']}** · « {r['statusOriginal']} »  \n"
                                    f"{r['usesCount']} usages · expire {r['expirationDate'] or '—'}  \n"
                                    f"[{r['evidence']['sourceId']}]({r['evidence']['sourceUrl']}) · {fmt_dt(r['evidence']['collectedAt'])}  \n"
                                    f"`{r['evidence']['validationStatus']}`")
                elif cov["coverage"] == "not_found_in_source":
                    st.markdown(f"⚪ **non trouvé dans {cov['sourceId']}**  \ncollecté {fmt_dt(cov['collectedAt'])}  \n_≠ absence d'homologation_")
                else:
                    st.markdown("⬜ **source non connectée**  \n_inconnu, pas « non homologué »_")
        warnings_box(data["warnings"])
        if data.get("relatedProducts"):
            st.markdown("### Produits liés (produits distincts — jamais fusionnés)")
            st.caption("`related_product` et `confirmed_sister_product` = affirmés par LPC ou par un nom officiel sur le même enregistrement · "
                       "`related_formulation` = même souche, autre formulation · `sister_product_candidate` = hypothèse à confirmer.")
            rel_rows = []
            for rp in data["relatedProducts"]:
                regs = rp["registrations"] or [None]
                for r in regs:
                    rel_rows.append({"Produit lié": rp["commercialName"], "Relation": rp["relationship"], "Statut de revue": rp["reviewStatus"],
                                     "Confiance": rp["confidence"], "Pays": r["countryCode"] if r else "—", "N°": r["registrationNumber"] if r else "—",
                                     "Statut": STATUS_BADGE.get(r["statusNormalized"], r["statusNormalized"]) if r else "aucun enregistrement dans les pays choisis",
                                     "Expire": (r["expirationDate"] or "—") if r else "—", "Source": r["evidence"]["sourceId"] if r else "—",
                                     "Collecté le": fmt_dt(r["evidence"]["collectedAt"]) if r else "—", "URL": r["evidence"]["sourceUrl"] if r else None,
                                     "Preuve de la relation": rp["evidence"]})
            st.dataframe(pd.DataFrame(rel_rows), hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL", display_text="source")})
        st.markdown("### Usages autorisés (valeur originale · valeur normalisée · preuve)")
        frames = [uses_table(r) for r in data["registrations"] if r["uses"]]
        if frames:
            df = pd.concat(frames, ignore_index=True)
            f1, f2, f3 = st.columns(3)
            with f1:
                crop_f = st.text_input("Filtrer culture", "")
            with f2:
                pairing_f = st.multiselect("Appariement", sorted(df["Appariement"].unique()), default=sorted(df["Appariement"].unique()))
            with f3:
                extr_f = st.multiselect("Extraction", sorted(df["Extraction"].unique()), default=sorted(df["Extraction"].unique()))
            view = df[df["Appariement"].isin(pairing_f) & df["Extraction"].isin(extr_f)]
            if crop_f:
                m = view["Culture (original)"].fillna("").str.contains(crop_f, case=False) | view["Culture (normalisée)"].fillna("").str.contains(crop_f, case=False)
                view = view[m]
            st.caption(f"{len(view)} lignes · `source_paired` = couple culture/cible affirmé par la source · `unpaired_lists` = listes indépendantes (CA/US) · `llm_paired` = extrait de l'étiquette par IA, à vérifier")
            st.dataframe(view, use_container_width=True, hide_index=True, column_config={"URL": st.column_config.LinkColumn("URL", display_text="source")})
        else:
            st.info("Aucun usage structuré pour cette sélection.")
        st.markdown("### Détail des enregistrements")
        for r in data["registrations"]:
            with st.expander(f"{r['countryCode']} · {r['registrationNumber']} · {r['statusOriginal']} → {r['statusNormalized']}"):
                a, b = st.columns(2)
                with a:
                    st.markdown("**Valeurs originales (source)**")
                    st.json({"statusOriginal": r["statusOriginal"], "holderOriginal": r["holderOriginal"], "activeEntityOriginal": r["activeEntityOriginal"],
                             "formulationOriginal": r["formulationOriginal"], "approvalDate": r["approvalDate"], "expirationDate": r["expirationDate"]})
                with b:
                    st.markdown("**Preuve**")
                    st.json(r["evidence"])
        ex1, ex2 = st.columns(2)
        with ex1:
            st.download_button("⬇️ Export CSV (cette sélection)", data=httpx.get(f"{API}/export.csv", params={"productId": pid, "countries": ",".join(countries)}, timeout=120).content,
                               file_name=f"{pid}_{'_'.join(countries)}.csv", mime="text/csv")
        with ex2:
            st.download_button("⬇️ Export Excel (cette sélection)", data=httpx.get(f"{API}/export.xlsx", params={"productId": pid, "countries": ",".join(countries)}, timeout=120).content,
                               file_name=f"{pid}_{'_'.join(countries)}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        disclaimer_box(data["disclaimer"])

elif page == "Carte":
    st.title("Carte des homologations")
    mode = st.radio("Vue", ["Un produit (et ses produits liés)", "Empreinte d'un micro-organisme (tous produits)"], horizontal=True)
    color_map = {"active": "#2e7d32", "actif (produit lié seulement)": "#7cb342", "withdrawn": "#c62828", "expired": "#ef6c00", "pending": "#f9a825",
                 "unknown": "#9e9e9e", "non trouvé dans la source": "#bdbdbd", "source non connectée": "#eeeeee"}
    rows, title, warnings = [], "", []
    if mode.startswith("Un produit"):
        pid = product_picker("map")
        data = api_get("/compare", {"productId": pid, "countries": ",".join(ALL_COUNTRIES)})
        if "__404__" in data:
            st.error(data["__404__"]["message"])
            st.stop()
        title, warnings = data.get("commercialName") or pid, data["warnings"]
        related_by_cc: dict[str, list] = {}
        for rp in data.get("relatedProducts", []):
            for r in rp["registrations"]:
                related_by_cc.setdefault(r["countryCode"], []).append((rp, r))
        for c in data["coverage"]:
            cc = c["countryCode"]
            regs = [r for r in data["registrations"] if r["countryCode"] == cc]
            rel = related_by_cc.get(cc, [])
            if c["coverage"] == "found":
                status = "active" if any(r["statusNormalized"] == "active" for r in regs) else regs[0]["statusNormalized"]
                detail = "; ".join(f"n° {r['registrationNumber']} ({r['statusOriginal']}, expire {r['expirationDate'] or '—'}, {r['usesCount']} usages)" for r in regs)
            elif rel:
                status = "actif (produit lié seulement)" if any(r["statusNormalized"] == "active" for _, r in rel) else rel[0][1]["statusNormalized"]
                detail = "produit absent ; liés : " + "; ".join(f"{rp['commercialName']} n° {r['registrationNumber']} ({rp['relationship']})" for rp, r in rel)
            elif c["coverage"] == "not_found_in_source":
                status, detail = "non trouvé dans la source", f"{c['sourceId']} collecté {fmt_dt(c['collectedAt'])} — ≠ non homologué"
            else:
                status, detail = "source non connectée", "aucune source officielle connectée pour ce marché"
            rows.append({"iso3": ISO3[cc], "Pays": COUNTRY_LABEL.get(cc, cc), "Statut": status, "Détail": detail,
                         "Usages": sum(r["usesCount"] for r in regs), "Liés": "; ".join(f"{rp['commercialName']} ({r['registrationNumber']})" for rp, r in rel) or "—",
                         "Source": c["sourceId"] or "—", "Collecté le": fmt_dt(c["collectedAt"])})
    else:
        species = st.text_input("Micro-organisme (genre espèce)", "Clonostachys rosea")
        crop = st.text_input("Culture (optionnel, mot de la culture tel qu'écrit ou normalisé)", "")
        data = api_get(f"/active-entities/{species}/registrations", {"crop": crop} if crop else None)
        title, warnings = f"Produits contenant {species}" + (f" sur « {crop} »" if crop else ""), data["warnings"]
        by_cc: dict[str, list] = {}
        for r in data["items"]:
            by_cc.setdefault(r["countryCode"], []).append(r)
        src_cov = api_get("/sources")["items"]
        covered = {s["countryOrRegion"] for s in src_cov if s["registrations"]}
        for cc in ALL_COUNTRIES:
            regs = by_cc.get(cc, [])
            if regs:
                status = "active" if any(r["statusNormalized"] == "active" for r in regs) else regs[0]["statusNormalized"]
                detail = "; ".join(f"{r['productName']} n° {r['registrationNumber']} [{r['activeEntityNormalized']}] {r['statusNormalized']}" for r in regs[:12])
            elif cc in covered:
                status, detail = "non trouvé dans la source", "aucun produit avec ce micro-organisme dans la source collectée — ≠ absence d'homologation"
            else:
                status, detail = "source non connectée", "aucune source officielle connectée pour ce marché"
            rows.append({"iso3": ISO3[cc], "Pays": COUNTRY_LABEL.get(cc, cc), "Statut": status, "Détail": detail, "Produits": len({r["productId"] for r in regs}),
                         "Souches": "; ".join(sorted({(r["activeEntityNormalized"] or "").replace(species, "").strip() or "—" for r in regs})) or "—"})
    df = pd.DataFrame(rows)
    hover = {c: True for c in df.columns if c not in ("iso3", "Pays")}
    hover["iso3"] = False
    fig = px.choropleth(df, locations="iso3", color="Statut", hover_name="Pays", hover_data=hover, color_discrete_map=color_map,
                        projection="natural earth", title=title, category_orders={"Statut": list(color_map)})
    fig.update_geos(showcountries=True, countrycolor="#cfd8dc", showcoastlines=False, landcolor="#f5f5f5", bgcolor="rgba(0,0,0,0)")
    fig.update_layout(margin=dict(l=0, r=0, t=48, b=0), legend_title="Statut (normalisé)", height=560, paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Vert foncé = produit homologué · vert clair = seulement un produit lié (sœur / formulation liée, produit distinct) · "
               "gris = absent de la source officielle collectée (≠ non homologué) · blanc = marché sans source connectée. Survolez un pays pour les numéros, statuts et dates.")
    st.markdown("#### Détail par pays")
    st.dataframe(df.drop(columns=["iso3"]), hide_index=True, use_container_width=True)
    warnings_box(warnings)
    disclaimer_box(None)

elif page == "Question":
    st.title("Question en langage naturel")
    st.caption("L'agent répond uniquement à partir des lignes de la base (sources officielles). Chaque réponse cite ses preuves ; "
               "l'IA ne fait que reformuler et un garde-fou rejette tout chiffre ou pays absent des faits.")
    examples = ["Dans quels pays LALSTOP CONTANS WG est-il homologué ?", "Comparer les usages de LALGUARD M52 OD entre la France et le Canada.",
                "Quels champs sont incertains pour LALSTOP G46 WG ?", "Quels produits pourraient être des produits sœurs de LALSTOP G46 WG ?",
                "Donne la source officielle de chaque donnée pour LALSTOP CONTANS WG.", "Quels produits contenant Clonostachys rosea sont homologués sur la fraise ?",
                "Quelles autorisations expirent dans les 12 prochains mois ?", "LALSTOP CONTANS WG est-il homologué au Brésil ?"]
    ex = st.selectbox("Exemples", [""] + examples)
    q = st.text_area("Votre question", value=ex, height=80)
    lang = st.radio("Langue de réponse", ["fr", "en"], horizontal=True)
    if st.button("Interroger", type="primary") and q.strip():
        with st.spinner("Recherche dans les sources collectées…"):
            ans = api_post("/ask", {"question": q, "language": lang})
        st.markdown("#### Réponse")
        st.text(ans["answer"])
        st.caption(f"intention : `{ans['intent']}` · outils : {', '.join(ans['toolsUsed']) or '—'} · formulation : {ans['model'] or 'déterministe (sans IA)'}")
        warnings_box(ans["warnings"])
        st.markdown(f"#### Preuves ({len(ans['evidence'])})")
        if ans["evidence"]:
            ev = pd.DataFrame([{"Source": e["sourceId"], "URL": e["sourceUrl"], "Collecté le": fmt_dt(e["collectedAt"]), "Validation": e["validationStatus"],
                                "Extraction": e.get("extractionMethod"), "Extrait": (e.get("excerpt") or "")[:160]} for e in ans["evidence"]])
            st.dataframe(ev, hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL", display_text="ouvrir")})
        else:
            st.info("Aucune preuve : aucune donnée des sources collectées ne répond à la question. Absence de résultat ≠ absence d'homologation.")
        with st.expander("Faits structurés utilisés par la réponse"):
            st.json(ans["facts"])
        disclaimer_box(ans["disclaimer"])

elif page == "Produits sœurs & revue":
    st.title("Noms équivalents, historiques et hypothèses « produit sœur »")
    pid = product_picker("sis")
    al = api_get(f"/products/{pid}/aliases")
    if "__404__" in al:
        st.error(al["__404__"]["message"])
        st.stop()
    if not al:
        st.info("Aucun alias ni hypothèse pour ce produit.")
    else:
        df = pd.DataFrame([{"Nom": a["aliasName"], "Relation": a["relationshipType"], "Pays": a["countryCode"] or "—", "Confiance": a["confidence"],
                            "Statut de revue": a["reviewStatus"], "Preuve": a["evidence"], "URL": a["sourceRecordUrl"], "id": a["aliasId"]} for a in al])
        st.caption("`alternate_name` / `historical_name` = fait officiel (même enregistrement) · `sister_product_candidate` = hypothèse à confirmer · "
                   "`related_formulation` = même souche, autre formulation. La confiance est celle de la machine, pas une validation réglementaire.")
        st.dataframe(df.drop(columns=["id"]), hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL", display_text="source")})
        st.markdown("### Revue Regulatory Affairs")
        st.caption("Chaque changement de statut est journalisé (qui, quand, pourquoi) et visible dans /review/log.")
        c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
        with c1:
            target = st.selectbox("Hypothèse / alias", df["id"], format_func=lambda i: f"{df.set_index('id').loc[i, 'Nom']} ({df.set_index('id').loc[i, 'Relation']}, {df.set_index('id').loc[i, 'Statut de revue']})")
        with c2:
            new = st.selectbox("Nouveau statut", ["validated", "rejected", "to_verify", "obsolete"])
        with c3:
            reviewer = st.text_input("Relecteur", "")
        with c4:
            note = st.text_input("Justification", "")
        if st.button("Enregistrer la décision", disabled=not reviewer):
            res = api_post("/review", {"entityType": "alias", "entityId": target, "newStatus": new, "reviewer": reviewer, "note": note})
            st.success(f"{res['entityId']} : {res['oldStatus']} → {res['newStatus']} (par {res['reviewer']})")
            api_get.clear()
        log = api_get("/review/log", {"limit": 50})
        if log:
            st.markdown("#### Journal de revue")
            st.dataframe(pd.DataFrame(log), hide_index=True, use_container_width=True)
    disclaimer_box(None)

elif page == "Veille (changements, échéances)":
    st.title("Veille : changements détectés et échéances")
    months = st.slider("Horizon des échéances (mois)", 1, 60, 12)
    exp = api_get("/expiring", {"months": months})
    st.markdown(f"### Autorisations expirant dans les {months} mois ({len(exp['items'])})")
    if exp["items"]:
        st.dataframe(pd.DataFrame([{"Produit": r["productName"], "Pays": r["countryCode"], "N°": r["registrationNumber"], "Expire le": r["expirationDate"],
                                    "Jours restants": r["daysLeft"], "Statut": r["statusNormalized"], "Source": r["evidence"]["sourceId"], "URL": r["evidence"]["sourceUrl"],
                                    "Collecté le": fmt_dt(r["evidence"]["collectedAt"])} for r in exp["items"]]),
                     hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL", display_text="source")})
    warnings_box(exp["warnings"])
    ch = api_get("/changes", {"limit": 300})
    st.markdown(f"### Changements entre collectes ({len(ch)})")
    st.caption("Comparaison champ par champ entre deux collectes d'une même source. Une ligne disparue de la source est marquée « plus listée », jamais « retirée ».")
    if ch:
        st.dataframe(pd.DataFrame([{"Détecté le": fmt_dt(c["detectedAt"]), "Entité": c["entityId"], "Champ": c["field"], "Avant": c["oldValue"], "Après": c["newValue"],
                                    "Snapshot": f"{c['fromSnapshotId'] or '—'} → {c['toSnapshotId']}"} for c in ch]), hide_index=True, use_container_width=True)
    else:
        st.info("Aucun changement : il faut au moins deux collectes de la même source.")
    disclaimer_box(None)

elif page == "Sources & qualité":
    st.title("Sources officielles, licences et qualité des données")
    src = api_get("/sources")
    df = pd.DataFrame([{"Source": s["sourceId"], "Nom officiel": s["officialName"], "Région": s["countryOrRegion"], "Accès": s["accessMethod"], "Format": s["dataFormat"],
                        "Licence": s["licenseName"], "Limites": s["accessAndReuseLimits"], "Enregistrements": s["registrations"], "Dernière collecte": fmt_dt(s["lastCollectedAt"]),
                        "URL": s["baseUrl"]} for s in src["items"]])
    st.dataframe(df, hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL", display_text="ouvrir")})
    st.markdown("### Champs manquants ou incertains par produit")
    pid = product_picker("dq")
    dq = api_get(f"/products/{pid}/quality")
    if "__404__" not in dq:
        st.dataframe(pd.DataFrame([{"Enregistrement": i["registrationId"], "Pays": i["countryCode"], "Statut": i["statusNormalized"], "Validation": i["validationStatus"],
                                    "Appariement": ", ".join(i["pairing"]), "Manquant / incertain": "; ".join(i["missingOrUncertain"]) or "—"} for i in dq["registrations"]]),
                     hide_index=True, use_container_width=True)
        warnings_box(dq["warnings"])
    st.markdown("### Export complet")
    st.download_button("⬇️ Toute la base (CSV)", data=httpx.get(f"{API}/export.csv", timeout=180).content, file_name="lpc_regwatch_all.csv", mime="text/csv")
    disclaimer_box(src["disclaimer"])
