"""Streamlit workbench — a THIN client of the API (no direct database access, no business logic here).

Why: cahier §16 forbids logic locked in the UI; everything shown comes from the same endpoints that
Power Platform / Copilot Studio would call. API base URL from env API_BASE_URL.
Visual identity: Lallemand Plant Care (slate #36434b, Lallemand red #e30327, light greys) via .streamlit/config.toml.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
PILOTS = ["P-LPC-CONTANS", "P-LPC-G46", "P-LPC-M52"]
ALL_COUNTRIES = ["CA", "US", "FR", "BR", "DE", "BE", "MX", "UY"]
COUNTRY_LABEL = {"CA": "Canada", "US": "États-Unis", "FR": "France", "BR": "Brésil", "DE": "Allemagne", "BE": "Belgique", "MX": "Mexique", "UY": "Uruguay",
                 "ES": "Espagne", "IT": "Italie", "NL": "Pays-Bas", "GB": "Royaume-Uni", "PL": "Pologne"}
ISO3 = {"CA": "CAN", "US": "USA", "FR": "FRA", "BR": "BRA", "DE": "DEU", "BE": "BEL", "MX": "MEX", "UY": "URY", "ES": "ESP", "IT": "ITA", "NL": "NLD", "GB": "GBR", "PL": "POL"}
ISO3_TO_CC = {v: k for k, v in ISO3.items()}
CENTROIDS = {"CA": (56.1, -106.3), "US": (39.8, -98.6), "FR": (46.6, 2.2), "BR": (-14.2, -51.9), "DE": (51.2, 10.4), "BE": (50.5, 4.5), "MX": (23.6, -102.5),
             "UY": (-32.5, -55.8), "ES": (40.4, -3.7), "IT": (42.5, 12.5), "NL": (52.1, 5.3), "GB": (54.0, -2.0), "PL": (52.0, 19.0)}

# brand palette (lallemandplantcare.com): slate, Lallemand red, greys; map accents chosen to read on slate
SLATE, SLATE_DARK, RED, GREY, GREY_LIGHT, INK = "#36434b", "#2b363d", "#e30327", "#9ba1a5", "#ebeced", "#212529"
STATUS_COLOR = {"active": "#2fd27a", "expired": "#f0a21f", "withdrawn": RED, "pending": "#f5c842", "unknown": GREY}
STATUS_LABEL = {"active": "actif", "expired": "expiré", "withdrawn": "retiré", "pending": "en attente", "unknown": "inconnu"}
MAP_COLORS = {"homologué (actif)": "#2fd27a", "produit lié seulement": "#38c6ff", "retiré / expiré": RED, "en attente": "#f5c842",
              "non trouvé dans la source": "#5e6b72", "source non connectée": "#434f56"}
MAP_ORDER = list(MAP_COLORS)
ASSETS = Path(__file__).parent / "assets"

st.set_page_config(page_title="LPC Regulatory Watch", page_icon=str(ASSETS / "lallemand_logo.svg"), layout="wide", initial_sidebar_state="expanded")

st.markdown(f"""
<style>
  section[data-testid="stSidebar"] {{ min-width: 300px; }}
  section[data-testid="stSidebar"] .block-container {{ padding-top: 1.2rem; }}
  section[data-testid="stSidebar"] [data-testid="stRadio"] label p {{ font-size: 0.95rem; }}
  section[data-testid="stSidebar"] [data-testid="stRadio"] > div {{ gap: 0.15rem; }}
  .lpc-brand {{ display:flex; align-items:center; gap:12px; margin-bottom:6px; }}
  .lpc-brand .t1 {{ font-size:1.05rem; font-weight:700; letter-spacing:.02em; color:#fff; line-height:1.1; }}
  .lpc-brand .t2 {{ font-size:.78rem; color:#c9d0d4; letter-spacing:.12em; text-transform:uppercase; }}
  .lpc-card {{ background:{SLATE_DARK}; border:1px solid #4a575f; border-radius:8px; padding:10px 12px; margin:8px 0 12px; font-size:.82rem; color:#dfe4e7; }}
  .lpc-card b {{ color:#fff; }}
  .lpc-card .ok {{ color:#2fd27a; font-weight:600; }}
  .lpc-card .off {{ color:#f5c842; font-weight:600; }}
  .lpc-section {{ font-size:.72rem; letter-spacing:.14em; text-transform:uppercase; color:#aab3b8; margin:14px 0 4px; }}
  .lpc-list {{ font-size:.84rem; color:#e6eaec; line-height:1.55; margin:0; padding-left:0; list-style:none; }}
  .lpc-list li::before {{ content:""; display:inline-block; width:6px; height:6px; border-radius:50%; background:{RED}; margin-right:8px; vertical-align:middle; }}
  .badge {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:.78rem; font-weight:600; color:#fff; }}
  .kpi {{ background:{GREY_LIGHT}; border-left:4px solid {RED}; border-radius:6px; padding:10px 14px; }}
  .kpi .v {{ font-size:1.6rem; font-weight:700; color:{INK}; line-height:1.1; }}
  .kpi .l {{ font-size:.7rem; color:#5b6770; text-transform:uppercase; letter-spacing:.03em; line-height:1.2; }}
  .ccard {{ border:1px solid #d7d9db; border-radius:8px; padding:12px 14px; background:#fff; min-height:150px; }}
  .ccard h4 {{ margin:0 0 6px; font-size:1rem; color:{INK}; }}
  .ccard .m {{ color:#5b6770; font-size:.82rem; }}
  .ccard a {{ color:{SLATE}; }}
  .disclaimer {{ font-size:.78rem; color:#5b6770; border-top:1px solid #e1e3e4; padding-top:8px; margin-top:18px; }}
  .warn {{ font-size:.85rem; }}
  div[data-testid="stMetric"] {{ background:{GREY_LIGHT}; border-left:4px solid {RED}; border-radius:6px; padding:8px 12px; }}
</style>
""", unsafe_allow_html=True)


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


def badge(status: str) -> str:
    return f'<span class="badge" style="background:{STATUS_COLOR.get(status, GREY)}">{STATUS_LABEL.get(status, status)}</span>'


def disclaimer_box(text: str | None):
    st.markdown(f'<div class="disclaimer">{text or "Ce prototype n’est pas une source réglementaire officielle. Validation Regulatory Affairs requise. Aucun résultat ≠ absence d’homologation."}</div>',
                unsafe_allow_html=True)


def warnings_box(warnings: list[str]):
    if warnings:
        with st.expander(f"{len(warnings)} avertissement(s) — données manquantes ou incertaines", expanded=False):
            for w in warnings:
                st.markdown(f'<div class="warn">• {w}</div>', unsafe_allow_html=True)


def map_status(active: int, withdrawn: int, expired: int, pending: int, coverage: str, related: int = 0) -> str:
    if active:
        return "homologué (actif)"
    if withdrawn or expired:
        return "retiré / expiré"
    if pending:
        return "en attente"
    if related:
        return "produit lié seulement"
    return "source non connectée" if coverage == "source_not_collected" else "non trouvé dans la source"


def status_map(df: pd.DataFrame, key: str, height: int = 540, size_col: str | None = None) -> str | None:
    """Slate world map in the brand palette: coloured country fills + halo markers sized by `size_col`.
    Returns the ISO-3 code of the clicked country (polygon or halo) or None."""
    fig = go.Figure()
    extra_cols = [c for c in df.columns if c not in ("iso3", "Pays", "Statut")]
    for status in MAP_ORDER:
        part = df[df["Statut"] == status]
        if part.empty:
            continue
        hover = "<b>%{customdata[0]}</b><br>" + "<br>".join(f"{c}: %{{customdata[{i + 1}]}}" for i, c in enumerate(extra_cols))
        fig.add_trace(go.Choropleth(locations=part["iso3"], z=[1] * len(part), colorscale=[[0, MAP_COLORS[status]], [1, MAP_COLORS[status]]], showscale=False,
                                    marker_line_color=SLATE_DARK, marker_line_width=0.9, name=status, showlegend=True,
                                    customdata=part[["Pays"] + extra_cols].values, hovertemplate=hover + "<extra></extra>",
                                    marker_opacity=0.95 if status in MAP_ORDER[:4] else 0.7))
    glow = df[df["Statut"].isin(MAP_ORDER[:4])]
    if not glow.empty:
        lats = [CENTROIDS[ISO3_TO_CC[i]][0] for i in glow["iso3"]]
        lons = [CENTROIDS[ISO3_TO_CC[i]][1] for i in glow["iso3"]]
        vals = glow[size_col] if size_col and size_col in glow else pd.Series([1] * len(glow), index=glow.index)
        sizes = 20 + 24 * (vals / max(1, vals.max())) ** 0.5
        colors = [MAP_COLORS[s] for s in glow["Statut"]]
        fig.add_trace(go.Scattergeo(lat=lats, lon=lons, mode="markers", marker=dict(size=sizes * 2.3, color=colors, opacity=0.16, line_width=0),
                                    hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scattergeo(lat=lats, lon=lons, mode="markers+text", marker=dict(size=sizes, color=colors, opacity=0.95, line=dict(width=2, color=SLATE_DARK)),
                                    text=[str(int(v)) if size_col else "" for v in vals], textfont=dict(color=SLATE_DARK, size=12, family="Segoe UI, Arial"),
                                    textposition="middle center", customdata=list(glow["iso3"]), hovertemplate="%{customdata}<extra></extra>", showlegend=False))
    fig.update_geos(showland=True, landcolor="#46535b", showcountries=True, countrycolor="#56636b", showcoastlines=False, showocean=True, oceancolor=SLATE_DARK,
                    showlakes=False, showframe=False, bgcolor=SLATE_DARK, lataxis_range=[-58, 82], projection_type="natural earth", projection_scale=1.08)
    fig.update_layout(margin=dict(l=0, r=0, t=6, b=0), height=height, paper_bgcolor=SLATE_DARK, plot_bgcolor=SLATE_DARK,
                      font=dict(color="#e6eaec", family="Segoe UI, Arial"),
                      legend=dict(orientation="h", y=0.01, x=0.5, xanchor="center", bgcolor="rgba(43,54,61,.75)", bordercolor="#56636b", borderwidth=1, font=dict(size=12)),
                      clickmode="event+select", dragmode=False, hoverlabel=dict(bgcolor="#1f272c", bordercolor="#2fd27a", font=dict(color="#eef1f2", size=12)))
    ev = st.plotly_chart(fig, use_container_width=True, key=key, on_select="rerun", selection_mode="points", theme=None,
                         config={"displayModeBar": False, "scrollZoom": False})
    try:
        points = ev.selection.points  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        points = ev.get("selection", {}).get("points", []) if isinstance(ev, dict) else []
    for pt in points or []:
        loc = pt.get("location") or pt.get("customdata")
        if isinstance(loc, (list, tuple)):
            loc = loc[0]
        if loc in ISO3_TO_CC:
            return loc
    return None


def country_picker(df: pd.DataFrame, clicked: str | None, key: str, label_col: str = "Enregistrements") -> str:
    """Country pills under a map; a map click overrides the pills (widget state is updated before rendering)."""
    opts = list(df["iso3"])
    labels = {i: f"{df.set_index('iso3').loc[i, 'Pays']} · {int(df.set_index('iso3').loc[i, label_col])}" if label_col in df else df.set_index("iso3").loc[i, "Pays"] for i in opts}
    state_key = f"{key}_pills"
    if clicked in opts and st.session_state.get(f"{key}_last_click") != clicked:
        st.session_state[state_key] = clicked
        st.session_state[f"{key}_last_click"] = clicked
    if st.session_state.get(state_key) not in opts:
        st.session_state[state_key] = opts[0]
    picked = st.pills("Pays", opts, format_func=lambda i: labels[i], selection_mode="single", key=state_key, label_visibility="collapsed")
    return picked or st.session_state.get(f"{key}_last_click") or opts[0]


# ---------------------------------------------------------------------------------- sidebar
try:
    health = api_get("/health")
except Exception as e:  # noqa: BLE001
    st.error(f"API injoignable sur {API} : {e}")
    st.stop()

with st.sidebar:
    logo = (ASSETS / "lallemand_logo.svg").read_text(encoding="utf-8") if (ASSETS / "lallemand_logo.svg").exists() else ""
    st.markdown(f'<div class="lpc-brand"><div style="width:96px">{logo}</div><div><div class="t1">Regulatory Watch</div><div class="t2">Plant Care · prototype</div></div></div>',
                unsafe_allow_html=True)
    ai_txt = f'<span class="ok">activée</span> · {health.get("aiProvider")}' if health.get("aiEnabled") else '<span class="off">désactivée</span> · réponses déterministes'
    st.markdown(f'<div class="lpc-card"><b>{health.get("registrations")}</b> enregistrements · v{health.get("version")}<br>IA : {ai_txt}<br>'
                f'Dernière collecte : {fmt_dt(health.get("lastSnapshotAt"))}</div>', unsafe_allow_html=True)
    st.markdown('<div class="lpc-section">Navigation</div>', unsafe_allow_html=True)
    page = st.radio("Vue", ["Vue d'ensemble", "Comparaison", "Carte", "Question", "Produits sœurs & revue", "Veille (changements, échéances)",
                            "Registre interne LPC", "Sources & qualité"], label_visibility="collapsed")
    st.markdown('<div class="lpc-section">Produits pilotes</div><ul class="lpc-list"><li>LALSTOP CONTANS WG</li><li>LALSTOP G46 WG</li><li>LALGUARD M52 OD</li></ul>',
                unsafe_allow_html=True)
    st.markdown('<div class="lpc-section">Sources officielles</div><ul class="lpc-list"><li>Santé Canada — PPID</li><li>US EPA — PPLS</li><li>ANSES — E-Phy</li><li>MAPA — AGROFIT</li></ul>',
                unsafe_allow_html=True)
    with st.expander("Limites connues"):
        for line in ["4 sources : un produit absent est « non trouvé dans la source », jamais « non homologué ».",
                     "Dose CA/US : uniquement via l'étiquette PDF (extraction IA, à vérifier).",
                     "Codes EPPO : candidats to_verify ; Brésil : produits actifs seulement, sans dates.",
                     "Hypothèses « produit sœur » : à confirmer par Regulatory Affairs.",
                     "Prototype sans authentification ; design Entra ID documenté."]:
            st.markdown(f"- {line}")
    st.markdown('<div class="lpc-section">Liens</div>', unsafe_allow_html=True)
    st.markdown(f'<ul class="lpc-list"><li><a href="{API}/docs" target="_blank">Documentation API</a></li><li><a href="/pitch/" target="_blank">Présentation</a></li></ul>', unsafe_allow_html=True)

products = api_get("/products", {"limit": 500})["items"]
prod_label = {p["productId"]: f"{p['commercialName']}  ({', '.join(p['countries']) or 'aucun pays'})" for p in products}
ordered = PILOTS + sorted([p["productId"] for p in products if p["productId"] not in PILOTS], key=lambda i: prod_label[i])


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


def country_detail_table(regs: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"Produit": r["productName"], "N°": r["registrationNumber"], "Statut": STATUS_LABEL.get(r["statusNormalized"], r["statusNormalized"]),
                          "Statut (original)": r["statusOriginal"], "Expire": r["expirationDate"] or "—", "Titulaire": r["holder"], "Usages": r["usesCount"],
                          "Micro-organisme": r["activeEntityNormalized"], "Validation": r["validationStatus"], "Source": r["sourceId"],
                          "Collecté le": fmt_dt(r["collectedAt"]), "URL": r["sourceUrl"]} for r in regs])


LINK = {"URL": st.column_config.LinkColumn("URL", display_text="source")}

# ---------------------------------------------------------------------------------- pages
if page == "Vue d'ensemble":
    st.title("Vue d'ensemble des homologations")
    c1, c2, c3 = st.columns([2.2, 2, 1])
    with c1:
        scope_label = st.radio("Périmètre", ["Produits pilotes LPC", "Tous les produits Lallemand", "Tous les produits de la base", "Un produit"], horizontal=True)
    scope = {"Produits pilotes LPC": "pilots", "Tous les produits Lallemand": "lallemand", "Tous les produits de la base": "all", "Un produit": "product"}[scope_label]
    params = {"scope": scope}
    with c2:
        if scope == "product":
            params["productId"] = product_picker("ov")
    with c3:
        params["months"] = st.number_input("Échéances (mois)", 1, 60, 12)
    ov = api_get("/overview", params)
    if "__404__" in ov:
        st.error(ov["__404__"]["message"])
        st.stop()
    t = ov["totals"]
    k = st.columns(6)
    for col, (v, l) in zip(k, [(t["sourcesConnected"], "Sources officielles"), (t["countriesFound"], "Pays avec homologation"), (t["products"], "Produits"),
                                (t["registrations"], "Enregistrements"), (t["active"], "dont actifs"), (t["expiringSoon"], f"Expirent < {ov['months']} mois")]):
        col.markdown(f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>', unsafe_allow_html=True)
    rows = []
    for c in ov["countries"]:
        if c["countryCode"] not in ISO3:
            continue
        prods = sorted({r["productName"] for r in c["registrations"]})
        rows.append({"iso3": ISO3[c["countryCode"]], "Pays": c["countryName"], "Statut": map_status(c["active"], c["withdrawn"], c["expired"], c["pending"], c["coverage"]),
                     "Enregistrements": c["active"] + c["withdrawn"] + c["expired"] + c["pending"] + c["unknown"], "Actifs": c["active"], "Retirés": c["withdrawn"] + c["expired"],
                     "En attente": c["pending"], "Produits": c["products"], "Usages": c["usesCount"], "Expirent bientôt": c["expiringSoon"],
                     "Source": c["sourceId"] or "aucune", "Collecté le": fmt_dt(c["collectedAt"]),
                     "Liste": (", ".join(prods[:6]) + (" …" if len(prods) > 6 else "")) or "—"})
    df = pd.DataFrame(rows)
    st.caption("Survolez un pays pour les chiffres ; cliquez un pays ou un halo, ou choisissez-le dans les pastilles sous la carte. "
               "Vert = au moins une homologation active dans le périmètre · rouge = seulement des retraits · gris = source officielle collectée mais aucun produit "
               "du périmètre (≠ non homologué) · gris foncé = marché sans source connectée dans ce prototype.")
    clicked = status_map(df, "ov_map", 580, size_col="Enregistrements")
    sel_iso = country_picker(df, clicked, "ov")
    cc = ISO3_TO_CC[sel_iso]
    c = next(x for x in ov["countries"] if x["countryCode"] == cc)
    st.markdown(f"### {c['countryName']} ({cc}) — {c['sourceId'] or 'aucune source connectée'}" + (f" · collecté {fmt_dt(c['collectedAt'])}" if c["collectedAt"] else ""))
    if c["registrations"]:
        st.dataframe(country_detail_table(c["registrations"]), hide_index=True, use_container_width=True, column_config=LINK)
    elif c["coverage"] == "not_found_in_source":
        st.info(f"Aucun produit du périmètre dans {c['sourceId']} au {fmt_dt(c['collectedAt'])}. Ce n'est pas une preuve d'absence d'homologation.")
    else:
        st.warning("Aucune source officielle connectée pour ce marché dans le prototype : rien ne peut être affirmé.")
    with st.expander("Tableau de tous les pays"):
        st.dataframe(df.drop(columns=["iso3"]), hide_index=True, use_container_width=True)
    disclaimer_box(ov["disclaimer"])

elif page == "Comparaison":
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
        regs_by_cc: dict[str, list] = {}
        for r in data["registrations"]:
            regs_by_cc.setdefault(r["countryCode"], []).append(r)
        rel_by_cc: dict[str, list] = {}
        for rp in data.get("relatedProducts", []):
            for r in rp["registrations"]:
                rel_by_cc.setdefault(r["countryCode"], []).append((rp, r))
        mrows = []
        for cov in data["coverage"]:
            cc = cov["countryCode"]
            if cc not in ISO3:
                continue
            regs = regs_by_cc.get(cc, [])
            mrows.append({"iso3": ISO3[cc], "Pays": COUNTRY_LABEL.get(cc, cc),
                          "Statut": map_status(sum(r["statusNormalized"] == "active" for r in regs), sum(r["statusNormalized"] == "withdrawn" for r in regs),
                                               sum(r["statusNormalized"] == "expired" for r in regs), sum(r["statusNormalized"] == "pending" for r in regs),
                                               cov["coverage"], len(rel_by_cc.get(cc, []))),
                          "N°": ", ".join(f"{r['registrationNumber']} ({r['statusOriginal']})" for r in regs) or "—",
                          "Expire": ", ".join(r["expirationDate"] or "—" for r in regs) or "—", "Usages": sum(r["usesCount"] for r in regs),
                          "Produits liés": ", ".join(f"{rp['commercialName']} {r['registrationNumber']}" for rp, r in rel_by_cc.get(cc, [])) or "—",
                          "Source": cov["sourceId"] or "aucune", "Collecté le": fmt_dt(cov["collectedAt"])})
        mdf = pd.DataFrame(mrows)
        clicked = status_map(mdf, "cmp_map", 440, size_col="Usages")
        focus = ISO3_TO_CC.get(clicked) if clicked else None
        cols = st.columns(len(countries))
        for c, cc in zip(cols, countries):
            cov = next(x for x in data["coverage"] if x["countryCode"] == cc)
            border = f"border:2px solid {RED};" if focus == cc else ""
            with c:
                if cov["coverage"] == "found":
                    inner = ""
                    for r in regs_by_cc.get(cc, []):
                        inner += (f'{badge(r["statusNormalized"])} <b>n° {r["registrationNumber"]}</b><div class="m">« {r["statusOriginal"]} » · {r["usesCount"]} usages · '
                                  f'expire {r["expirationDate"] or "—"}<br><a href="{r["evidence"]["sourceUrl"]}" target="_blank">{r["evidence"]["sourceId"]}</a> · '
                                  f'{fmt_dt(r["evidence"]["collectedAt"])}<br><code>{r["evidence"]["validationStatus"]}</code></div>')
                elif cov["coverage"] == "not_found_in_source":
                    inner = (f'<span class="badge" style="background:{GREY}">non trouvé dans {cov["sourceId"]}</span><div class="m">collecté {fmt_dt(cov["collectedAt"])}'
                             f'<br>≠ absence d’homologation</div>')
                    if rel_by_cc.get(cc):
                        inner += '<div class="m">Produits liés : ' + ", ".join(f"{rp['commercialName']} ({r['registrationNumber']})" for rp, r in rel_by_cc[cc]) + "</div>"
                else:
                    inner = f'<span class="badge" style="background:{SLATE}">source non connectée</span><div class="m">inconnu, pas « non homologué »</div>'
                st.markdown(f'<div class="ccard" style="{border}"><h4>{COUNTRY_LABEL.get(cc, cc)} ({cc})</h4>{inner}</div>', unsafe_allow_html=True)
        warnings_box(data["warnings"])
        if data.get("relatedProducts"):
            st.markdown("### Produits liés (produits distincts — jamais fusionnés)")
            st.caption("related_product et confirmed_sister_product = affirmés par LPC ou par un nom officiel sur le même enregistrement · "
                       "related_formulation = même souche, autre formulation · sister_product_candidate = hypothèse à confirmer.")
            rel_rows = []
            for rp in data["relatedProducts"]:
                for r in rp["registrations"] or [None]:
                    rel_rows.append({"Produit lié": rp["commercialName"], "Relation": rp["relationship"], "Statut de revue": rp["reviewStatus"], "Confiance": rp["confidence"],
                                     "Pays": r["countryCode"] if r else "—", "N°": r["registrationNumber"] if r else "—",
                                     "Statut": STATUS_LABEL.get(r["statusNormalized"], r["statusNormalized"]) if r else "aucun enregistrement dans les pays choisis",
                                     "Expire": (r["expirationDate"] or "—") if r else "—", "Source": r["evidence"]["sourceId"] if r else "—",
                                     "Collecté le": fmt_dt(r["evidence"]["collectedAt"]) if r else "—", "URL": r["evidence"]["sourceUrl"] if r else None,
                                     "Preuve de la relation": rp["evidence"]})
            st.dataframe(pd.DataFrame(rel_rows), hide_index=True, use_container_width=True, column_config=LINK)
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
            st.caption(f"{len(view)} lignes · source_paired = couple culture/cible affirmé par la source · unpaired_lists = listes indépendantes (CA/US) · "
                       "llm_paired = extrait de l'étiquette par IA, à vérifier")
            st.dataframe(view, use_container_width=True, hide_index=True, column_config=LINK)
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
            st.download_button("Export CSV (cette sélection)", data=httpx.get(f"{API}/export.csv", params={"productId": pid, "countries": ",".join(countries)}, timeout=120).content,
                               file_name=f"{pid}_{'_'.join(countries)}.csv", mime="text/csv")
        with ex2:
            st.download_button("Export Excel (cette sélection)", data=httpx.get(f"{API}/export.xlsx", params={"productId": pid, "countries": ",".join(countries)}, timeout=120).content,
                               file_name=f"{pid}_{'_'.join(countries)}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        disclaimer_box(data["disclaimer"])

elif page == "Carte":
    st.title("Carte des homologations")
    mode = st.radio("Vue", ["Un produit (et ses produits liés)", "Empreinte d'un micro-organisme (tous produits)"], horizontal=True)
    rows, warnings = [], []
    detail: dict[str, list] = {}
    if mode.startswith("Un produit"):
        pid = product_picker("map")
        data = api_get("/compare", {"productId": pid, "countries": ",".join(ALL_COUNTRIES)})
        if "__404__" in data:
            st.error(data["__404__"]["message"])
            st.stop()
        warnings = data["warnings"]
        related_by_cc: dict[str, list] = {}
        for rp in data.get("relatedProducts", []):
            for r in rp["registrations"]:
                related_by_cc.setdefault(r["countryCode"], []).append((rp, r))
        for c in data["coverage"]:
            cc = c["countryCode"]
            regs = [r for r in data["registrations"] if r["countryCode"] == cc]
            rel = related_by_cc.get(cc, [])
            status = map_status(sum(r["statusNormalized"] == "active" for r in regs), sum(r["statusNormalized"] == "withdrawn" for r in regs),
                                sum(r["statusNormalized"] == "expired" for r in regs), sum(r["statusNormalized"] == "pending" for r in regs), c["coverage"], len(rel))
            rows.append({"iso3": ISO3[cc], "Pays": COUNTRY_LABEL.get(cc, cc), "Statut": status, "Enregistrements": len(regs) + len(rel),
                         "N°": "; ".join(f"{r['registrationNumber']} ({r['statusOriginal']}, expire {r['expirationDate'] or '—'})" for r in regs) or "—",
                         "Produits liés": "; ".join(f"{rp['commercialName']} {r['registrationNumber']} ({rp['relationship']})" for rp, r in rel) or "—",
                         "Usages": sum(r["usesCount"] for r in regs), "Source": c["sourceId"] or "—", "Collecté le": fmt_dt(c["collectedAt"])})
            detail[ISO3[cc]] = [{"productName": data.get("commercialName"), **r, "holder": r["holderOriginal"], "activeEntityNormalized": None,
                                 "sourceId": r["evidence"]["sourceId"], "sourceUrl": r["evidence"]["sourceUrl"], "collectedAt": r["evidence"]["collectedAt"],
                                 "validationStatus": r["evidence"]["validationStatus"]} for r in regs] + \
                               [{"productName": f"{rp['commercialName']} (produit lié : {rp['relationship']})", **r, "holder": r["holderOriginal"], "activeEntityNormalized": None,
                                 "sourceId": r["evidence"]["sourceId"], "sourceUrl": r["evidence"]["sourceUrl"], "collectedAt": r["evidence"]["collectedAt"],
                                 "validationStatus": r["evidence"]["validationStatus"]} for rp, r in rel]
    else:
        species = st.text_input("Micro-organisme (genre espèce)", "Clonostachys rosea")
        crop = st.text_input("Culture (optionnel, mot de la culture tel qu'écrit ou normalisé)", "")
        data = api_get(f"/active-entities/{species}/registrations", {"crop": crop} if crop else None)
        warnings = data["warnings"]
        by_cc: dict[str, list] = {}
        for r in data["items"]:
            by_cc.setdefault(r["countryCode"], []).append(r)
        covered = {s["countryOrRegion"] for s in api_get("/sources")["items"] if s["registrations"]}
        for cc in ALL_COUNTRIES:
            regs = by_cc.get(cc, [])
            status = map_status(sum(r["statusNormalized"] == "active" for r in regs), sum(r["statusNormalized"] == "withdrawn" for r in regs),
                                sum(r["statusNormalized"] == "expired" for r in regs), sum(r["statusNormalized"] == "pending" for r in regs),
                                "not_found_in_source" if cc in covered else "source_not_collected")
            rows.append({"iso3": ISO3[cc], "Pays": COUNTRY_LABEL.get(cc, cc), "Statut": status, "Enregistrements": len(regs), "Produits": len({r["productId"] for r in regs}),
                         "Souches": "; ".join(sorted({(r["activeEntityNormalized"] or "").replace(species, "").strip() or "—" for r in regs})) or "—"})
            detail[ISO3[cc]] = [{**r, "holder": r["holderOriginal"], "sourceId": r["evidence"]["sourceId"], "sourceUrl": r["evidence"]["sourceUrl"],
                                 "collectedAt": r["evidence"]["collectedAt"], "validationStatus": r["evidence"]["validationStatus"]} for r in regs]
    df = pd.DataFrame(rows)
    clicked = status_map(df, "carte_map", 560, size_col="Enregistrements")
    sel = country_picker(df, clicked, "carte")
    st.markdown(f"#### {df.set_index('iso3').loc[sel, 'Pays']}")
    if detail.get(sel):
        st.dataframe(country_detail_table(detail[sel]), hide_index=True, use_container_width=True, column_config=LINK)
    else:
        st.info(df.set_index("iso3").loc[sel, "Statut"].capitalize() + " — rien à afficher pour ce pays dans ce périmètre.")
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
        st.caption(f"intention : {ans['intent']} · outils : {', '.join(ans['toolsUsed']) or '—'} · formulation : {ans['model'] or 'déterministe (sans IA)'}")
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
        st.caption("alternate_name / historical_name = fait officiel (même enregistrement) · related_product / confirmed_sister_product = affirmés par LPC · "
                   "sister_product_candidate = hypothèse à confirmer · related_formulation = même souche, autre formulation. La confiance est celle de la machine, pas une validation réglementaire.")
        st.dataframe(df.drop(columns=["id"]), hide_index=True, use_container_width=True, column_config=LINK)
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
                                    "Jours restants": r["daysLeft"], "Statut": STATUS_LABEL.get(r["statusNormalized"], r["statusNormalized"]), "Source": r["evidence"]["sourceId"],
                                    "URL": r["evidence"]["sourceUrl"], "Collecté le": fmt_dt(r["evidence"]["collectedAt"])} for r in exp["items"]]),
                     hide_index=True, use_container_width=True, column_config=LINK)
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

elif page == "Registre interne LPC":
    st.title("Rapprochement du registre interne LPC avec les sources officielles")
    st.caption("LPC a partagé la structure de sa liste SharePoint (pas les données). Chargez un export CSV/XLSX de cette liste, ou utilisez l'échantillon "
               "fictif (is_synthetic=true). Chaque ligne est normalisée (pays → ISO, « 12/31/2999 » → sans échéance, statut commercial séparé du statut réglementaire, "
               "actifs en texte libre → espèce + souche) puis rapprochée d'un enregistrement officiel par numéro, sinon par nom. Les écarts sont signalés, jamais corrigés.")
    up = st.file_uploader("Export de la liste SharePoint (CSV ou XLSX)", type=["csv", "xlsx"])
    if up is not None:
        r = httpx.post(f"{API}/registry/reconcile", files={"file": (up.name, up.getvalue())}, timeout=300)
        if r.status_code != 200:
            st.error(r.text)
            st.stop()
        rep = r.json()
    else:
        rep = api_get("/registry/reconcile/sample")
        st.info("Échantillon fictif chargé (11 lignes, is_synthetic=true). Déposez un fichier pour rapprocher vos propres lignes.")
    c = rep["counts"]
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Lignes", rep["total"]); k2.metric("Trouvées par n°", c["matched_by_number"]); k3.metric("Trouvées par nom", c["matched_by_name"])
    k4.metric("Non trouvées dans la source", c["not_found_in_source"]); k5.metric("Écarts à examiner", c["discrepancies"])
    table = []
    for x in rep["rows"]:
        disc = [f"{cmp['field']}: registre « {cmp['registry']} » vs officiel « {cmp['official']} »" for cmp in x["comparison"] if cmp["verdict"] == "discrepancy"]
        off = x["official"] or {}
        table.append({"#": x["row"], "Titre (registre)": x["title"], "Pays": f"{x['country_original']} → {x['country_code'] or '?'}",
                      "N° (registre)": x["registration_number_original"], "Statut registre": f"{x['status_original']} → {x['status_normalized']}",
                      "Échéance registre": x["expiration_date"] or ("sans échéance (2999)" if "no_expiry_convention" in x["flags"] else x["expiration_date_original"] or "—"),
                      "Rapprochement": x["match"], "Produit officiel": off.get("productName") or "—", "N° officiel": off.get("registrationNumber") or "—",
                      "Statut officiel": off.get("statusNormalized") or "—", "Échéance officielle": off.get("expirationDate") or "—",
                      "Écarts": "; ".join(disc) or "—", "Drapeaux": ", ".join(x["flags"]) or "—",
                      "Source": (x["evidence"] or {}).get("sourceId") or "—", "Collecté le": fmt_dt((x["evidence"] or {}).get("collectedAt")), "URL": (x["evidence"] or {}).get("sourceUrl")})
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True, column_config=LINK)
    with st.expander("Lignes normalisées (valeurs originales conservées) et détail des comparaisons"):
        st.json(rep["rows"])
    warnings_box(rep["warnings"])
    st.markdown("---")
    st.markdown("**Modèle cible Dataverse** (schema/dataverse_tables.xlsx) : la base peut être exportée dans cette structure.")
    v = api_get("/export/dataverse-validation")
    st.caption(f"Validation de l'export contre le classeur : {'conforme' if v['ok'] else 'écarts : ' + ', '.join(v['errors'])} · "
               + " · ".join(f"{t} {i['rows']} lignes" for t, i in v["tables"].items()))
    e1, e2 = st.columns(2)
    with e1:
        st.download_button("Export Dataverse (zip de CSV, un par table)", data=httpx.get(f"{API}/export/dataverse.zip", timeout=300).content,
                           file_name="lpc_dataverse_export.zip", mime="application/zip")
    with e2:
        st.download_button("Export Dataverse (classeur Excel)", data=httpx.get(f"{API}/export/dataverse.xlsx", timeout=300).content,
                           file_name="lpc_dataverse_export.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    disclaimer_box(rep["disclaimer"])

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
    st.download_button("Toute la base (CSV)", data=httpx.get(f"{API}/export.csv", timeout=180).content, file_name="lpc_regwatch_all.csv", mime="text/csv")
    disclaimer_box(src["disclaimer"])
