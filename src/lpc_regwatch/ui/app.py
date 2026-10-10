"""Streamlit workbench — a THIN client of the API (no direct database access, no business logic here).

Why: cahier §16 forbids logic locked in the UI; everything shown comes from the same endpoints that
Power Platform / Copilot Studio would call. API base URL from env API_BASE_URL.
Visual identity: Lallemand Plant Care (slate #36434b, Lallemand red #e30327, light greys) via .streamlit/config.toml.
Languages: French, English, Portuguese (ui/i18n.py); every string goes through `t()` so a language switch cannot break a page.
"""
from __future__ import annotations

import base64
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # `streamlit run src/lpc_regwatch/ui/app.py` without PYTHONPATH
from lpc_regwatch.ui.i18n import COUNTRY_IN, COUNTRY_NAMES, EXAMPLES, LANGS, tr  # noqa: E402

API = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
API_PUBLIC = os.getenv("API_PUBLIC_URL", API).rstrip("/")  # what the browser can open (behind the proxy: /api)
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
TOOLS = ["page.overview", "page.compare", "page.map", "page.sisters", "page.watch", "page.registry", "page.sources"]  # data & monitoring pages
PAGES = ["page.home", "page.chat"] + TOOLS
TOOL_ICONS = {"page.overview": ":material/public:", "page.compare": ":material/compare_arrows:", "page.map": ":material/map:", "page.sisters": ":material/account_tree:",
              "page.watch": ":material/monitoring:", "page.registry": ":material/fact_check:", "page.sources": ":material/database:"}
STARTER_ICONS = [":material/public:", ":material/compare_arrows:", ":material/fact_check:", ":material/account_tree:", ":material/microbiology:", ":material/event:"]
BOT_AVATAR = ":material/microbiology:"
STATUS_TEXT = {"active": "#1e8e4e", "withdrawn": "#c8102e", "expired": "#c76b00", "pending": "#b8860b", "unknown": "#5b6770"}
RAIL_ITEMS = [("chat", ":material/forum:"), ("page.overview", ":material/public:"), ("page.compare", ":material/compare_arrows:"), ("page.map", ":material/map:"),
              ("page.sisters", ":material/account_tree:"), ("page.watch", ":material/monitoring:"), ("page.registry", ":material/fact_check:"), ("page.sources", ":material/database:")]


def pattern_svg(stroke: str = "rgba(54,67,75,0.07)") -> str:
    """Faint repeating micro-organism motifs for the chat background (one 480 px tile)."""
    sw = 1.6
    bact = (f'<g transform="translate(40 60)"><rect x="0" y="6" width="52" height="22" rx="11" fill="none" stroke="{stroke}" stroke-width="{sw}"/>'
            f'<path d="M0 17c-5 0-6-6-11-6M52 17c5 0 6 6 11 6M16 6V1M36 6V1M16 28v5M36 28v5" stroke="{stroke}" stroke-width="{sw}" stroke-linecap="round" fill="none"/></g>')
    spore = (f'<g transform="translate(300 180)"><path d="M26 56V28M26 34c-9-2-15-9-17-19M26 34c9-2 15-9 17-19M26 28V10" stroke="{stroke}" stroke-width="{sw}" stroke-linecap="round" fill="none"/>'
             f'<circle cx="9" cy="9" r="6" fill="none" stroke="{stroke}" stroke-width="{sw}"/><circle cx="43" cy="9" r="6" fill="none" stroke="{stroke}" stroke-width="{sw}"/><circle cx="26" cy="4" r="6" fill="none" stroke="{stroke}" stroke-width="{sw}"/></g>')
    leaf = (f'<g transform="translate(120 320)"><path d="M0 44C1 20 20 0 56 0c0 36-16 52-40 52-7 0-12-3-16-8z" fill="none" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"/>'
            f'<path d="M8 42C20 32 34 20 50 8" stroke="{stroke}" stroke-width="{sw}" stroke-linecap="round" fill="none"/></g>')
    cell = (f'<g transform="translate(380 380)"><circle cx="20" cy="20" r="18" fill="none" stroke="{stroke}" stroke-width="{sw}"/><circle cx="14" cy="16" r="3" fill="none" stroke="{stroke}" stroke-width="{sw}"/>'
            f'<circle cx="26" cy="24" r="3" fill="none" stroke="{stroke}" stroke-width="{sw}"/></g>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="480" viewBox="0 0 480 480">{bact}{spore}{leaf}{cell}</svg>'


PATTERN_URI = "data:image/svg+xml;base64," + base64.b64encode(pattern_svg().encode("utf-8")).decode("ascii")
LOGO_URI = "data:image/svg+xml;base64," + base64.b64encode((ASSETS / "lallemand_logo.svg").read_bytes()).decode("ascii") if (ASSETS / "lallemand_logo.svg").exists() else ""




st.set_page_config(page_title="LPC Regulatory Watch", page_icon=str(ASSETS / "lallemand_logo.svg"), layout="wide", initial_sidebar_state="expanded")

if "lang" not in st.session_state:
    st.session_state["lang"] = "fr"



def t(key: str, **fmt) -> str:
    return tr(st.session_state.get("lang", "fr"), key, **fmt)


def cname(cc: str) -> str:
    return COUNTRY_NAMES.get(st.session_state.get("lang", "fr"), COUNTRY_NAMES["fr"]).get(cc, cc)


def lang_key(base: str) -> str:
    """Widget key scoped to the current language. Option labels are part of a radio's identity in the browser: after a
    language switch the server keeps the value but the page shows no selected option. A fresh key per language, seeded
    with the authoritative value kept in `st.session_state[base]`, keeps both the value and the visible selection."""
    lang = st.session_state.get("lang", "fr")
    key = f"{base}__{lang}"
    if st.session_state.get(f"{base}__lang") != lang:  # first render in this language (or first render at all)
        if base in st.session_state:
            st.session_state[key] = st.session_state[base]
        st.session_state[f"{base}__lang"] = lang
    return key


st.markdown(f"""
<style>
  section[data-testid="stSidebar"] {{ min-width: 280px; margin:10px 0 10px 10px; height:calc(100vh - 20px); border-radius:18px; background:#fff;
                                      box-shadow:0 10px 30px rgba(33,37,41,.10), 0 1px 2px rgba(33,37,41,.06); border:1px solid #e6e8ea; }}
  section[data-testid="stSidebar"] > div:first-child {{ border-radius:18px; }}
  section[data-testid="stSidebar"] [data-testid="stButton"] button {{ justify-content:flex-start; text-align:left; }}
  section[data-testid="stSidebar"] [data-testid="stButton"] button p {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:220px; font-size:.9rem; }}
  section[data-testid="stSidebar"] [data-testid="stExpander"] details {{ border:none; background:transparent; }}
  section[data-testid="stSidebar"] [data-testid="stExpander"] summary {{ padding:.3rem 0; }}
  section[data-testid="stSidebar"] [data-testid="stExpander"] summary p {{ font-size:.78rem; letter-spacing:.12em; text-transform:uppercase; color:#6b767d; }}
  [data-testid="stChatMessage"] {{ background:transparent; padding:.25rem 0; gap:.5rem; }}
  [data-testid="stChatMessageAvatarUser"] {{ display:none; }}
  [data-testid="stChatMessageAvatarCustom"] {{ background:{RED}; border:none; border-radius:50%; width:30px; height:30px; margin-top:2px; }}
  [data-testid="stChatMessageAvatarCustom"] span {{ color:#fff !important; font-size:18px; }}
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {{ margin:0 0 0 auto; flex:0 1 auto; width:auto; max-width:78%; background:#e7eaed; border-radius:18px 18px 4px 18px; padding:.6rem 1rem; }}
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] p {{ margin:0; }}
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarCustom"]) [data-testid="stChatMessageContent"] {{ padding:.25rem 0 0; }}
  section.stMain h1.hero {{ margin-top:6vh; }}
  .chat-map-cap {{ text-align:center; color:#6b767d; font-size:.82rem; margin:-.2rem 0 1rem; }}
  .lpc-brand .mark {{ display:flex; align-items:center; }}
  .sb-art {{ display:flex; gap:4px; align-items:flex-end; }}
  .sb-art svg {{ width:26px; height:21px; }}
  .ans-head {{ font-size:1.02rem; line-height:1.55; margin:0 0 .9rem; color:{INK}; }}
  .ans-sec {{ font-size:.95rem; font-weight:700; color:{INK}; margin:1.1rem 0 .3rem; padding-top:.6rem; border-top:1px solid #e6e8ea; }}
  .ans-sec-text {{ font-size:.95rem; color:{INK}; margin:0 0 .6rem; }}
  [data-testid="stChatMessage"] [data-testid="stDataFrame"] {{ margin:.3rem 0 .9rem; }}
  [data-testid="stChatMessage"] .warn {{ margin:.3rem 0; }}
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{ justify-content:flex-end; padding-right:0; width:100%; }}
  section.stMain {{ background-image:url("{PATTERN_URI}"); background-repeat:repeat; background-size:480px 480px; }}
  .st-key-logo_btn [data-testid="stButton"] button {{ background:url("{LOGO_URI}") no-repeat center / 160px auto; height:54px; width:100%; border:none; box-shadow:none; margin-top:0; }}
  .st-key-logo_btn [data-testid="stButton"] button:hover {{ background-color:transparent; opacity:.9; }}
  .st-key-logo_btn [data-testid="stButton"] button p {{ color:transparent; font-size:0; }}
  .st-key-tools [data-testid="stButton"] button, .st-key-rail [data-testid="stButton"] button {{ justify-content:flex-start; }}
  .st-key-tools [data-testid="stButton"] button > div {{ justify-content:flex-start; width:100%; }}
  .st-key-tools [data-testid="stButton"] button p {{ text-align:left; }}
  .st-key-rail {{ display:none; }}
  section[data-testid="stSidebar"][aria-expanded="false"] {{ display:block !important; width:72px !important; min-width:72px !important; max-width:72px !important; transform:none !important; }}
  section[data-testid="stSidebar"][aria-expanded="false"] .st-key-sbfull {{ display:none; }}
  section[data-testid="stSidebar"][aria-expanded="false"] .st-key-rail {{ display:block; padding-top:2.6rem; }}
  section[data-testid="stSidebar"][aria-expanded="false"] .block-container {{ padding:1rem .4rem; }}
  .st-key-rail [data-testid="stButton"] button {{ width:44px; height:40px; padding:0; justify-content:center; margin:0 auto; }}
  .st-key-rail [data-testid="stButton"] button [data-testid="stIconMaterial"] {{ color:{SLATE}; font-size:1.35rem; }}
  .st-key-rail [data-testid="stButton"] button p {{ display:none; }}
  .home-sub {{ text-align:center; color:#5b6770; font-size:1.05rem; margin:-.2rem auto 1.4rem; max-width:720px; }}
  .st-key-home_cards [data-testid="stButton"] button {{ min-height:92px; white-space:normal; border-radius:16px; border:1px solid #d7d9db; background:#fff; justify-content:flex-start; text-align:left; padding:.8rem 1rem; }}
  .st-key-home_cards [data-testid="stButton"] button:hover {{ border-color:{RED}; }}
  .st-key-home_cards [data-testid="stButton"] button p {{ white-space:normal !important; font-size:.95rem; line-height:1.35; text-align:left; }}
  .st-key-home_cards [data-testid="stButton"] button [data-testid="stIconMaterial"] {{ color:{RED}; font-size:1.6rem; margin-right:.4rem; }}
  .hero-sub {{ text-align:center; color:#5b6770; margin:-.2rem 0 1.6rem; font-size:1rem; }}
  .st-key-starters [data-testid="stButton"] button {{ min-height:66px; white-space:normal; text-align:left; border-radius:14px; border:1px solid #d7d9db; background:#fff; justify-content:flex-start; padding:.6rem .9rem; }}
  .st-key-starters [data-testid="stButton"] button:hover {{ border-color:{RED}; background:#fff; }}
  .st-key-starters [data-testid="stButton"] button p, .st-key-starters [data-testid="stButton"] button div {{ font-size:.92rem; line-height:1.3; white-space:normal !important; overflow:visible !important; text-overflow:clip; text-align:left; }}
  .st-key-starters [data-testid="stButton"] button [data-testid="stIconMaterial"] {{ color:{RED}; font-size:1.3rem; margin-right:.2rem; }}
  section[data-testid="stSidebar"] .st-key-tools [data-testid="stButton"] button [data-testid="stIconMaterial"] {{ color:{RED}; }}
  .lpc-status {{ font-size:.74rem; color:#6b767d; line-height:1.5; margin-top:10px; }}
  .lpc-status .ok {{ color:#2fd27a; }}
  section[data-testid="stSidebar"] .block-container {{ padding-top: .2rem; }}
  [data-testid="stSidebarHeader"] {{ height:2.3rem; min-height:2.3rem; padding:.35rem .5rem 0; }}
  [data-testid="stSidebarUserContent"] {{ padding-top:0 !important; }}
  div[data-stale="true"], .stale-element {{ opacity:1 !important; }}
  section[data-testid="stSidebar"] [data-testid="stRadio"] label p {{ font-size: 0.95rem; }}
  section[data-testid="stSidebar"] [data-testid="stRadio"] > div {{ gap: 0.15rem; }}
  .lpc-logo {{ width:170px; margin:0 auto 6px; }}
  .lpc-logo svg {{ width:100%; height:auto; display:block; }}
  .lpc-brand {{ display:flex; align-items:center; justify-content:center; text-align:center; gap:10px; margin-bottom:10px; }}
  .lpc-brand .t1 {{ font-size:1.05rem; font-weight:700; letter-spacing:.02em; color:{INK}; line-height:1.1; }}
  .lpc-brand .t2 {{ font-size:.74rem; color:#6b767d; letter-spacing:.12em; text-transform:uppercase; }}
  .lpc-card {{ background:{SLATE_DARK}; border:1px solid #4a575f; border-radius:8px; padding:10px 12px; margin:8px 0 12px; font-size:.82rem; color:#dfe4e7; }}
  .lpc-card b {{ color:#fff; }}
  .lpc-card .ok {{ color:#2fd27a; font-weight:600; }}
  .lpc-card .off {{ color:#f5c842; font-weight:600; }}
  .lpc-section {{ font-size:.72rem; letter-spacing:.14em; text-transform:uppercase; color:#8a949a; margin:14px 0 4px; }}
  .lpc-list {{ font-size:.84rem; color:{INK}; line-height:1.55; margin:0; padding-left:0; list-style:none; }}
  .lpc-list li::before {{ content:""; display:inline-block; width:6px; height:6px; border-radius:50%; background:{RED}; margin-right:8px; vertical-align:middle; }}
  .badge {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:.78rem; font-weight:600; color:#fff; }}
  .kpi {{ background:{GREY_LIGHT}; border-left:4px solid {RED}; border-radius:6px; padding:10px 12px; margin-bottom:16px; }}
  .kpi .v {{ font-size:1.6rem; font-weight:700; color:{INK}; line-height:1.1; white-space:nowrap; }}
  .kpi .v.small {{ font-size:1.05rem; padding:.35rem 0; }}
  .kpi .l {{ font-size:.64rem; color:#5b6770; text-transform:uppercase; letter-spacing:.02em; line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .st-key-lpc_topbar {{ position:fixed; top:.55rem; right:1rem; z-index:999991; width:auto; }}
  .st-key-lpc_topbar button[data-testid="stPopoverButton"] {{ border-radius:999px; min-height:2.2rem; height:2.2rem; width:2.2rem; padding:0; justify-content:center; color:{SLATE}; background:#fff; border:1px solid #d7d9db; }}
  .st-key-lpc_topbar button[data-testid="stPopoverButton"] p {{ display:none; }}
  .st-key-lpc_topbar button[data-testid="stPopoverButton"] [aria-hidden="true"] {{ display:none; }}
  .st-key-lpc_topbar button[data-testid="stPopoverButton"] [data-testid="stIconMaterial"] {{ font-size:1.35rem; line-height:1; }}
  .st-key-lpc_topbar button[data-testid="stPopoverButton"] > div {{ justify-content:center; width:100%; }}
  .st-key-lpc_topbar button[data-testid="stPopoverButton"]:hover {{ border-color:{RED}; color:{RED}; }}
  .lpc-menu-h {{ font-size:.72rem; letter-spacing:.14em; text-transform:uppercase; color:#5b6770; margin:2px 0 6px; }}
  .lpc-menu-list {{ list-style:none; padding:0; margin:0; font-size:.9rem; line-height:1.8; }}
  .lpc-menu-list a {{ color:{SLATE}; text-decoration:none; }}
  .lpc-menu-list a:hover {{ color:{RED}; }}
  .lpc-about {{ font-size:.82rem; color:{INK}; line-height:1.5; max-width:380px; }}
  .lpc-about .muted {{ color:#6b767d; font-size:.76rem; }}
  [class*="st-key-chat_sugg_"] [data-testid="stButtonGroup"] {{ flex-wrap:wrap; row-gap:6px; }}
  [class*="st-key-chat_sugg_"] [data-testid="stButtonGroup"] button {{ white-space:normal; text-align:left; line-height:1.25; }}
  @media (max-width: 1100px) {{
    .st-key-home_kpis [data-testid="stColumn"] {{ flex:1 1 30% !important; min-width:30% !important; }}
  }}
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


def status_map(df: pd.DataFrame, key: str, height: int = 540, size_col: str | None = None, interactive: bool = True) -> str | None:
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
    if not interactive:
        st.plotly_chart(fig, use_container_width=True, key=key, theme=None, config={"displayModeBar": False, "scrollZoom": False, "staticPlot": False})
        return None
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

# ---------------------------------------------------------------------------------- conversations (threads)
def threads() -> list[dict]:
    return st.session_state.setdefault("threads", [])


def current_thread() -> dict:
    """The active thread; a fresh one is created when none is active."""
    ts = threads()
    th = next((x for x in ts if x["id"] == st.session_state.get("thread_id")), None)
    if th is None:
        th = {"id": st.session_state.get("thread_seq", 0) + 1, "title": None, "messages": [], "ctx": None}
        st.session_state["thread_seq"] = th["id"]
        ts.insert(0, th)
        st.session_state["thread_id"] = th["id"]
    return th


def go_chat(thread_id: int | None = None):
    """Back to the assistant, optionally on a given thread (applied at the start of the next run)."""
    if thread_id is not None:
        st.session_state["thread_id"] = thread_id
    st.session_state["goto_chat"] = True
    st.rerun()


def queue_question(q: str):
    """Append the user's message to the active thread and let the next run answer it (so the bubble shows immediately)."""
    th = current_thread()
    th["messages"].append({"role": "user", "content": q})
    th["title"] = th["title"] or (q[:60] + ("…" if len(q) > 60 else ""))
    st.session_state["chat_pending"] = q


st.session_state.setdefault("page", "page.home")
if st.session_state.pop("goto_chat", False):
    st.session_state["page"] = "page.chat"


def go_page(p: str):
    st.session_state["page"] = p
    st.rerun()


with st.sidebar:
    with st.container(key="rail"):  # icon rail shown only when the sidebar is collapsed (CSS)
        if st.button("+", key="rail_new", icon=":material/add:"):
            if current_thread()["messages"]:
                st.session_state["thread_id"] = None
            go_chat()
        for item, icon in RAIL_ITEMS:
            if st.button(" ", key=f"rail_{item}", icon=icon, type="tertiary"):
                go_page("page.chat" if item == "chat" else item)
    with st.container(key="sbfull"):
        with st.container(key="logo_btn"):
            if st.button("Lallemand Plant Care", key="logo_home", type="tertiary", use_container_width=True):
                go_page("page.home")
        st.markdown(f'<div class="lpc-brand"><div><div class="t1">Regulatory Watch</div><div class="t2">{t("app.subtitle")}</div></div></div>', unsafe_allow_html=True)
        if st.button(t("chat.new"), key="new_thread", use_container_width=True, type="primary", icon=":material/add:"):
            if current_thread()["messages"]:
                st.session_state["thread_id"] = None  # a fresh thread; empty ones are reused
            go_chat()
        th_cur = current_thread()
        history = [x for x in threads() if x["messages"]]
        if history:
            st.markdown(f'<div class="lpc-section">{t("sb.threads")}</div>', unsafe_allow_html=True)
            for x in history[:15]:
                active = x["id"] == th_cur["id"] and st.session_state["page"] == "page.chat"
                if st.button(x["title"] or "…", key=f"thread_{x['id']}", use_container_width=True, type="secondary" if active else "tertiary"):
                    go_chat(x["id"])
        st.markdown(f'<div class="lpc-section">{t("sb.tools")}</div>', unsafe_allow_html=True)
        with st.container(key="tools"):
            for tool in TOOLS:
                if st.button(t(tool), key=f"tool_{tool}", use_container_width=True, icon=TOOL_ICONS[tool], type="secondary" if st.session_state["page"] == tool else "tertiary"):
                    go_page(tool)
page = st.session_state["page"]


# ---------------------------------------------------------------------------------- top-right menu (language, links)
def _set_lang():
    v = st.session_state.get("lang_ctl")
    if v and v != st.session_state["lang"]:
        st.session_state["lang"] = v


st.session_state.setdefault("lang_ctl", st.session_state["lang"])
with st.container(key="lpc_topbar"):
    with st.popover("menu", icon=":material/more_vert:"):
        st.markdown(f'<div class="lpc-menu-h">{t("sb.lang")}</div>', unsafe_allow_html=True)
        st.segmented_control(t("sb.lang"), list(LANGS), format_func=lambda k: LANGS[k], key="lang_ctl", on_change=_set_lang, label_visibility="collapsed")
        st.markdown(f'<div class="lpc-menu-h" style="margin-top:12px">{t("sb.links")}</div><ul class="lpc-menu-list"><li><a href="{API_PUBLIC}/guide" target="_blank">{t("sb.guide")}</a></li>'
                    f'<li><a href="{API_PUBLIC}/docs" target="_blank">{t("sb.swagger")}</a></li><li><a href="/pitch/" target="_blank">{t("sb.pitch")}</a></li></ul>', unsafe_allow_html=True)
        st.markdown(f'<div class="lpc-menu-h" style="margin-top:12px">{t("sb.about")}</div><div class="lpc-about"><b>{t("sb.pilots")}</b> : LALSTOP CONTANS WG, LALSTOP G46 WG, LALGUARD M52 OD<br>'
                    f'<b>{t("sb.sources")}</b> : Santé Canada PPID, US EPA PPLS, ANSES E-Phy, MAPA AGROFIT<br><b>{t("sb.limits")}</b> : {t("sb.lim1")} {t("sb.lim2")}<br>'
                    f'<span class="muted">{t("disclaimer")}</span></div>', unsafe_allow_html=True)

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


def overview_rows(ov: dict) -> pd.DataFrame:
    """Map rows (one per country) from GET /overview."""
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
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------- assistant (chat) helpers
ANSWER_COLS = [("country", "country"), ("product", "product"), ("registrationNumber", "number"), ("status", "status"), ("statusOriginal", "status_orig"),
               ("expiry", "expires"), ("relationship", "ask.item.relationship"), ("detail", "ask.item.detail"), ("sourceId", "source"), ("collectedAt", "collected")]
MAP_INTENTS = {"registration_lookup", "ingredient_search", "country_portfolio"}
FOLLOW_UPS = {"registration_lookup": ["chat.fu_uses", "chat.fu_sisters", "chat.fu_sources"], "use_comparison": ["chat.fu_sisters", "chat.fu_quality", "chat.fu_countries"],
              "sister_product": ["chat.fu_countries", "chat.fu_uses"], "source": ["chat.fu_uses", "chat.fu_quality"], "data_quality": ["chat.fu_countries", "chat.fu_uses"],
              "ingredient_search": ["chat.fu_sources"]}


def show_table(data, **kw):
    """st.dataframe with a visible sort hint on every header (click a header to sort, the menu offers ascending / descending)."""
    df = data.data if hasattr(data, "data") else data
    cfg = dict(kw.pop("column_config", None) or {})
    for c in df.columns:
        if c in cfg and isinstance(cfg[c], dict):
            if not str(cfg[c].get("label") or "").endswith("⇅"):
                cfg[c]["label"] = f"{cfg[c].get('label') or c} ⇅"
        elif c not in cfg:
            cfg[c] = st.column_config.Column(label=f"{c} ⇅")
    st.dataframe(data, column_config=cfg, **kw)


def answer_status(v: str | None) -> str | None:
    """Readable, translated status for an answer row (registration status or coverage verdict)."""
    if v in STATUS_COLOR:
        return st_label(v)
    return {"not_found_in_source": t("m.notfound"), "source_not_collected": t("m.nosource")}.get(v or "", v)


def answer_map(ans: dict, key: str):
    """Small world map built from the facts of a country-type answer (found / not found / no source / related only)."""
    if ans.get("intent") not in MAP_INTENTS:
        return
    agg: dict[str, dict] = {}
    for f in ans.get("facts") or []:
        cc = f.get("country")
        if cc not in ISO3:
            continue
        d = agg.setdefault(cc, {"active": 0, "withdrawn": 0, "expired": 0, "pending": 0, "related": 0, "coverage": "found"})
        if f["type"] == "registration" and f.get("statusNormalized") in d:
            d[f["statusNormalized"]] += 1
        elif f["type"] in ("coverage", "portfolio"):
            d["coverage"] = f.get("coverage") or "found"
        elif f["type"] == "related_registration":
            d["related"] += 1
    if not agg:
        return
    rows = [{"iso3": ISO3[cc], t("country"): cname(cc), "Statut": map_status(d["active"], d["withdrawn"], d["expired"], d["pending"], d["coverage"], d["related"]),
             t("registrations"): d["active"] + d["withdrawn"] + d["expired"] + d["pending"]} for cc, d in agg.items()]
    status_map(pd.DataFrame(rows), key, height=270, size_col=t("registrations"), interactive=False)


def _typed(text: str, delay: float = 0.018):
    """Word-by-word generator for st.write_stream (the 'typing' feel of a new answer)."""
    for w in text.split(" "):
        yield w + " "
        time.sleep(delay)


def style_status(df: pd.DataFrame):
    """Colour the status column(s) of a table (active green, withdrawn red, expired orange, pending amber)."""
    labels = {st_label(k): v for k, v in STATUS_TEXT.items()}
    labels.update({t("m.notfound"): "#5b6770", t("m.nosource"): "#5b6770"})
    cols = [c for c in df.columns if c in (t("status"), t("reg.status_col"), t("reg.off_status"))]
    if not cols:
        return df
    fn = lambda v: f"color:{labels[v]}; font-weight:600" if v in labels else ""  # noqa: E731
    sty = df.style
    return sty.map(fn, subset=cols) if hasattr(sty, "map") else sty.applymap(fn, subset=cols)


def answer_items_df(items: list[dict]) -> pd.DataFrame:
    rows = [{t(lbl): (answer_status(it.get(k)) if k == "status" else it.get(k)) for k, lbl in ANSWER_COLS + [("url", "ask.url")] if any(x.get(k) for x in items)} for it in items]
    return pd.DataFrame(rows)


def render_items(items: list[dict]):
    if not items:
        return
    df = answer_items_df(items)
    cfg = {t("ask.url"): st.column_config.LinkColumn(t("ask.url"), display_text=t("ask.open"))} if t("ask.url") in df.columns else None
    show_table(style_status(df), hide_index=True, use_container_width=True, column_config=cfg)


def render_answer(ans: dict, key: str, stream: bool = False):
    """One assistant turn: the answer sentence (streamed when new), a map when the question is about countries, only the useful
    rows, the sections of a multi-part question, caveats; evidence, meta and raw facts folded away under 'Sources'."""
    sa = ans.get("structured") or {}
    head = sa.get("headline") or t("ask.answer")
    if stream:
        st.write_stream(_typed(head))
    else:
        st.markdown(f'<p class="ans-head">{head}</p>', unsafe_allow_html=True)
    answer_map(ans, f"{key}_map")
    render_items(sa.get("items") or [])
    for i, sec in enumerate(sa.get("sections") or []):
        st.markdown(f'<div class="ans-sec">{sec.get("title") or ""}</div>' + (f'<p class="ans-sec-text">{sec["text"]}</p>' if sec.get("text") else ""), unsafe_allow_html=True)
        render_items(sec.get("items") or [])
    for cv in sa.get("caveats") or []:
        st.markdown(f'<div class="warn">• {cv}</div>', unsafe_allow_html=True)
    other = [w for w in (ans.get("warningsLocalized") or ans["warnings"]) if w not in (sa.get("caveats") or [])]
    with st.expander(t("chat.sources", n=len(ans["evidence"]))):
        st.caption(t("ask.meta", intent=ans["intent"], tools=", ".join(ans["toolsUsed"]) or "—", model=ans["model"] or t("ask.det")))
        for w in other:
            st.markdown(f'<div class="warn">• {w}</div>', unsafe_allow_html=True)
        if ans["evidence"]:
            ev = pd.DataFrame([{t("source"): e["sourceId"], "URL": e["sourceUrl"], t("collected"): fmt_dt(e["collectedAt"]), t("validation"): e["validationStatus"],
                                t("ask.excerpt"): (e.get("excerpt") or "")[:160]} for e in ans["evidence"]])
            show_table(ev, hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL", display_text=t("ask.open"))})
        else:
            st.info(t("ask.no_evidence"))
        st.json(ans["facts"], expanded=False)

def chat_suggestions(th: dict) -> list[str]:
    """Follow-up questions about the last answer, never one already asked in this thread."""
    lang = st.session_state["lang"]
    last = next((m for m in reversed(th["messages"]) if m["role"] == "assistant" and m.get("ans")), None)
    out: list[str] = []
    if last and (last["ans"].get("context") or {}).get("productIds"):
        out += [t(k) for k in FOLLOW_UPS.get(last["ans"].get("intent"), [])]
    asked = {m["content"] for m in th["messages"] if m["role"] == "user"}
    out = [x for x in out if x not in asked]
    if len(out) < 2:
        out += [x for x in EXAMPLES.get(lang, EXAMPLES["fr"])[:4] if x not in asked and x not in out]
    return out[:3]


def chat_page():
    """ChatGPT-like assistant: centred thread, pinned input, starter cards on an empty thread, streamed answers."""
    lang = st.session_state["lang"]
    th = current_thread()
    msgs = th["messages"]
    st.markdown("<style>section.stMain .block-container, [data-testid=\"stBottomBlockContainer\"] { max-width: 900px; } "
                "section.stMain div[data-stale=\"true\"] { display:none !important; }</style>", unsafe_allow_html=True)  # a sent question replaces the previous view at once
    if not msgs:
        st.markdown("<style>section.stMain h1 { text-align:center; margin-top:8vh; font-size:2rem; }</style>", unsafe_allow_html=True)
        st.title(t("chat.hero"))
        st.markdown(f'<p class="hero-sub">{t("chat.hero_sub")}</p>', unsafe_allow_html=True)
        ov = api_get("/overview", {"scope": "pilots", "months": 12})
        if "__404__" not in ov:
            clicked = status_map(overview_rows(ov), f"chat_map_{th['id']}", 380, size_col=t("registrations"))
            st.markdown(f'<p class="chat-map-cap">{t("chat.map_caption", n=ov["totals"]["registrations"], c=ov["totals"]["countriesFound"])}</p>', unsafe_allow_html=True)
            if clicked and st.session_state.get("chat_map_last") != (th["id"], clicked):
                st.session_state["chat_map_last"] = (th["id"], clicked)
                cc = ISO3_TO_CC[clicked]
                queue_question(t("chat.sugg_country", cin=COUNTRY_IN.get(lang, COUNTRY_IN["en"]).get(cc, cc)))
                st.rerun()
        with st.container(key="starters"):
            cols = st.columns(2)
            for i, ex in enumerate(EXAMPLES.get(lang, EXAMPLES["fr"])[:4]):
                if cols[i % 2].button(ex, key=f"starter_{i}_{lang}", use_container_width=True, icon=STARTER_ICONS[i % len(STARTER_ICONS)]):
                    queue_question(ex)
                    st.rerun()
    else:
        for i, m in enumerate(msgs):
            if m["role"] == "user":
                with st.chat_message("user"):
                    st.markdown(m["content"])
            else:
                with st.chat_message("assistant", avatar=BOT_AVATAR):
                    if m.get("error"):
                        st.error(m["error"])
                    else:
                        render_answer(m["ans"], key=f"ans_{th['id']}_{i}")
                    if i == len(msgs) - 1 and not st.session_state.get("chat_pending"):
                        sugg = chat_suggestions(th)
                        pick = st.pills(t("chat.suggest"), sugg, selection_mode="single", key=f"chat_sugg_{th['id']}_{i}_{lang}", label_visibility="collapsed",
                                        format_func=lambda q: f":material/arrow_forward: {q}") if sugg else None
                        if pick:
                            queue_question(pick)
                            st.rerun()
        pending = st.session_state.get("chat_pending")
        if pending:
            with st.chat_message("assistant", avatar=BOT_AVATAR):
                ans = None
                with st.spinner(t("ask.spinner")):
                    hist = [{"role": m["role"], "content": m["content"] if m["role"] == "user" else (((m.get("ans") or {}).get("structured") or {}).get("headline") or "")}
                            for m in msgs[:-1]][-6:]
                    try:
                        ans = api_post("/ask", {"question": pending, "language": lang, "context": th.get("ctx"), "history": hist})
                    except httpx.HTTPError as e:  # noqa: BLE001 - the API refused or failed: say so, keep the thread
                        msgs.append({"role": "assistant", "error": t("ask.error", err=e)})
                if ans:
                    th["ctx"] = ans.get("context")
                    render_answer(ans, key=f"ans_{th['id']}_{len(msgs)}", stream=True)
                    msgs.append({"role": "assistant", "ans": ans})
            st.session_state["chat_pending"] = None
            st.rerun()
    typed = st.chat_input(t("chat.placeholder"), key="chat_in")
    if typed and typed.strip():
        queue_question(typed.strip())
        st.rerun()


# ---------------------------------------------------------------------------------- pages
if page not in ("page.chat", "page.home"):
    if st.button(t("chat.back"), key="back_chat", type="tertiary", icon=":material/arrow_back:"):
        go_chat()


def home_page():
    """Landing page: what the tool is, three entries (assistant, map, data & monitoring), key figures, the pilots map."""
    st.markdown("<style>section.stMain .block-container { max-width: 1000px; } section.stMain h1 { text-align:center; margin-top:4vh; font-size:2.1rem; }</style>", unsafe_allow_html=True)
    st.title(t("home.title"))
    st.markdown(f'<p class="home-sub">{t("home.sub")}</p>', unsafe_allow_html=True)
    with st.container(key="home_cards"):
        c1, c2, c3 = st.columns(3)
        if c1.button(t("home.cta_chat"), key="home_chat", icon=":material/forum:", use_container_width=True):
            go_page("page.chat")
        if c2.button(t("home.cta_map"), key="home_map", icon=":material/public:", use_container_width=True):
            go_page("page.overview")
        if c3.button(t("home.cta_data"), key="home_data", icon=":material/monitoring:", use_container_width=True):
            go_page("page.sources")
    ov = api_get("/overview", {"scope": "pilots", "months": 12})
    src = api_get("/sources")["items"]
    collected = [x for x in src if x.get("registrations")]
    sch = health.get("updateSchedule") or {}
    with st.container(key="home_kpis"):
        k = st.columns(5)
    for col, (v, lbl) in zip(k, [(len(collected), t("ov.k.sources")), (health.get("registrations"), t("registrations")), (ov["totals"]["countriesFound"] if "__404__" not in ov else "—", t("ov.k.countries")),
                                  (fmt_dt(health.get("lastSnapshotAt"))[:10], t("home.k.updated")), (fmt_dt(sch.get("nextRunAt"))[:16], t("home.k.next"))]):
        col.markdown(f'<div class="kpi"><div class="v{" small" if len(str(v)) > 6 else ""}">{v}</div><div class="l" title="{lbl}">{lbl}</div></div>', unsafe_allow_html=True)
    if "__404__" not in ov:
        th = current_thread()
        clicked = status_map(overview_rows(ov), f"home_map_{th['id']}", 420, size_col=t("registrations"))
        st.markdown(f'<p class="chat-map-cap">{t("chat.map_caption", n=ov["totals"]["registrations"], c=ov["totals"]["countriesFound"])}</p>', unsafe_allow_html=True)
        if clicked and st.session_state.get("home_map_last") != (th["id"], clicked):
            st.session_state["home_map_last"] = (th["id"], clicked)
            cc = ISO3_TO_CC[clicked]
            queue_question(t("chat.sugg_country", cin=COUNTRY_IN.get(st.session_state["lang"], COUNTRY_IN["en"]).get(cc, cc)))
            go_chat()
    st.markdown(f'<div class="lpc-section" style="color:#6b767d">{t("sb.sources")}</div>', unsafe_allow_html=True)
    show_table(pd.DataFrame([{t("source"): x["sourceId"], t("src.name"): x["officialName"], t("src.region"): x["countryOrRegion"], t("registrations"): x["registrations"],
                                t("src.last"): fmt_dt(x["lastCollectedAt"])} for x in collected]), hide_index=True, use_container_width=True)
if page == "page.home":
    home_page()

elif page == "page.chat":
    chat_page()

elif page == "page.overview":
    st.title(t("ov.title"))
    c1, c2, c3 = st.columns([2.2, 2, 1])
    scope_keys = ["ov.scope.pilots", "ov.scope.lallemand", "ov.scope.all", "ov.scope.product"]
    with c1:
        scope_key = st.radio(t("ov.scope"), scope_keys, format_func=t, horizontal=True, key=lang_key("ov_scope"))
        st.session_state["ov_scope"] = scope_key
    scope = {"ov.scope.pilots": "pilots", "ov.scope.lallemand": "lallemand", "ov.scope.all": "all", "ov.scope.product": "product"}[scope_key]
    params = {"scope": scope}
    with c2:
        if scope == "product":
            params["productId"] = product_picker("ov")
    with c3:
        params["months"] = st.number_input(t("ov.months"), 1, 60, 12, key="ov_months")
    ov = api_get("/overview", params)
    if "__404__" in ov:
        st.error(ov["__404__"]["message"])
        st.stop()
    tt = ov["totals"]
    with st.container(key="home_kpis"):
        k = st.columns(6)
    for col, (v, lbl) in zip(k, [(tt["sourcesConnected"], t("ov.k.sources")), (tt["countriesFound"], t("ov.k.countries")), (tt["products"], t("products")),
                                  (tt["registrations"], t("registrations")), (tt["active"], t("ov.k.active")), (tt["expiringSoon"], t("ov.k.expiring", m=ov["months"]))]):
        col.markdown(f'<div class="kpi"><div class="v">{v}</div><div class="l" title="{lbl}">{lbl}</div></div>', unsafe_allow_html=True)
    df = overview_rows(ov)
    clicked = status_map(df, "ov_map", 540, size_col=t("registrations"))
    st.caption(t("ov.caption"))
    sel_iso = country_picker(df, clicked, "ov", t("registrations"))
    cc = ISO3_TO_CC[sel_iso]
    c = next(x for x in ov["countries"] if x["countryCode"] == cc)
    h1, h2 = st.columns([3, 1.4])
    h1.markdown(f"#### {cname(cc)} ({cc}) — {c['sourceId'] or t('none_country')}" + (f" · {t('collected').lower()} {fmt_dt(c['collectedAt'])}" if c["collectedAt"] else ""))
    ask_q = t("chat.sugg_country", cin=COUNTRY_IN.get(st.session_state["lang"], COUNTRY_IN["en"]).get(cc, cc))
    if h2.button(t("chat.ask_about"), key="ask_country", use_container_width=True, icon=":material/forum:", help=ask_q):
        if current_thread()["messages"]:
            st.session_state["thread_id"] = None
        queue_question(ask_q)
        go_chat()
    if c["registrations"]:
        show_table(country_detail_table(c["registrations"]), hide_index=True, use_container_width=True, column_config=LINK)
    elif c["coverage"] == "not_found_in_source":
        st.info(t("ov.notfound", src=c["sourceId"], at=fmt_dt(c["collectedAt"]), n=c.get("totalInStore", 0)))
    else:
        st.warning(t("ov.nosource"))
    with st.expander(t("ov.table")):
        view = df.drop(columns=["iso3"]).copy()
        view["Statut"] = view["Statut"].map(t)
        view = view.rename(columns={"Statut": t("status")})
        show_table(view, hide_index=True, use_container_width=True)

elif page == "page.compare":
    st.title(t("cmp.title"))
    col1, col2 = st.columns([2, 2])
    with col1:
        pid = product_picker("cmp")
    with col2:
        st.session_state.setdefault("cmp_countries", ["CA", "US", "FR", "BR"])
        countries = st.multiselect(t("countries"), ALL_COUNTRIES, format_func=lambda c: f"{cname(c)} ({c})", key=lang_key("cmp_countries"))
        st.session_state["cmp_countries"] = countries
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
        if clicked and st.session_state.get("cmp_last_click") != clicked:  # a new click: highlight the card and filter the uses below
            st.session_state["cmp_last_click"] = clicked
            st.session_state["cmp_focus"] = ISO3_TO_CC.get(clicked)
            st.session_state[lang_key("cmp_uses_cc")] = [ISO3_TO_CC.get(clicked)]
        focus = st.session_state.get("cmp_focus") if st.session_state.get("cmp_focus") in countries else None
        cols = st.columns(len(countries))
        for c, cc in zip(cols, countries):
            cov = next(x for x in data["coverage"] if x["countryCode"] == cc)
            border = f"border:2px solid {RED};" if focus == cc else ""
            with c:
                if cov["coverage"] == "found":
                    inner = ""
                    for r in regs_by_cc.get(cc, []):
                        inner += (f'{badge(r["statusNormalized"])} <b>{t("number")} {r["registrationNumber"]}</b><div class="m">« {r["statusOriginal"]} » · {r["usesCount"]} {t("use" if r["usesCount"] == 1 else "uses").lower()} · '
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
            show_table(pd.DataFrame(rel_rows), hide_index=True, use_container_width=True, column_config=LINK)
        st.markdown(f"### {t('cmp.uses_h')}")
        frames = [uses_table(r) for r in data["registrations"] if r["uses"]]
        if frames:
            df = pd.concat(frames, ignore_index=True)
            cc_opts = sorted(df[t("country")].unique())
            st.session_state.setdefault("cmp_uses_cc", cc_opts)
            cc_key = lang_key("cmp_uses_cc")
            if not st.session_state.get(cc_key) or any(c not in cc_opts for c in st.session_state[cc_key]):
                st.session_state[cc_key] = cc_opts  # options changed (other product) or the clicked country has no uses: show everything
            f0, f1, f2, f3 = st.columns([1.2, 1.6, 1.6, 1.6])
            with f0:
                cc_f = st.multiselect(t("country"), cc_opts, format_func=lambda c: f"{cname(c)} ({c})", key=cc_key)
                st.session_state["cmp_uses_cc"] = cc_f
            with f1:
                crop_f = st.text_input(t("cmp.filter_crop"), "", key="cmp_crop_f")
            with f2:
                pairing_f = st.multiselect(t("cmp.pairing"), sorted(df[t("cmp.pairing")].unique()), default=sorted(df[t("cmp.pairing")].unique()), key=f"cmp_pair_{pid}")
            with f3:
                extr_f = st.multiselect(t("cmp.extraction"), sorted(df[t("cmp.extraction")].unique()), default=sorted(df[t("cmp.extraction")].unique()), key=f"cmp_extr_{pid}")
            view = df[df[t("country")].isin(cc_f or cc_opts) & df[t("cmp.pairing")].isin(pairing_f) & df[t("cmp.extraction")].isin(extr_f)]
            if crop_f:
                m = view[t("u.crop_o")].fillna("").str.contains(crop_f, case=False) | view[t("u.crop_n")].fillna("").str.contains(crop_f, case=False)
                view = view[m]
            st.caption(t("cmp.rows_cap", n=len(view)))
            show_table(view, use_container_width=True, hide_index=True, column_config=LINK)
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

elif page == "page.map":
    st.title(t("map.title"))
    mode = st.radio(t("map.mode"), ["map.mode.product", "map.mode.species"], format_func=t, horizontal=True, key=lang_key("map_mode"))
    st.session_state["map_mode"] = mode
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
        species = st.text_input(t("map.species"), "Clonostachys rosea", key="map_species")
        crop = st.text_input(t("map.crop"), "", key="map_crop")
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
        show_table(country_detail_table(detail[sel]), hide_index=True, use_container_width=True, column_config=LINK)
    else:
        st.info(t(df.set_index("iso3").loc[sel, "Statut"]).capitalize() + " — " + t("map.nothing"))
    warnings_box(warnings)

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
        show_table(df.drop(columns=["id"]), hide_index=True, use_container_width=True, column_config=LINK)
        st.markdown(f"### {t('sis.review_h')}")
        st.caption(t("sis.review_cap"))
        c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
        idx = df.set_index("id")
        with c1:
            target = st.selectbox(t("sis.target"), df["id"], format_func=lambda i: f"{idx.loc[i, t('sis.name')]} ({idx.loc[i, t('cmp.relation')]}, {idx.loc[i, t('cmp.review')]})")
        with c2:
            new = st.selectbox(t("sis.new"), ["validated", "rejected", "to_verify", "obsolete"], key="sis_new")
        with c3:
            reviewer = st.text_input(t("sis.reviewer"), "", key="sis_reviewer")
        with c4:
            note = st.text_input(t("sis.note"), "", key="sis_note")
        if st.button(t("sis.save"), disabled=not reviewer):
            res = api_post("/review", {"entityType": "alias", "entityId": target, "newStatus": new, "reviewer": reviewer, "note": note})
            st.success(t("sis.saved", id=res["entityId"], old=res["oldStatus"], new=res["newStatus"], who=res["reviewer"]))
            api_get.clear()
        log = api_get("/review/log", {"limit": 50})
        if log:
            st.markdown(f"#### {t('sis.log')}")
            show_table(pd.DataFrame(log), hide_index=True, use_container_width=True)

elif page == "page.watch":
    st.title(t("watch.title"))
    months = st.slider(t("watch.horizon"), 1, 60, 12, key="watch_months")
    exp = api_get("/expiring", {"months": months})
    st.markdown(f"### {t('watch.exp_h', m=months, n=len(exp['items']))}")
    if exp["items"]:
        show_table(pd.DataFrame([{t("product"): r["productName"], t("country"): r["countryCode"], t("number"): r["registrationNumber"], t("watch.expires_on"): r["expirationDate"],
                                    t("watch.days_left"): r["daysLeft"], t("status"): st_label(r["statusNormalized"]), t("source"): r["evidence"]["sourceId"],
                                    "URL": r["evidence"]["sourceUrl"], t("collected"): fmt_dt(r["evidence"]["collectedAt"])} for r in exp["items"]]),
                     hide_index=True, use_container_width=True, column_config=LINK)
    warnings_box(exp["warnings"])
    ch = api_get("/changes", {"limit": 300})
    st.markdown(f"### {t('watch.changes_h', n=len(ch))}")
    st.caption(t("watch.changes_cap"))
    if ch:
        show_table(pd.DataFrame([{t("watch.detected"): fmt_dt(c["detectedAt"]), t("watch.entity"): c["entityId"], t("watch.field"): c["field"], t("watch.before"): c["oldValue"],
                                    t("watch.after"): c["newValue"], "Snapshot": f"{c['fromSnapshotId'] or '—'} → {c['toSnapshotId']}"} for c in ch]),
                     hide_index=True, use_container_width=True)
    else:
        st.info(t("watch.no_changes"))

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
    show_table(pd.DataFrame(table), hide_index=True, use_container_width=True, column_config=LINK)
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

elif page == "page.sources":
    st.title(t("src.title"))
    src = api_get("/sources")
    df = pd.DataFrame([{t("source"): s["sourceId"], t("src.name"): s["officialName"], t("src.region"): s["countryOrRegion"], t("src.access"): s["accessMethod"],
                        t("src.format"): s["dataFormat"], t("src.licence"): s["licenseName"], t("src.limits"): s["accessAndReuseLimits"], t("registrations"): s["registrations"],
                        t("src.last"): fmt_dt(s["lastCollectedAt"]), "URL": s["baseUrl"]} for s in src["items"]])
    show_table(df, hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL", display_text=t("ask.open"))})
    st.markdown(f"### {t('src.quality_h')}")
    pid = product_picker("dq")
    dq = api_get(f"/products/{pid}/quality")
    if "__404__" not in dq:
        show_table(pd.DataFrame([{t("src.registration"): i["registrationId"], t("country"): i["countryCode"], t("status"): st_label(i["statusNormalized"]),
                                    t("validation"): i["validationStatus"], t("cmp.pairing"): ", ".join(i["pairing"]), t("src.missing"): "; ".join(i["missingOrUncertain"]) or "—"}
                                   for i in dq["registrations"]]), hide_index=True, use_container_width=True)
        warnings_box(dq["warnings"])
    st.markdown(f"### {t('src.export_h')}")
    st.download_button(t("src.export_all"), data=httpx.get(f"{API}/export.csv", timeout=180).content, file_name="lpc_regwatch_all.csv", mime="text/csv")
