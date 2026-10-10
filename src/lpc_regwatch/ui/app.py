"""Streamlit workbench — a THIN client of the API (no direct database access, no business logic here).

Why: cahier §16 forbids logic locked in the UI; everything shown comes from the same endpoints that
Power Platform / Copilot Studio would call. API base URL from env API_BASE_URL.
Visual identity: Lallemand Plant Care (slate #36434b, Lallemand red #e30327, light greys) via .streamlit/config.toml.
Languages: French, English, Portuguese (ui/i18n.py); every string goes through `t()` so a language switch cannot break a page.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # `streamlit run src/lpc_regwatch/ui/app.py` without PYTHONPATH
from lpc_regwatch.ui.i18n import COUNTRY_NAMES, EXAMPLES, LANGS, tr  # noqa: E402

API = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
PILOTS = ["P-LPC-CONTANS", "P-LPC-G46", "P-LPC-M52"]
ALL_COUNTRIES = ["CA", "US", "FR", "BR", "DE", "BE", "MX", "UY"]
ISO3 = {"CA": "CAN", "US": "USA", "FR": "FRA", "BR": "BRA", "DE": "DEU", "BE": "BEL", "MX": "MEX", "UY": "URY", "ES": "ESP", "IT": "ITA", "NL": "NLD", "GB": "GBR", "PL": "POL"}
ISO3_TO_CC = {v: k for k, v in ISO3.items()}
CENTROIDS = {"CA": (56.1, -106.3), "US": (39.8, -98.6), "FR": (46.6, 2.2), "BR": (-14.2, -51.9), "DE": (51.2, 10.4), "BE": (50.5, 4.5), "MX": (23.6, -102.5),
             "UY": (-32.5, -55.8), "ES": (40.4, -3.7), "IT": (42.5, 12.5), "NL": (52.1, 5.3), "GB": (54.0, -2.0), "PL": (52.0, 19.0)}

# brand palette (lallemandplantcare.com): slate, Lallemand red, greys; map accents chosen to read on slate
SLATE, SLATE_DARK, RED, GREY, GREY_LIGHT, INK = "#36434b", "#2b363d", "#e30327", "#9ba1a5", "#ebeced", "#212529"
STATUS_COLOR = {"active": "#2fd27a", "expired": "#f0a21f", "withdrawn": RED, "pending": "#f5c842", "unknown": GREY}
MAP_KEYS = ["m.active", "m.related", "m.withdrawn", "m.pending", "m.notfound", "m.nosource"]
MAP_COLORS = {"m.active": "#2fd27a", "m.related": "#38c6ff", "m.withdrawn": RED, "m.pending": "#f5c842", "m.notfound": "#5e6b72", "m.nosource": "#434f56"}
ASSETS = Path(__file__).parent / "assets"
PAGES = ["page.overview", "page.compare", "page.map", "page.ask", "page.sisters", "page.watch", "page.registry", "page.sources"]

st.set_page_config(page_title="LPC Regulatory Watch", page_icon=str(ASSETS / "lallemand_logo.svg"), layout="wide", initial_sidebar_state="expanded")

if "lang" not in st.session_state:
    st.session_state["lang"] = "fr"


def t(key: str, **fmt) -> str:
    return tr(st.session_state.get("lang", "fr"), key, **fmt)


def cname(cc: str) -> str:
    return COUNTRY_NAMES.get(st.session_state.get("lang", "fr"), COUNTRY_NAMES["fr"]).get(cc, cc)


st.markdown(f"""
<style>
  section[data-testid="stSidebar"] {{ min-width: 300px; }}
  section[data-testid="stSidebar"] .block-container {{ padding-top: 1.2rem; }}
  section[data-testid="stSidebar"] [data-testid="stRadio"] label p {{ font-size: 0.95rem; }}
  section[data-testid="stSidebar"] [data-testid="stRadio"] > div {{ gap: 0.15rem; }}
  .lpc-logo {{ width:170px; margin:0 0 6px -4px; }}
  .lpc-logo svg {{ width:100%; height:auto; display:block; }}
  .lpc-brand {{ display:flex; align-items:center; gap:12px; margin-bottom:10px; }}
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


def st_label(status: str) -> str:
    return t(f"st.{status}") if status in STATUS_COLOR else status


def badge(status: str) -> str:
    return f'<span class="badge" style="background:{STATUS_COLOR.get(status, GREY)}">{st_label(status)}</span>'


def disclaimer_box(text: str | None = None):
    st.markdown(f'<div class="disclaimer">{t("disclaimer")}</div>', unsafe_allow_html=True)


def warnings_box(warnings: list[str]):
    if warnings:
        with st.expander(t("warnings.n", n=len(warnings)), expanded=False):
            for w in warnings:
                st.markdown(f'<div class="warn">• {w}</div>', unsafe_allow_html=True)


def map_status(active: int, withdrawn: int, expired: int, pending: int, coverage: str, related: int = 0) -> str:
    if active:
        return "m.active"
    if withdrawn or expired:
        return "m.withdrawn"
    if pending:
        return "m.pending"
    if related:
        return "m.related"
    return "m.nosource" if coverage == "source_not_collected" else "m.notfound"


def status_map(df: pd.DataFrame, key: str, height: int = 540, size_col: str | None = None) -> str | None:
    """Slate world map in the brand palette: coloured country fills + halo markers sized by `size_col`.
    `df["Statut"]` holds map status KEYS (m.*); labels are translated at render time. Returns the clicked ISO-3 or None."""
    fig = go.Figure()
    label_col = t("country")
    extra_cols = [c for c in df.columns if c not in ("iso3", label_col, "Statut")]
    for skey in MAP_KEYS:
        part = df[df["Statut"] == skey]
        if part.empty:
            continue
        hover = "<b>%{customdata[0]}</b><br>" + "<br>".join(f"{c}: %{{customdata[{i + 1}]}}" for i, c in enumerate(extra_cols))
        fig.add_trace(go.Choropleth(locations=part["iso3"], z=[1] * len(part), colorscale=[[0, MAP_COLORS[skey]], [1, MAP_COLORS[skey]]], showscale=False,
                                    marker_line_color=SLATE_DARK, marker_line_width=0.9, name=t(skey), showlegend=True,
                                    customdata=part[[label_col] + extra_cols].values, hovertemplate=hover + "<extra></extra>",
                                    marker_opacity=0.95 if skey in MAP_KEYS[:4] else 0.7))
    glow = df[df["Statut"].isin(MAP_KEYS[:4])]
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


def country_picker(df: pd.DataFrame, clicked: str | None, key: str, size_col: str) -> str:
    """Country pills under a map; a map click overrides the pills (widget state is updated before rendering)."""
    opts = list(df["iso3"])
    idx = df.set_index("iso3")
    labels = {i: f"{idx.loc[i, t('country')]} · {int(idx.loc[i, size_col])}" if size_col in df else str(idx.loc[i, t("country")]) for i in opts}
    state_key = f"{key}_pills"
    if clicked in opts and st.session_state.get(f"{key}_last_click") != clicked:
        st.session_state[state_key] = clicked
        st.session_state[f"{key}_last_click"] = clicked
    if st.session_state.get(state_key) not in opts:
        st.session_state[state_key] = opts[0]
    picked = st.pills(t("country"), opts, format_func=lambda i: labels[i], selection_mode="single", key=state_key, label_visibility="collapsed")
    return picked or st.session_state.get(f"{key}_last_click") or opts[0]


# ---------------------------------------------------------------------------------- sidebar
try:
    health = api_get("/health")
except Exception as e:  # noqa: BLE001
    st.error(t("api.down", api=API, err=e))
    st.stop()

with st.sidebar:
    logo = (ASSETS / "lallemand_logo.svg").read_text(encoding="utf-8") if (ASSETS / "lallemand_logo.svg").exists() else ""
    st.markdown(f'<div class="lpc-logo">{logo}</div><div class="lpc-brand"><div><div class="t1">Regulatory Watch</div><div class="t2">{t("app.subtitle")}</div></div></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="lpc-section">{t("sb.lang")}</div>', unsafe_allow_html=True)
    lang_pick = st.segmented_control(t("sb.lang"), list(LANGS), format_func=lambda k: LANGS[k], default=st.session_state["lang"], key="lang_ctl", label_visibility="collapsed")
    if lang_pick and lang_pick != st.session_state["lang"]:
        st.session_state["lang"] = lang_pick
        st.rerun()
    ai_txt = f'<span class="ok">{t("sb.ai_on")}</span> · {health.get("aiProvider")}' if health.get("aiEnabled") else f'<span class="off">{t("sb.ai_off")}</span>'
    st.markdown(f'<div class="lpc-card"><b>{health.get("registrations")}</b> {t("sb.records")} · v{health.get("version")}<br>{t("sb.ai")} : {ai_txt}<br>'
                f'{t("sb.last")} : {fmt_dt(health.get("lastSnapshotAt"))}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="lpc-section">{t("sb.nav")}</div>', unsafe_allow_html=True)
    page = st.radio(t("sb.nav"), PAGES, format_func=t, label_visibility="collapsed", key="page")
    with st.expander(t("sb.about")):
        st.markdown(f'<div class="lpc-section">{t("sb.pilots")}</div><ul class="lpc-list"><li>LALSTOP CONTANS WG</li><li>LALSTOP G46 WG</li><li>LALGUARD M52 OD</li></ul>'
                    f'<div class="lpc-section">{t("sb.sources")}</div><ul class="lpc-list"><li>Santé Canada — PPID</li><li>US EPA — PPLS</li><li>ANSES — E-Phy</li><li>MAPA — AGROFIT</li></ul>'
                    f'<div class="lpc-section">{t("sb.limits")}</div>', unsafe_allow_html=True)
        for k in ("sb.lim1", "sb.lim2", "sb.lim3", "sb.lim4", "sb.lim5"):
            st.markdown(f"- {t(k)}")
    st.markdown(f'<ul class="lpc-list" style="margin-top:10px"><li><a href="{API}/docs" target="_blank">{t("sb.api_docs")}</a></li><li><a href="/pitch/" target="_blank">{t("sb.pitch")}</a></li></ul>',
                unsafe_allow_html=True)

products = api_get("/products", {"limit": 500})["items"]
prod_label = {p["productId"]: f"{p['commercialName']}  ({', '.join(p['countries']) or t('no_country')})" for p in products}
ordered = PILOTS + sorted([p["productId"] for p in products if p["productId"] not in PILOTS], key=lambda i: prod_label[i])
LINK = {"URL": st.column_config.LinkColumn("URL", display_text=t("source").lower())}


def product_picker(key: str) -> str:
    q = st.text_input(t("search"), key=f"q_{key}", placeholder=t("search.ph"))
    if q:
        res = api_get("/products", {"q": q, "limit": 50})
        if not res["items"]:
            st.warning(res["warnings"][0])
            return st.selectbox(t("product"), ordered, format_func=lambda i: prod_label.get(i, i), key=f"sel_{key}")
        opts = [p["productId"] for p in res["items"]]
        return st.selectbox(t("product"), opts, format_func=lambda i: f"{prod_label.get(i, i)}  · {t('found_via')} {next(p['matchedOn'] for p in res['items'] if p['productId'] == i)}",
                            key=f"sel_{key}")
    return st.selectbox(t("product"), ordered, format_func=lambda i: prod_label.get(i, i), key=f"sel_{key}")


def uses_table(reg: dict) -> pd.DataFrame:
    rows = []
    for u in reg["uses"]:
        rows.append({
            t("country"): reg["countryCode"], t("number"): reg["registrationNumber"],
            t("u.crop_o"): u["cropOriginal"], t("u.crop_n"): u["cropNormalized"], t("u.eppo_crop"): f"{u['eppoCropCode'] or '—'} [{u['eppoCropStatus']}]",
            t("u.target_o"): u["targetOriginal"], t("u.target_n"): u["targetNormalized"], t("u.eppo_target"): u["eppoTargetCode"] or "—",
            t("u.dose"): f"{u['doseValue']} {u['doseUnitOriginal']}" if u["doseValue"] is not None else t("u.dose_missing"),
            t("u.dose_n"): f"{u['doseValueNormalized']} {u['doseUnitNormalized']}" if u["doseValueNormalized"] is not None else "—",
            t("u.phi"): u["phiDays"], t("u.maxapp"): u["maxApplications"],
            "BBCH": f"{u['growthStageMin'] or ''}-{u['growthStageMax'] or ''}" if u["growthStageMin"] or u["growthStageMax"] else "",
            t("cmp.pairing"): u["pairing"], t("cmp.extraction"): u["evidence"]["extractionMethod"], t("cmp.conf"): u["evidence"]["confidence"],
            t("validation"): u["evidence"]["validationStatus"], t("u.restr"): (u["restrictionsOriginal"] or "")[:200],
            t("source"): u["evidence"]["sourceId"], t("collected"): fmt_dt(u["evidence"]["collectedAt"]), "URL": u["evidence"]["sourceUrl"],
        })
    return pd.DataFrame(rows)


def country_detail_table(regs: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{t("product"): r["productName"], t("number"): r["registrationNumber"], t("status"): st_label(r["statusNormalized"]),
                          t("status_orig"): r["statusOriginal"], t("expires"): r["expirationDate"] or "—", t("holder"): r["holder"], t("uses"): r["usesCount"],
                          t("microorganism"): r["activeEntityNormalized"], t("validation"): r["validationStatus"], t("source"): r["sourceId"],
                          t("collected"): fmt_dt(r["collectedAt"]), "URL": r["sourceUrl"]} for r in regs])


# ---------------------------------------------------------------------------------- pages
if page == "page.overview":
    st.title(t("ov.title"))
    c1, c2, c3 = st.columns([2.2, 2, 1])
    scope_keys = ["ov.scope.pilots", "ov.scope.lallemand", "ov.scope.all", "ov.scope.product"]
    with c1:
        scope_key = st.radio(t("ov.scope"), scope_keys, format_func=t, horizontal=True, key="ov_scope")
    scope = {"ov.scope.pilots": "pilots", "ov.scope.lallemand": "lallemand", "ov.scope.all": "all", "ov.scope.product": "product"}[scope_key]
    params = {"scope": scope}
    with c2:
        if scope == "product":
            params["productId"] = product_picker("ov")
    with c3:
        params["months"] = st.number_input(t("ov.months"), 1, 60, 12)
    ov = api_get("/overview", params)
    if "__404__" in ov:
        st.error(ov["__404__"]["message"])
        st.stop()
    tt = ov["totals"]
    k = st.columns(6)
    for col, (v, lbl) in zip(k, [(tt["sourcesConnected"], t("ov.k.sources")), (tt["countriesFound"], t("ov.k.countries")), (tt["products"], t("products")),
                                  (tt["registrations"], t("registrations")), (tt["active"], t("ov.k.active")), (tt["expiringSoon"], t("ov.k.expiring", m=ov["months"]))]):
        col.markdown(f'<div class="kpi"><div class="v">{v}</div><div class="l">{lbl}</div></div>', unsafe_allow_html=True)
    rows = []
    for c in ov["countries"]:
        if c["countryCode"] not in ISO3:
            continue
        prods = sorted({r["productName"] for r in c["registrations"]})
        rows.append({"iso3": ISO3[c["countryCode"]], t("country"): cname(c["countryCode"]),
                     "Statut": map_status(c["active"], c["withdrawn"], c["expired"], c["pending"], c["coverage"]),
                     t("registrations"): c["active"] + c["withdrawn"] + c["expired"] + c["pending"] + c["unknown"], t("ov.col.actives"): c["active"],
                     t("ov.col.withdrawn"): c["withdrawn"] + c["expired"], t("ov.col.pending"): c["pending"], t("products"): c["products"], t("uses"): c["usesCount"],
                     t("ov.col.expiring"): c["expiringSoon"], t("m.other_in_store"): c.get("totalInStore", 0),
                     t("source"): c["sourceId"] or t("none"), t("collected"): fmt_dt(c["collectedAt"]),
                     t("ov.col.list"): (", ".join(prods[:6]) + (" …" if len(prods) > 6 else "")) or "—"})
    df = pd.DataFrame(rows)
    clicked = status_map(df, "ov_map", 580, size_col=t("registrations"))
    st.caption(t("ov.caption"))
    sel_iso = country_picker(df, clicked, "ov", t("registrations"))
    cc = ISO3_TO_CC[sel_iso]
    c = next(x for x in ov["countries"] if x["countryCode"] == cc)
    st.markdown(f"### {cname(cc)} ({cc}) — {c['sourceId'] or t('none_country')}" + (f" · {t('collected').lower()} {fmt_dt(c['collectedAt'])}" if c["collectedAt"] else ""))
    if c["registrations"]:
        st.dataframe(country_detail_table(c["registrations"]), hide_index=True, use_container_width=True, column_config=LINK)
    elif c["coverage"] == "not_found_in_source":
        st.info(t("ov.notfound", src=c["sourceId"], at=fmt_dt(c["collectedAt"]), n=c.get("totalInStore", 0)))
    else:
        st.warning(t("ov.nosource"))
    with st.expander(t("ov.table")):
        view = df.drop(columns=["iso3"]).copy()
        view["Statut"] = view["Statut"].map(t)
        view = view.rename(columns={"Statut": t("status")})
        st.dataframe(view, hide_index=True, use_container_width=True)
    disclaimer_box(ov["disclaimer"])

elif page == "page.compare":
    st.title(t("cmp.title"))
    col1, col2 = st.columns([2, 2])
    with col1:
        pid = product_picker("cmp")
    with col2:
        countries = st.multiselect(t("countries"), ALL_COUNTRIES, default=["CA", "US", "FR", "BR"], format_func=lambda c: f"{cname(c)} ({c})")
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
            mrows.append({"iso3": ISO3[cc], t("country"): cname(cc),
                          "Statut": map_status(sum(r["statusNormalized"] == "active" for r in regs), sum(r["statusNormalized"] == "withdrawn" for r in regs),
                                               sum(r["statusNormalized"] == "expired" for r in regs), sum(r["statusNormalized"] == "pending" for r in regs),
                                               cov["coverage"], len(rel_by_cc.get(cc, []))),
                          t("number"): ", ".join(f"{r['registrationNumber']} ({r['statusOriginal']})" for r in regs) or "—",
                          t("expires"): ", ".join(r["expirationDate"] or "—" for r in regs) or "—", t("uses"): sum(r["usesCount"] for r in regs),
                          t("cmp.related_short"): ", ".join(f"{rp['commercialName']} {r['registrationNumber']}" for rp, r in rel_by_cc.get(cc, [])) or "—",
                          t("source"): cov["sourceId"] or t("none"), t("collected"): fmt_dt(cov["collectedAt"])})
        mdf = pd.DataFrame(mrows)
        clicked = status_map(mdf, "cmp_map", 440, size_col=t("uses"))
        focus = ISO3_TO_CC.get(clicked) if clicked else None
        cols = st.columns(len(countries))
        for c, cc in zip(cols, countries):
            cov = next(x for x in data["coverage"] if x["countryCode"] == cc)
            border = f"border:2px solid {RED};" if focus == cc else ""
            with c:
                if cov["coverage"] == "found":
                    inner = ""
                    for r in regs_by_cc.get(cc, []):
                        inner += (f'{badge(r["statusNormalized"])} <b>{t("number")} {r["registrationNumber"]}</b><div class="m">« {r["statusOriginal"]} » · {r["usesCount"]} {t("uses").lower()} · '
                                  f'{t("expires").lower()} {r["expirationDate"] or "—"}<br><a href="{r["evidence"]["sourceUrl"]}" target="_blank">{r["evidence"]["sourceId"]}</a> · '
                                  f'{fmt_dt(r["evidence"]["collectedAt"])}<br><code>{r["evidence"]["validationStatus"]}</code></div>')
                elif cov["coverage"] == "not_found_in_source":
                    inner = (f'<span class="badge" style="background:{GREY}">{t("cmp.not_in", src=cov["sourceId"])}</span><div class="m">{t("collected").lower()} '
                             f'{fmt_dt(cov["collectedAt"])}<br>{t("cmp.neq")}</div>')
                    if rel_by_cc.get(cc):
                        inner += f'<div class="m">{t("cmp.related_short")} : ' + ", ".join(f"{rp['commercialName']} ({r['registrationNumber']})" for rp, r in rel_by_cc[cc]) + "</div>"
                else:
                    inner = f'<span class="badge" style="background:{SLATE}">{t("m.nosource")}</span><div class="m">{t("cmp.unknown_not_absent")}</div>'
                st.markdown(f'<div class="ccard" style="{border}"><h4>{cname(cc)} ({cc})</h4>{inner}</div>', unsafe_allow_html=True)
        warnings_box(data["warnings"])
        if data.get("relatedProducts"):
            st.markdown(f"### {t('cmp.related_h')}")
            st.caption(t("cmp.related_cap"))
            rel_rows = []
            for rp in data["relatedProducts"]:
                for r in rp["registrations"] or [None]:
                    rel_rows.append({t("cmp.related_col"): rp["commercialName"], t("cmp.relation"): rp["relationship"], t("cmp.review"): rp["reviewStatus"],
                                     t("cmp.conf"): rp["confidence"], t("country"): r["countryCode"] if r else "—", t("number"): r["registrationNumber"] if r else "—",
                                     t("status"): st_label(r["statusNormalized"]) if r else t("cmp.rel_none"),
                                     t("expires"): (r["expirationDate"] or "—") if r else "—", t("source"): r["evidence"]["sourceId"] if r else "—",
                                     t("collected"): fmt_dt(r["evidence"]["collectedAt"]) if r else "—", "URL": r["evidence"]["sourceUrl"] if r else None,
                                     t("cmp.rel_evidence"): rp["evidence"]})
            st.dataframe(pd.DataFrame(rel_rows), hide_index=True, use_container_width=True, column_config=LINK)
        st.markdown(f"### {t('cmp.uses_h')}")
        frames = [uses_table(r) for r in data["registrations"] if r["uses"]]
        if frames:
            df = pd.concat(frames, ignore_index=True)
            f1, f2, f3 = st.columns(3)
            with f1:
                crop_f = st.text_input(t("cmp.filter_crop"), "")
            with f2:
                pairing_f = st.multiselect(t("cmp.pairing"), sorted(df[t("cmp.pairing")].unique()), default=sorted(df[t("cmp.pairing")].unique()))
            with f3:
                extr_f = st.multiselect(t("cmp.extraction"), sorted(df[t("cmp.extraction")].unique()), default=sorted(df[t("cmp.extraction")].unique()))
            view = df[df[t("cmp.pairing")].isin(pairing_f) & df[t("cmp.extraction")].isin(extr_f)]
            if crop_f:
                m = view[t("u.crop_o")].fillna("").str.contains(crop_f, case=False) | view[t("u.crop_n")].fillna("").str.contains(crop_f, case=False)
                view = view[m]
            st.caption(t("cmp.rows_cap", n=len(view)))
            st.dataframe(view, use_container_width=True, hide_index=True, column_config=LINK)
        else:
            st.info(t("cmp.no_uses"))
        st.markdown(f"### {t('cmp.detail_h')}")
        for r in data["registrations"]:
            with st.expander(f"{r['countryCode']} · {r['registrationNumber']} · {r['statusOriginal']} → {r['statusNormalized']}"):
                a, b = st.columns(2)
                with a:
                    st.markdown(f"**{t('cmp.originals')}**")
                    st.json({"statusOriginal": r["statusOriginal"], "holderOriginal": r["holderOriginal"], "activeEntityOriginal": r["activeEntityOriginal"],
                             "formulationOriginal": r["formulationOriginal"], "approvalDate": r["approvalDate"], "expirationDate": r["expirationDate"]})
                with b:
                    st.markdown(f"**{t('cmp.evidence')}**")
                    st.json(r["evidence"])
        ex1, ex2 = st.columns(2)
        with ex1:
            st.download_button(t("cmp.export_csv"), data=httpx.get(f"{API}/export.csv", params={"productId": pid, "countries": ",".join(countries)}, timeout=120).content,
                               file_name=f"{pid}_{'_'.join(countries)}.csv", mime="text/csv")
        with ex2:
            st.download_button(t("cmp.export_xlsx"), data=httpx.get(f"{API}/export.xlsx", params={"productId": pid, "countries": ",".join(countries)}, timeout=120).content,
                               file_name=f"{pid}_{'_'.join(countries)}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        disclaimer_box(data["disclaimer"])

elif page == "page.map":
    st.title(t("map.title"))
    mode = st.radio(t("map.mode"), ["map.mode.product", "map.mode.species"], format_func=t, horizontal=True, key="map_mode")
    rows, warnings = [], []
    detail: dict[str, list] = {}
    if mode == "map.mode.product":
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
            rows.append({"iso3": ISO3[cc], t("country"): cname(cc), "Statut": status, t("registrations"): len(regs) + len(rel),
                         t("number"): "; ".join(f"{r['registrationNumber']} ({r['statusOriginal']}, {t('expires').lower()} {r['expirationDate'] or '—'})" for r in regs) or "—",
                         t("cmp.related_short"): "; ".join(f"{rp['commercialName']} {r['registrationNumber']} ({rp['relationship']})" for rp, r in rel) or "—",
                         t("uses"): sum(r["usesCount"] for r in regs), t("source"): c["sourceId"] or "—", t("collected"): fmt_dt(c["collectedAt"])})
            detail[ISO3[cc]] = [{"productName": data.get("commercialName"), **r, "holder": r["holderOriginal"], "activeEntityNormalized": None,
                                 "sourceId": r["evidence"]["sourceId"], "sourceUrl": r["evidence"]["sourceUrl"], "collectedAt": r["evidence"]["collectedAt"],
                                 "validationStatus": r["evidence"]["validationStatus"]} for r in regs] + \
                               [{"productName": f"{rp['commercialName']} ({t('map.related_tag')} : {rp['relationship']})", **r, "holder": r["holderOriginal"],
                                 "activeEntityNormalized": None, "sourceId": r["evidence"]["sourceId"], "sourceUrl": r["evidence"]["sourceUrl"],
                                 "collectedAt": r["evidence"]["collectedAt"], "validationStatus": r["evidence"]["validationStatus"]} for rp, r in rel]
    else:
        species = st.text_input(t("map.species"), "Clonostachys rosea")
        crop = st.text_input(t("map.crop"), "")
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
            rows.append({"iso3": ISO3[cc], t("country"): cname(cc), "Statut": status, t("registrations"): len(regs), t("products"): len({r["productId"] for r in regs}),
                         t("map.strains"): "; ".join(sorted({(r["activeEntityNormalized"] or "").replace(species, "").strip() or "—" for r in regs})) or "—"})
            detail[ISO3[cc]] = [{**r, "holder": r["holderOriginal"], "sourceId": r["evidence"]["sourceId"], "sourceUrl": r["evidence"]["sourceUrl"],
                                 "collectedAt": r["evidence"]["collectedAt"], "validationStatus": r["evidence"]["validationStatus"]} for r in regs]
    df = pd.DataFrame(rows)
    clicked = status_map(df, "carte_map", 560, size_col=t("registrations"))
    sel = country_picker(df, clicked, "carte", t("registrations"))
    st.markdown(f"#### {df.set_index('iso3').loc[sel, t('country')]}")
    if detail.get(sel):
        st.dataframe(country_detail_table(detail[sel]), hide_index=True, use_container_width=True, column_config=LINK)
    else:
        st.info(t(df.set_index("iso3").loc[sel, "Statut"]).capitalize() + " — " + t("map.nothing"))
    warnings_box(warnings)
    disclaimer_box()

elif page == "page.ask":
    st.title(t("ask.title"))
    st.caption(t("ask.caption"))
    lang = st.session_state["lang"]
    ex = st.selectbox(t("ask.examples"), [""] + EXAMPLES.get(lang, EXAMPLES["fr"]))
    q = st.text_area(t("ask.q"), value=ex, height=80)
    ans_lang = st.radio(t("ask.lang"), list(LANGS), format_func=lambda k: LANGS[k], index=list(LANGS).index(lang), horizontal=True)
    if st.button(t("ask.go"), type="primary") and q.strip():
        with st.spinner(t("ask.spinner")):
            ans = api_post("/ask", {"question": q, "language": ans_lang})
        sa = ans.get("structured") or {}
        st.markdown(f"#### {sa.get('headline') or t('ask.answer')}")
        items = sa.get("items") or []
        if items:
            cols_map = [("country", t("country")), ("product", t("product")), ("registrationNumber", t("number")), ("status", t("status")), ("statusOriginal", t("status_orig")),
                        ("expiry", t("expires")), ("relationship", t("ask.item.relationship")), ("detail", t("ask.item.detail")), ("sourceId", t("source")), ("collectedAt", t("collected"))]
            rows = [{lbl: (st_label(it[k]) if k == "status" and it.get(k) in STATUS_COLOR else it.get(k)) for k, lbl in cols_map if any(x.get(k) for x in items)} for it in items]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        for cv in sa.get("caveats") or []:
            st.markdown(f'<div class="warn">• {cv}</div>', unsafe_allow_html=True)
        st.caption(t("ask.meta", intent=ans["intent"], tools=", ".join(ans["toolsUsed"]) or "—", model=ans["model"] or t("ask.det")))
        other = [w for w in ans["warnings"] if w not in (sa.get("caveats") or [])]
        warnings_box(other)
        with st.expander(t("ask.evidence", n=len(ans["evidence"]))):
            if ans["evidence"]:
                ev = pd.DataFrame([{t("source"): e["sourceId"], "URL": e["sourceUrl"], t("collected"): fmt_dt(e["collectedAt"]), t("validation"): e["validationStatus"],
                                    t("cmp.extraction"): e.get("extractionMethod"), t("ask.excerpt"): (e.get("excerpt") or "")[:160]} for e in ans["evidence"]])
                st.dataframe(ev, hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL", display_text=t("ask.open"))})
            else:
                st.info(t("ask.no_evidence"))
        with st.expander(t("ask.facts")):
            st.json(ans["facts"])
    disclaimer_box()

elif page == "page.sisters":
    st.title(t("sis.title"))
    pid = product_picker("sis")
    al = api_get(f"/products/{pid}/aliases")
    if "__404__" in al:
        st.error(al["__404__"]["message"])
        st.stop()
    if not al:
        st.info(t("sis.none"))
    else:
        df = pd.DataFrame([{t("sis.name"): a["aliasName"], t("cmp.relation"): a["relationshipType"], t("country"): a["countryCode"] or "—", t("cmp.conf"): a["confidence"],
                            t("cmp.review"): a["reviewStatus"], t("sis.evidence"): a["evidence"], "URL": a["sourceRecordUrl"], "id": a["aliasId"]} for a in al])
        st.caption(t("sis.caption"))
        st.dataframe(df.drop(columns=["id"]), hide_index=True, use_container_width=True, column_config=LINK)
        st.markdown(f"### {t('sis.review_h')}")
        st.caption(t("sis.review_cap"))
        c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
        idx = df.set_index("id")
        with c1:
            target = st.selectbox(t("sis.target"), df["id"], format_func=lambda i: f"{idx.loc[i, t('sis.name')]} ({idx.loc[i, t('cmp.relation')]}, {idx.loc[i, t('cmp.review')]})")
        with c2:
            new = st.selectbox(t("sis.new"), ["validated", "rejected", "to_verify", "obsolete"])
        with c3:
            reviewer = st.text_input(t("sis.reviewer"), "")
        with c4:
            note = st.text_input(t("sis.note"), "")
        if st.button(t("sis.save"), disabled=not reviewer):
            res = api_post("/review", {"entityType": "alias", "entityId": target, "newStatus": new, "reviewer": reviewer, "note": note})
            st.success(t("sis.saved", id=res["entityId"], old=res["oldStatus"], new=res["newStatus"], who=res["reviewer"]))
            api_get.clear()
        log = api_get("/review/log", {"limit": 50})
        if log:
            st.markdown(f"#### {t('sis.log')}")
            st.dataframe(pd.DataFrame(log), hide_index=True, use_container_width=True)
    disclaimer_box()

elif page == "page.watch":
    st.title(t("watch.title"))
    months = st.slider(t("watch.horizon"), 1, 60, 12)
    exp = api_get("/expiring", {"months": months})
    st.markdown(f"### {t('watch.exp_h', m=months, n=len(exp['items']))}")
    if exp["items"]:
        st.dataframe(pd.DataFrame([{t("product"): r["productName"], t("country"): r["countryCode"], t("number"): r["registrationNumber"], t("watch.expires_on"): r["expirationDate"],
                                    t("watch.days_left"): r["daysLeft"], t("status"): st_label(r["statusNormalized"]), t("source"): r["evidence"]["sourceId"],
                                    "URL": r["evidence"]["sourceUrl"], t("collected"): fmt_dt(r["evidence"]["collectedAt"])} for r in exp["items"]]),
                     hide_index=True, use_container_width=True, column_config=LINK)
    warnings_box(exp["warnings"])
    ch = api_get("/changes", {"limit": 300})
    st.markdown(f"### {t('watch.changes_h', n=len(ch))}")
    st.caption(t("watch.changes_cap"))
    if ch:
        st.dataframe(pd.DataFrame([{t("watch.detected"): fmt_dt(c["detectedAt"]), t("watch.entity"): c["entityId"], t("watch.field"): c["field"], t("watch.before"): c["oldValue"],
                                    t("watch.after"): c["newValue"], "Snapshot": f"{c['fromSnapshotId'] or '—'} → {c['toSnapshotId']}"} for c in ch]),
                     hide_index=True, use_container_width=True)
    else:
        st.info(t("watch.no_changes"))
    disclaimer_box()

elif page == "page.registry":
    st.title(t("reg.title"))
    st.caption(t("reg.caption"))
    up = st.file_uploader(t("reg.upload"), type=["csv", "xlsx"])
    if up is not None:
        r = httpx.post(f"{API}/registry/reconcile", files={"file": (up.name, up.getvalue())}, timeout=300)
        if r.status_code != 200:
            st.error(r.text)
            st.stop()
        rep = r.json()
    else:
        rep = api_get("/registry/reconcile/sample")
        st.info(t("reg.sample"))
    c = rep["counts"]
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(t("reg.rows"), rep["total"]); k2.metric(t("reg.by_number"), c["matched_by_number"]); k3.metric(t("reg.by_name"), c["matched_by_name"])
    k4.metric(t("reg.not_found"), c["not_found_in_source"]); k5.metric(t("reg.disc"), c["discrepancies"])
    table = []
    for x in rep["rows"]:
        disc = [t("reg.disc_fmt", f=cmp["field"], r=cmp["registry"], o=cmp["official"]) for cmp in x["comparison"] if cmp["verdict"] == "discrepancy"]
        off = x["official"] or {}
        table.append({"#": x["row"], t("reg.title_col"): x["title"], t("country"): f"{x['country_original']} → {x['country_code'] or '?'}",
                      t("reg.num_col"): x["registration_number_original"], t("reg.status_col"): f"{x['status_original']} → {x['status_normalized']}",
                      t("reg.exp_col"): x["expiration_date"] or (t("reg.noexp") if "no_expiry_convention" in x["flags"] else x["expiration_date_original"] or "—"),
                      t("reg.match"): x["match"], t("reg.off_product"): off.get("productName") or "—", t("reg.off_num"): off.get("registrationNumber") or "—",
                      t("reg.off_status"): off.get("statusNormalized") or "—", t("reg.off_exp"): off.get("expirationDate") or "—",
                      t("reg.disc_col"): "; ".join(disc) or "—", t("reg.flags"): ", ".join(x["flags"]) or "—",
                      t("source"): (x["evidence"] or {}).get("sourceId") or "—", t("collected"): fmt_dt((x["evidence"] or {}).get("collectedAt")), "URL": (x["evidence"] or {}).get("sourceUrl")})
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True, column_config=LINK)
    with st.expander(t("reg.raw")):
        st.json(rep["rows"])
    warnings_box(rep["warnings"])
    st.markdown("---")
    st.markdown(t("reg.dv_h"))
    v = api_get("/export/dataverse-validation")
    res = t("reg.dv_ok") if v["ok"] else t("reg.dv_bad", t=", ".join(v["errors"]))
    st.caption(t("reg.dv_val", res=res, tables=" · ".join(f"{tb} {i['rows']} {t('reg.dv_rows')}" for tb, i in v["tables"].items())))
    e1, e2 = st.columns(2)
    with e1:
        st.download_button(t("reg.dv_zip"), data=httpx.get(f"{API}/export/dataverse.zip", timeout=300).content, file_name="lpc_dataverse_export.zip", mime="application/zip")
    with e2:
        st.download_button(t("reg.dv_xlsx"), data=httpx.get(f"{API}/export/dataverse.xlsx", timeout=300).content, file_name="lpc_dataverse_export.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    disclaimer_box(rep["disclaimer"])

elif page == "page.sources":
    st.title(t("src.title"))
    src = api_get("/sources")
    df = pd.DataFrame([{t("source"): s["sourceId"], t("src.name"): s["officialName"], t("src.region"): s["countryOrRegion"], t("src.access"): s["accessMethod"],
                        t("src.format"): s["dataFormat"], t("src.licence"): s["licenseName"], t("src.limits"): s["accessAndReuseLimits"], t("registrations"): s["registrations"],
                        t("src.last"): fmt_dt(s["lastCollectedAt"]), "URL": s["baseUrl"]} for s in src["items"]])
    st.dataframe(df, hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL", display_text=t("ask.open"))})
    st.markdown(f"### {t('src.quality_h')}")
    pid = product_picker("dq")
    dq = api_get(f"/products/{pid}/quality")
    if "__404__" not in dq:
        st.dataframe(pd.DataFrame([{t("src.registration"): i["registrationId"], t("country"): i["countryCode"], t("status"): st_label(i["statusNormalized"]),
                                    t("validation"): i["validationStatus"], t("cmp.pairing"): ", ".join(i["pairing"]), t("src.missing"): "; ".join(i["missingOrUncertain"]) or "—"}
                                   for i in dq["registrations"]]), hide_index=True, use_container_width=True)
        warnings_box(dq["warnings"])
    st.markdown(f"### {t('src.export_h')}")
    st.download_button(t("src.export_all"), data=httpx.get(f"{API}/export.csv", timeout=180).content, file_name="lpc_regwatch_all.csv", mime="text/csv")
    disclaimer_box(src["disclaimer"])
