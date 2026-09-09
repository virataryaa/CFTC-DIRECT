"""
cot_app.py — ICEBREAKER COT Dashboard
Run: streamlit run cot_app.py
"""

import datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy import stats as scipy_stats
import streamlit as st
from pathlib import Path

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="CFTC DIRECT — COT", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
  :root { color-scheme: light !important; }
  html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"], .main {
    background:#ffffff !important; color:#1a1a1a !important;
  }
  [data-testid="stSidebar"] { background:#f7f8fa !important; }
  [data-testid="stHeader"]  { background:transparent !important; }
  .block-container { padding-top:1.2rem !important; max-width:1600px; }
  div[data-testid="stExpander"] {
    border:1px solid #e0e4ed !important; border-radius:7px !important;
  }
  div[data-testid="stTabs"] button { font-size:0.81rem !important; font-weight:500; }
  div[data-testid="stTabs"] button:nth-child(8),
  div[data-testid="stTabs"] button:nth-child(9),
  div[data-testid="stTabs"] button:nth-child(10),
  div[data-testid="stTabs"] button:nth-child(11) {
    background-color:#f3f4f6 !important;
    border-radius:6px 6px 0 0 !important;
  }
  div[data-testid="stTabs"] button:nth-child(12) {
    background-color:#fce7f3 !important;
    border-radius:6px 6px 0 0 !important;
  }
  div[data-testid="stTabs"] button:nth-child(12) p {
    color:#be185d !important; font-weight:600 !important;
  }
  div[data-testid="stTabs"] button:nth-child(13) {
    background-color:#ede9fe !important;
    border-radius:6px 6px 0 0 !important;
  }
  div[data-testid="stTabs"] button:nth-child(13) p {
    color:#6d28d9 !important; font-weight:600 !important;
  }
  hr { border:none !important; border-top:1px solid #e8e8ed !important; margin:.5rem 0 !important; }
  [data-testid="stRadio"] label { font-size:.82rem !important; }
</style>""", unsafe_allow_html=True)

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_DIR      = Path(__file__).resolve().parent.parent / "Database"
CIT_FILE    = DB_DIR / "cot_cit.parquet"
FO_FILE     = DB_DIR / "cot_disagg_futopt.parquet"
FUT_FILE    = DB_DIR / "cot_disagg_fut.parquet"
ROLLEX_DIR  = DB_DIR / "Rollex"
ROLLEX_MAP  = {
    "KC": "rollex_KC.parquet",
    "CC": "rollex_CC.parquet",
    "CT": "rollex_CT.parquet",
    "SB": "rollex_SB.parquet",
    "RC": "rollex_RC.parquet",
    "LCC":"rollex_LCC.parquet",
    "LSU":"rollex_LSU.parquet",
}
VAR_LOT_USD = {"KC":375, "CC":10, "SB":1120, "CT":500, "RC":10, "LCC":10, "LSU":50,
               "GC":100, "SI":5000, "HG":25000}  # = CONTRACT_SIZE, /100 already folded in for CENTS_QUOTED ones
_CONF_Z     = 2.3263

# ── Commodity config ──────────────────────────────────────────────────────────
COMM_COLORS = {
    "KC":"#1a56db","CC":"#d97706","SB":"#059669",
    "CT":"#7c3aed","RC":"#dc2626","LCC":"#0891b2",
    "LSU":"#ea580c","GC":"#ca8a04","SI":"#64748b","HG":"#b45309",
    "KRC":"#6d28d9","CLC":"#0f766e","SLS":"#a16207",
}
COMM_NAMES = {
    "KC":"KC : Arabica Coffee","CC":"CC : NYC Cocoa",
    "SB":"SB : Sugar #11","CT":"CT : Cotton #2",
    "RC":"RC : Robusta Coffee","LCC":"LCC : London Cocoa",
    "LSU":"LSU : London White Sugar",
    "GC":"GC : Gold","SI":"SI : Silver","HG":"HG : Copper",
}
CONTRACT_SIZE = {"KC":37500,"CC":10,"SB":112000,"CT":50000,"RC":10,"LCC":10,"LSU":50,
                 "GC":100,"SI":5000,"HG":25000,"KRC":1,"CLC":1,"SLS":1}
CONTRACT_UNIT = {"KC":"lbs","CC":"MT","SB":"lbs","CT":"lbs","RC":"MT","LCC":"MT","LSU":"MT",
                 "GC":"oz","SI":"oz","HG":"lbs","KRC":"lots","CLC":"lots","SLS":"lots"}
CIT_COMMS     = {"KC","CC","SB","CT"}
# London softs come from ICE, which publishes no crop split and no
# concentration ratios for them.
ICE_COMMS     = {"RC","LCC","LSU"}  # metals have no CIT/Index Traders category (verified), same as RC/LCC/LSU
# Commodities whose LSEG price feed is cents/lb (needs /100 for $ nominal) —
# deliberately NOT the same set as CONTRACT_UNIT=="lbs": Copper (HG) is
# physically "lbs" too but LSEG quotes HGc2 directly in $/lb already
# (verified 2026-08-28: HGc2 ~6.59, not ~659 — cents/lb would put copper
# under 7 cents a pound, which has never happened). Do not add HG here.
CENTS_QUOTED  = {"KC","SB","CT"}
COMBINED_COMMS = {"KRC","CLC","SLS"}
COMBINED_MAP   = {"KRC":("KC","RC"), "CLC":("CC","LCC"), "SLS":("SB","LSU")}

C_LONG  = "#16a34a"
C_SHORT = "#dc2626"
C_NET   = "#1a56db"
C_PRICE = "#f59e0b"
C_OLD   = "#e67e22"
C_NEW   = "#2980b9"
GRAY    = "#6e6e73"

CROP_START_MONTH = 9
_MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
CROP_WEEK_TICKS  = {1:"Sep",5:"Oct",9:"Nov",14:"Dec",18:"Jan",22:"Feb",
                    26:"Mar",30:"Apr",35:"May",39:"Jun",43:"Jul",48:"Aug"}
MONTH_TICKS      = {1:"Jan",5:"Feb",9:"Mar",14:"Apr",18:"May",23:"Jun",
                    27:"Jul",32:"Aug",36:"Sep",40:"Oct",45:"Nov",49:"Dec"}

# ── Plot base ─────────────────────────────────────────────────────────────────
_BASE = dict(
    template="plotly_white",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif",
              color="#1a1a1a", size=11),
)

def _ax(x=False):
    b = dict(showgrid=True, gridcolor="rgba(0,0,0,0.05)", gridwidth=1,
             zeroline=True, zerolinecolor="rgba(0,0,0,0.12)", zerolinewidth=1,
             showline=True, linecolor="rgba(0,0,0,0.08)", linewidth=1,
             tickfont=dict(size=10, color="#666"))
    if x:
        b.update(showgrid=False, tickangle=-35, nticks=20, hoverformat="%d %b %Y")
    return b


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════
def _derive_nets(df, cols):
    pairs = [
        ("Spec Long",     "Spec Short",     "Spec Net"),
        ("Index Long",    "Index Short",    "Index Net"),
        ("Non Rep Long",  "Non Rep Short",  "Non Rep Net"),
        ("Comm Long",     "Comm Short",     "Comm Net"),
        ("MM Long",       "MM Short",       "MM Net"),
        ("Swap Long",     "Swap Short",     "Swap Net"),
        ("Other Long",    "Other Short",    "Other Net"),
        ("Producer Long", "Producer Short", "Comm Net"),
    ]
    for l, s, n in pairs:
        if l in df.columns and s in df.columns and n not in df.columns:
            df[n] = df[l] - df[s]
    return df

def _add_pct(df):
    for col in list(df.columns):
        pct_col = f"Pct OI {col}"
        if (pct_col not in df.columns and "Total OI" in df.columns
                and col not in ("Date","Commodity","Crop","Px")
                and not col.startswith("Traders") and not col.startswith("Conc")
                and not col.startswith("Pct OI")):
            try:
                df[pct_col] = (df[col] / df["Total OI"] * 100).round(2)
            except Exception:
                pass
    return df

@st.cache_data(ttl=600)
def load_cit() -> pd.DataFrame:
    df = pd.read_parquet(CIT_FILE)
    df = df.drop(columns=["Px"], errors="ignore")   # CFTC/ICE publish positions only
    df["Date"] = pd.to_datetime(df["Date"])
    num = [c for c in df.columns if c not in ("Date","Commodity","Crop")]
    df[num] = df[num].astype(float)
    df = _derive_nets(df, df.columns)
    # Combined spec = Large Spec + Non Rep + Index
    for side in ("Long","Short"):
        df[f"Combined Spec {side}"] = (
            df.get(f"Spec {side}", 0) +
            df.get(f"Non Rep {side}", 0) +
            df.get(f"Index {side}", 0)
        )
    df["Combined Spec Net"] = df["Combined Spec Long"] - df["Combined Spec Short"]
    # Large Spec + Non-Rep (excl. Index)
    for side in ("Long","Short"):
        df[f"Spec+NonRep {side}"] = (
            df.get(f"Spec {side}", 0) +
            df.get(f"Non Rep {side}", 0)
        )
    df["Spec+NonRep Net"] = df["Spec+NonRep Long"] - df["Spec+NonRep Short"]
    df = _add_pct(df)
    return df.sort_values(["Commodity","Date"]).reset_index(drop=True)

@st.cache_data(ttl=600)
def load_disagg(version: str) -> pd.DataFrame:
    path = FO_FILE if version == "F&O" else FUT_FILE
    df = pd.read_parquet(path)
    df = df.drop(columns=["Px"], errors="ignore")   # CFTC/ICE publish positions only
    df["Date"] = pd.to_datetime(df["Date"])
    num = [c for c in df.columns if c not in ("Date","Commodity","Crop")]
    df[num] = df[num].astype(float)
    df = _derive_nets(df, df.columns)
    # Combined spec (Disagg) = MM + Other + Non Rep + Swap
    for side in ("Long","Short"):
        df[f"Combined Spec {side}"] = (
            df.get(f"MM {side}", 0) +
            df.get(f"Other {side}", 0) +
            df.get(f"Non Rep {side}", 0) +
            df.get(f"Swap {side}", 0)
        )
    df["Combined Spec Net"] = df["Combined Spec Long"] - df["Combined Spec Short"]
    # MM + Other + Non-Rep (excl. Swap)
    for side in ("Long","Short"):
        df[f"MM+Other+NonRep {side}"] = (
            df.get(f"MM {side}", 0) +
            df.get(f"Other {side}", 0) +
            df.get(f"Non Rep {side}", 0)
        )
    df["MM+Other+NonRep Net"] = df["MM+Other+NonRep Long"] - df["MM+Other+NonRep Short"]
    df = _add_pct(df)
    return df.sort_values(["Commodity","Crop","Date"]).reset_index(drop=True)

@st.cache_data(ttl=600)
def load_options_only() -> pd.DataFrame:
    """Options Only = F&O Combined minus Futures Only (numeric cols only)."""
    fo  = pd.read_parquet(FO_FILE).drop(columns=["Px"], errors="ignore")
    fut = pd.read_parquet(FUT_FILE).drop(columns=["Px"], errors="ignore")
    fo["Date"]  = pd.to_datetime(fo["Date"])
    fut["Date"] = pd.to_datetime(fut["Date"])
    id_cols = ["Date","Commodity","Crop"]
    num_fo  = [c for c in fo.columns  if c not in id_cols]
    num_fut = [c for c in fut.columns if c not in id_cols]
    num_both = [c for c in num_fo if c in num_fut]
    merged = fo.merge(fut[id_cols + num_both], on=id_cols, how="left", suffixes=("","_fut"))
    for c in num_both:
        merged[c] = pd.to_numeric(merged[c], errors="coerce") - pd.to_numeric(merged[f"{c}_fut"], errors="coerce")
        merged.drop(columns=[f"{c}_fut"], inplace=True)
    df = merged.copy()
    df = _derive_nets(df, df.columns)
    for side in ("Long","Short"):
        df[f"Combined Spec {side}"] = (
            df.get(f"MM {side}", 0) + df.get(f"Other {side}", 0) +
            df.get(f"Non Rep {side}", 0) + df.get(f"Swap {side}", 0))
    df["Combined Spec Net"] = df["Combined Spec Long"] - df["Combined Spec Short"]
    for side in ("Long","Short"):
        df[f"MM+Other+NonRep {side}"] = (
            df.get(f"MM {side}", 0) + df.get(f"Other {side}", 0) + df.get(f"Non Rep {side}", 0))
    df["MM+Other+NonRep Net"] = df["MM+Other+NonRep Long"] - df["MM+Other+NonRep Short"]
    df = _add_pct(df)
    # Trader counts and concentration % are not valid for options-only
    # (trader overlap between fut/options means subtraction gives wrong counts;
    #  concentration % uses different OI bases so subtracting is meaningless)
    invalid_cols = [c for c in df.columns if
                    c.startswith("Traders") or c.startswith("Conc")]
    df[invalid_cols] = np.nan
    return df.sort_values(["Commodity","Crop","Date"]).reset_index(drop=True)











# ══════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ══════════════════════════════════════════════════════════════════════════════






def show_table(d: pd.DataFrame, pos_cols: list, chg_cols: list, label: str, n=60, scale=True):
    with st.expander(label, expanded=False):
        avail_p = [c for c in pos_cols if c and c in d.columns]
        avail_c = [c for c in chg_cols if c and c in d.columns]
        src = d.sort_values("Date", ascending=False).head(n).copy()
        dates = pd.to_datetime(src["Date"]).dt.strftime("%d %b '%y").tolist()

        # build column data — positions and deltas in k lots (unless scale=False)
        col_data = {}
        for col in avail_p:
            if col == "Px" or not scale:
                col_data[col] = src[col].values
            else:
                col_data[col] = (src[col] / 1000).values
        for col in avail_c:
            if scale:
                col_data[f"Δ {col}"] = (src[col].diff(-1) / 1000).values
            else:
                col_data[f"Δ {col}"] = src[col].diff(-1).values
        if "Px" in avail_p:
            col_data["Px Δ%"] = src["Px"].pct_change(-1).mul(100).values
        if "Total OI" in d.columns and "Total OI" not in avail_p:
            col_data["OI (k)"] = (src["Total OI"] / 1000).values

        signed_cols = {c for c in col_data if c.startswith("Δ") or c == "Px Δ%"}
        px_cols     = {"Px"}
        pct_cols    = {"Px Δ%"}

        def _fmt(col, v):
            if pd.isna(v): return "—"
            if col in pct_cols:    return f"{v:+.2f}%"
            if col in signed_cols: return f"{v:+,.1f}"
            if col in px_cols:     return f"{v:.2f}"
            return f"{v:,.1f}"

        headers = list(col_data.keys())

        hdr_html = "<tr><th class='idx sub'>Date</th>"
        for h in headers:
            lbl = h if not scale or h in ("Px", "Px Δ%", "OI (k)") or h.startswith("Δ") else f"{h} (k)"
            hdr_html += f"<th class='sub'>{lbl}</th>"
        hdr_html += "</tr>"

        body_html = ""
        for i, date in enumerate(dates):
            body_html += f"<tr><td class='idx'>{date}</td>"
            for col in headers:
                v = col_data[col][i]
                txt = _fmt(col, v)
                if col in signed_cols or col in pct_cols:
                    try:
                        fv = float(v)
                        cls = "rpos" if fv > 0 else ("rneg" if fv < 0 else "")
                    except: cls = ""
                else:
                    cls = ""
                body_html += f"<td class='{cls}'>{txt}</td>"
            body_html += "</tr>"

        html = (f"{_RECAP_CSS}<div style='overflow-x:auto;overflow-y:auto;max-height:480px;margin-bottom:6px'>"
                f"<table class='rtbl'><thead>{hdr_html}</thead><tbody>{body_html}</tbody></table></div>")
        st.markdown(html, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# CHART FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════











# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — SPEC
# ══════════════════════════════════════════════════════════════════════════════
CIT_SPEC = {
    "Large Spec":    {"long":"Spec Long",    "short":"Spec Short",    "net":"Spec Net",    "spread":None},
    "Non-Rep":       {"long":"Non Rep Long", "short":"Non Rep Short", "net":"Non Rep Net", "spread":None},
    "Index Traders": {"long":"Index Long",   "short":"Index Short",   "net":"Index Net",   "spread":None},
    "Large Spec + Non-Rep": {"long":"Spec+NonRep Long","short":"Spec+NonRep Short","net":"Spec+NonRep Net","spread":None},
    "Large Spec + Index + Non-Rep": {"long":"Combined Spec Long","short":"Combined Spec Short","net":"Combined Spec Net","spread":None},
}
DISAGG_SPEC = {
    "Managed Money":              {"long":"MM Long",    "short":"MM Short",    "net":"MM Net",    "spread":"MM Spread"},
    "Other Rept":                 {"long":"Other Long", "short":"Other Short", "net":"Other Net", "spread":"Other Spread"},
    "Non-Rep":                    {"long":"Non Rep Long","short":"Non Rep Short","net":"Non Rep Net","spread":None},
    "Swap Dealers":               {"long":"Swap Long",  "short":"Swap Short",  "net":"Swap Net",  "spread":"Swap Spread"},
    "MM + Other + Non-Rep":       {"long":"MM+Other+NonRep Long","short":"MM+Other+NonRep Short","net":"MM+Other+NonRep Net","spread":None},
    "MM + Other + Non-Rep + Swap":{"long":"Combined Spec Long","short":"Combined Spec Short","net":"Combined Spec Net","spread":None},
}



# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — COMMERCIAL
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SPREADING (Disagg only)
# ══════════════════════════════════════════════════════════════════════════════
SPREAD_COLS = {
    "Managed Money": ("MM Spread",    C_NET),
    "Swap Dealers":  ("Swap Spread",  "#7c3aed"),
    "Other Rept":    ("Other Spread", "#d97706"),
}

# OC/NC — same categories with a short key for column naming
_OCNC_CATS = {
    "Managed Money": ("MM Spread",    C_NET,    "MM"),
    "Swap Dealers":  ("Swap Spread",  "#7c3aed","Swap"),
    "Other Rept":    ("Other Spread", "#d97706","OR"),
}
_OCNC_C_CROSS = "#8b5cf6"   # cross-crop colour





# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — OLD / NEW CROP (Disagg only)
# ══════════════════════════════════════════════════════════════════════════════
# ── Old/New helpers ───────────────────────────────────────────────────────────
def _crop_year_label(dt, sm=CROP_START_MONTH):
    y, m = dt.year, dt.month
    return f"{str(y)[2:]}/{str(y+1)[2:]}" if m >= sm else f"{str(y-1)[2:]}/{str(y)[2:]}"

def _crop_week_num(dt, sm=CROP_START_MONTH):
    y = dt.year if dt.month >= sm else dt.year - 1
    return max(1, (dt - pd.Timestamp(y, sm, 1)).days // 7 + 1)

def _current_crop_year_label(sm=CROP_START_MONTH):
    return _crop_year_label(pd.Timestamp.now(), sm)

def _on_seasonal_wide(d_crops):
    old   = d_crops[d_crops["Crop"]=="Old"].set_index("Date").sort_index()
    other = d_crops[d_crops["Crop"]=="Other"].set_index("Date").sort_index()
    common = old.index.intersection(other.index)
    if common.empty: return pd.DataFrame()
    old, other = old.loc[common], other.loc[common]
    oi_sum = old["Total OI"] + other["Total OI"]
    def _col(df, name):
        return df[name] if name in df.columns else pd.Series(np.nan, index=df.index)

    wide = pd.DataFrame({
        "OI Old %":         old["Total OI"] / oi_sum * 100,
        # Managed Money
        "MM Net Old":       old["MM Net"],       "MM Net New":       other["MM Net"],
        "MM Long Old":      old["MM Long"],       "MM Long New":      other["MM Long"],
        "MM Short Old":     old["MM Short"],      "MM Short New":     other["MM Short"],
        "MM Diff":          old["MM Net"] - other["MM Net"],
        # Commercial
        "Comm Net Old":     _col(old, "Comm Net"),    "Comm Net New":     _col(other, "Comm Net"),
        "Comm Long Old":    _col(old, "Producer Long"),  "Comm Long New":    _col(other, "Producer Long"),
        "Comm Short Old":   _col(old, "Producer Short"), "Comm Short New":   _col(other, "Producer Short"),
        "Comm Diff":        _col(old, "Comm Net") - _col(other, "Comm Net"),
        # Swap Dealers
        "Swap Net Old":     _col(old, "Swap Net"),    "Swap Net New":     _col(other, "Swap Net"),
        "Swap Long Old":    _col(old, "Swap Long"),   "Swap Long New":    _col(other, "Swap Long"),
        "Swap Short Old":   _col(old, "Swap Short"),  "Swap Short New":   _col(other, "Swap Short"),
        "Swap Diff":        _col(old, "Swap Net") - _col(other, "Swap Net"),
        # Other Reportables
        "Other Net Old":    _col(old, "Other Net"),   "Other Net New":    _col(other, "Other Net"),
        "Other Long Old":   _col(old, "Other Long"),  "Other Long New":   _col(other, "Other Long"),
        "Other Short Old":  _col(old, "Other Short"), "Other Short New":  _col(other, "Other Short"),
        "Other Diff":       _col(old, "Other Net") - _col(other, "Other Net"),
        "Week": pd.Series(common.isocalendar().week.astype(int).values, index=common),
        "Year": pd.Series(common.year, index=common),
    }, index=common)
    return wide.reset_index()

def _seas_chart(wide, metric, title, accent, ylabel="k lots", by_week=True, sm=CROP_START_MONTH):
    if wide.empty or metric not in wide.columns:
        return go.Figure().update_layout(**_BASE, height=340)
    grp = "Week" if by_week else "CropWeek"
    yr_col = "Year" if by_week else "CropYear"
    pivot = wide.pivot_table(index=grp, columns=yr_col, values=metric, aggfunc="mean")
    pivot = pivot[pivot.index <= 52]
    if by_week:
        cur = int(wide["Year"].max())
        hist_cols = [c for c in pivot.columns if c < cur]
    else:
        cur = _current_crop_year_label(sm)
        hist_cols = [c for c in pivot.columns if c != cur]
    hist = pivot[hist_cols] if hist_cols else pivot
    if hist.empty or hist.shape[1] == 0:
        p25 = p75 = med = pd.Series(dtype=float)
    else:
        p25, p75, med = hist.quantile(0.25, axis=1), hist.quantile(0.75, axis=1), hist.median(axis=1)
    r, g, b = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
    fig = go.Figure()
    for yr in hist_cols:
        fig.add_trace(go.Scatter(x=pivot.index, y=hist[yr], mode="lines",
            line=dict(color="rgba(150,150,150,0.18)", width=1), showlegend=False, hoverinfo="skip"))
    xs = list(p75.index) + list(p75.index[::-1])
    fig.add_trace(go.Scatter(x=xs, y=list(p75.values)+list(p25.values[::-1]),
        fill="toself", fillcolor=f"rgba({r},{g},{b},0.10)",
        line=dict(width=0), name="25–75th pct", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=med.index, y=med.values, mode="lines", name="Median",
        line=dict(color=f"rgba({r},{g},{b},0.55)", width=1.6, dash="dash")))
    if cur in pivot.columns:
        cy = pivot[cur].dropna()
        fig.add_trace(go.Scatter(x=cy.index, y=cy.values, mode="lines+markers",
            name=str(cur), line=dict(color=accent, width=2.6), marker=dict(size=5, color=accent)))
    fig.add_hline(y=0, line_width=1, line_color="rgba(0,0,0,0.12)")
    if by_week:
        xticks = dict(tickvals=list(MONTH_TICKS.keys()), ticktext=list(MONTH_TICKS.values()))
    else:
        xticks = dict(tickvals=list(CROP_WEEK_TICKS.keys()),
                      ticktext=[_MONTHS[(sm - 1 + i) % 12] for i in range(12)])
    fig.update_layout(**_BASE, height=340,
        title=dict(text=title, font=dict(size=12, color="#444"), x=0),
        margin=dict(l=50, r=20, t=40, b=60),
        legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center", font_size=10, bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(**_ax(x=True), title_text="", **xticks),
        yaxis=dict(**_ax(), title_text=ylabel, title_font_size=10))
    return fig





def render_old_new(d_crops, color, commodity=""):
    old   = d_crops[d_crops["Crop"]=="Old"].set_index("Date").sort_index()
    other = d_crops[d_crops["Crop"]=="Other"].set_index("Date").sort_index()
    alla  = d_crops[d_crops["Crop"]=="All"].set_index("Date").sort_index()

    if old.empty and other.empty:
        st.info("No Old/Other crop data in selected range."); return

    # Gate on a category column that's actually populated for Old/Other rows
    # (MM Long, charted right below), not Total OI — Total OI has no crop
    # split available from LSEG at all (a documented, permanent gap) and is
    # always NaN on these rows, so gating on it wrongly blocked this whole
    # tab even for commodities (KC/CC/SB/CT/GC/SI/HG) that DO have real
    # Old/Other category data.
    other_check = d_crops[d_crops["Crop"]=="Other"]["MM Long"].dropna()
    if other_check.empty:
        st.info("Old/New crop split not available for this commodity."); return

    # Default crop-start month per commodity (forced for key markets)
    _forced_months = {"CT": 7, "KC": 9, "CC": 9}
    _forced_names  = {"CT": "July", "KC": "September", "CC": "September"}
    _default_month = _forced_months.get(commodity, CROP_START_MONTH)
    _forced_help   = (
        f"Default forced to {_forced_names[commodity]} for {commodity} to match the standard crop calendar. "
        "You can change it manually if needed."
        if commodity in _forced_months else None
    )

    with st.expander("Seasonality  ·  Old vs New Crop (adjustable start)", expanded=True):
        wide_full = _on_seasonal_wide(d_crops)
        if not wide_full.empty:
            if st.session_state.get("_cy_start_comm") != commodity:
                st.session_state["cy_start_on"] = _default_month
                st.session_state["_cy_start_comm"] = commodity
            sm = st.selectbox("Crop year starts in", list(range(1,13)),
                              index=_default_month-1, format_func=lambda m: _MONTHS[m-1],
                              key="cy_start_on", help=_forced_help)
            wide_cy = wide_full.copy()
            wide_cy["CropYear"] = pd.to_datetime(wide_cy["Date"]).apply(lambda d: _crop_year_label(d, sm))
            wide_cy["CropWeek"] = pd.to_datetime(wide_cy["Date"]).apply(lambda d: _crop_week_num(d, sm))
            cur_cy = _current_crop_year_label(sm)
            st.markdown(
                f"<p style='font-size:.75rem;color:{GRAY};margin-bottom:4px'>"
                f"Each line = one crop year · Bold = current ({cur_cy}) · Shaded = 25–75th pct</p>",
                unsafe_allow_html=True)

            def _sc(metric, title, ylabel="k lots"):
                return _seas_chart(wide_cy, metric, title, color, ylabel, by_week=False, sm=sm)

            # ── Managed Money ─────────────────────────────────────────────────
            st.markdown("<div style='font-size:.75rem;font-weight:700;color:#374151;"
                        "margin:14px 0 6px;letter-spacing:.04em'>MANAGED MONEY</div>",
                        unsafe_allow_html=True)
            mm1, mm2, mm3 = st.columns(3)
            with mm1: st.plotly_chart(_sc("MM Net Old",   "MM Net (Old)  ·  k lots"),   width='stretch')
            with mm2: st.plotly_chart(_sc("MM Net New",   "MM Net (New)  ·  k lots"),   width='stretch')
            with mm3: st.plotly_chart(_sc("MM Diff",      "MM Net (Old − New)  ·  k lots"),    width='stretch')
            mm4, mm5, _ = st.columns(3)
            with mm4: st.plotly_chart(_sc("MM Long Old",  "MM Long (Old)  ·  k lots"),  width='stretch')
            with mm5: st.plotly_chart(_sc("MM Long New",  "MM Long (New)  ·  k lots"),  width='stretch')
            mm6, mm7, _ = st.columns(3)
            with mm6: st.plotly_chart(_sc("MM Short Old", "MM Short (Old)  ·  k lots"), width='stretch')
            with mm7: st.plotly_chart(_sc("MM Short New", "MM Short (New)  ·  k lots"), width='stretch')

            # ── Commercial ────────────────────────────────────────────────────
            st.markdown("<div style='font-size:.75rem;font-weight:700;color:#374151;"
                        "margin:14px 0 6px;letter-spacing:.04em'>COMMERCIAL</div>",
                        unsafe_allow_html=True)
            cm1, cm2, cm3 = st.columns(3)
            with cm1: st.plotly_chart(_sc("Comm Net Old",   "Comm Net (Old)  ·  k lots"),           width='stretch')
            with cm2: st.plotly_chart(_sc("Comm Net New",   "Comm Net (New)  ·  k lots"),           width='stretch')
            with cm3: st.plotly_chart(_sc("Comm Diff",      "Comm Net (Old − New)  ·  k lots"),     width='stretch')
            cm4, cm5, _ = st.columns(3)
            with cm4: st.plotly_chart(_sc("Comm Long Old",  "Comm Long (Old)  ·  k lots"),          width='stretch')
            with cm5: st.plotly_chart(_sc("Comm Long New",  "Comm Long (New)  ·  k lots"),          width='stretch')
            cm6, cm7, _ = st.columns(3)
            with cm6: st.plotly_chart(_sc("Comm Short Old", "Comm Short (Old)  ·  k lots"),         width='stretch')
            with cm7: st.plotly_chart(_sc("Comm Short New", "Comm Short (New)  ·  k lots"),         width='stretch')

            # ── Swap Dealers ──────────────────────────────────────────────────
            st.markdown("<div style='font-size:.75rem;font-weight:700;color:#374151;"
                        "margin:14px 0 6px;letter-spacing:.04em'>SWAP DEALERS</div>",
                        unsafe_allow_html=True)
            sw1, sw2, sw3 = st.columns(3)
            with sw1: st.plotly_chart(_sc("Swap Net Old",   "Swap Net (Old)  ·  k lots"),           width='stretch')
            with sw2: st.plotly_chart(_sc("Swap Net New",   "Swap Net (New)  ·  k lots"),           width='stretch')
            with sw3: st.plotly_chart(_sc("Swap Diff",      "Swap Net (Old − New)  ·  k lots"),     width='stretch')
            sw4, sw5, _ = st.columns(3)
            with sw4: st.plotly_chart(_sc("Swap Long Old",  "Swap Long (Old)  ·  k lots"),          width='stretch')
            with sw5: st.plotly_chart(_sc("Swap Long New",  "Swap Long (New)  ·  k lots"),          width='stretch')
            sw6, sw7, _ = st.columns(3)
            with sw6: st.plotly_chart(_sc("Swap Short Old", "Swap Short (Old)  ·  k lots"),         width='stretch')
            with sw7: st.plotly_chart(_sc("Swap Short New", "Swap Short (New)  ·  k lots"),         width='stretch')

            # ── Other Reportables ─────────────────────────────────────────────
            st.markdown("<div style='font-size:.75rem;font-weight:700;color:#374151;"
                        "margin:14px 0 6px;letter-spacing:.04em'>OTHER REPORTABLES</div>",
                        unsafe_allow_html=True)
            or1, or2, or3 = st.columns(3)
            with or1: st.plotly_chart(_sc("Other Net Old",   "Other Net (Old)  ·  k lots"),         width='stretch')
            with or2: st.plotly_chart(_sc("Other Net New",   "Other Net (New)  ·  k lots"),         width='stretch')
            with or3: st.plotly_chart(_sc("Other Diff",      "Other Net (Old − New)  ·  k lots"),   width='stretch')
            or4, or5, _ = st.columns(3)
            with or4: st.plotly_chart(_sc("Other Long Old",  "Other Long (Old)  ·  k lots"),        width='stretch')
            with or5: st.plotly_chart(_sc("Other Long New",  "Other Long (New)  ·  k lots"),        width='stretch')
            or6, or7, _ = st.columns(3)
            with or6: st.plotly_chart(_sc("Other Short Old", "Other Short (Old)  ·  k lots"),       width='stretch')
            with or7: st.plotly_chart(_sc("Other Short New", "Other Short (New)  ·  k lots"),       width='stretch')

            # ── Open Interest ─────────────────────────────────────────────────
            st.markdown("<div style='font-size:.75rem;font-weight:700;color:#374151;"
                        "margin:14px 0 6px;letter-spacing:.04em'>OPEN INTEREST</div>",
                        unsafe_allow_html=True)
            oi1, oi2, _ = st.columns(3)
            with oi1: st.plotly_chart(_sc("OI Old %", "OI % (Old)", "%"), width='stretch')

    with st.expander("Data table  ·  Old Crop / New Crop", expanded=False):
        common_dates = old.index.union(other.index).sort_values()[::-1][:30]
        common_dates_ext = old.index.union(other.index).sort_values()[::-1][:31]

        def _get_s(df, col, dates):
            return (df.reindex(dates)[col] / 1000) if col in df.columns else pd.Series(np.nan, index=dates)

        def _build_tbl(dates):
            data = {}
            for src, lbl in [("MM Net","MM Net Old"),("Comm Net","Comm Net Old")]:
                data[("Net · k lots", lbl)] = _get_s(old, src, dates).values
            for src, lbl in [("MM Net","MM Net New"),("Comm Net","Comm Net New")]:
                data[("Net · k lots", lbl)] = _get_s(other, src, dates).values
            for src, lbl in [("MM Long","Old"),("MM Short","Old"),("Producer Long","Old"),("Producer Short","Old")]:
                data[(src.replace("Producer","Prod"), lbl)] = _get_s(old, src, dates).values
            for src, lbl in [("MM Long","New"),("MM Short","New"),("Producer Long","New"),("Producer Short","New")]:
                data[(src.replace("Producer","Prod"), lbl)] = _get_s(other, src, dates).values
            data[("OI · k lots", "Old")] = _get_s(old, "Total OI", dates).values
            data[("OI · k lots", "New")] = _get_s(other, "Total OI", dates).values
            return pd.DataFrame(data, index=dates)

        tbl_df = _build_tbl(common_dates)
        tbl_df.index = pd.to_datetime(tbl_df.index).strftime("%d %b '%y")
        tbl_df.index.name = None
        st.markdown(_recap_html(tbl_df, scroll=True), unsafe_allow_html=True)

        tbl_ext = _build_tbl(common_dates_ext)
        chg_df = tbl_ext.diff(-1).iloc[:len(common_dates)]
        chg_df.index = pd.to_datetime(common_dates).strftime("%d %b '%y")
        chg_df.index.name = None
        st.markdown(
            f"<p style='font-size:.72rem;color:{GRAY};margin:8px 0 2px'>Weekly change  ·  k lots</p>",
            unsafe_allow_html=True)
        all_groups = {g for g, _ in chg_df.columns}
        st.markdown(_recap_html(chg_df, signed_groups=all_groups, scroll=True), unsafe_allow_html=True)

    # ── OI split ──────────────────────────────────────────────────────────────
    with st.expander("Open Interest  ·  Old vs New Crop", expanded=False):
        dates = old.index.union(other.index).sort_values()
        fig_oi = go.Figure([
            go.Bar(x=dates, y=old.reindex(dates)["Total OI"]/1000, name="Old Crop",
                   marker=dict(color=C_OLD,opacity=0.85,line=dict(width=0)),
                   hovertemplate="<b>%{x|%d %b %y}</b><br>Old OI: %{y:.1f}k<extra></extra>"),
            go.Bar(x=dates, y=other.reindex(dates)["Total OI"]/1000, name="New Crop",
                   marker=dict(color=C_NEW,opacity=0.85,line=dict(width=0)),
                   hovertemplate="<b>%{x|%d %b %y}</b><br>New OI: %{y:.1f}k<extra></extra>"),
        ])
        fig_oi.update_layout(**_BASE, barmode="stack", height=300,
            title=dict(text="Open Interest — Old vs New Crop  ·  k lots",font=dict(size=12,color="#444"),x=0),
            margin=dict(l=50,r=12,t=38,b=68), bargap=0.18,
            legend=dict(orientation="h",y=-0.24,x=0.5,xanchor="center",font_size=10),
            xaxis=dict(**_ax(x=True),tickformat="%d %b '%y"),
            yaxis=dict(**_ax(),title_text="k lots",title_font_size=10))
        st.plotly_chart(fig_oi, width='stretch')

    # ── Net positions ─────────────────────────────────────────────────────────
    with st.expander("Net Positions  ·  MM & Commercial", expanded=False):
        c1, c2 = st.columns(2)
        for col_c, (col, title) in zip([c1,c2],[("MM Net","Managed Money Net"),("Comm Net","Commercial (Prod) Net")]):
            with col_c:
                fig = go.Figure()
                for crop_df, lbl, clr in [(old,"Old Crop",C_OLD),(other,"New Crop",C_NEW)]:
                    if col in crop_df.columns:
                        fig.add_trace(go.Scatter(x=crop_df.index, y=crop_df[col]/1000, name=lbl,
                            line=dict(color=clr, width=2.2, shape="spline", smoothing=0.6),
                            hovertemplate=f"<b>%{{x|%d %b %y}}</b><br>{lbl}: %{{y:.1f}}k<extra></extra>"))
                fig.add_hline(y=0, line_width=1, line_color="rgba(0,0,0,0.15)")
                fig.update_layout(**_BASE, height=340,
                    title=dict(text=f"{title}  ·  k lots",font=dict(size=12,color="#444"),x=0),
                    margin=dict(l=50,r=20,t=40,b=70),
                    legend=dict(orientation="h",y=-0.22,x=0.5,xanchor="center",font_size=10,bgcolor="rgba(0,0,0,0)"),
                    xaxis=dict(**_ax(x=True),tickformat="%d %b '%y"),
                    yaxis=dict(**_ax(),title_text="k lots",title_font_size=10))
                st.plotly_chart(fig, width='stretch')

    # ── Gross legs ────────────────────────────────────────────────────────────
    with st.expander("Gross Legs  ·  Old vs New Crop", expanded=False):
        gross_legs = [(c,t) for c,t in [
            ("MM Long","MM Long"),("MM Short","MM Short"),
            ("Producer Long","Comm Long"),("Producer Short","Comm Short"),
        ] if c in old.columns or c in other.columns]
        for col, title in gross_legs:
            c1, c2 = st.columns(2)
            with c1:
                fig = go.Figure()
                for crop_df, lbl, clr in [(old,"Old",C_OLD),(other,"New",C_NEW)]:
                    if col in crop_df.columns:
                        fig.add_trace(go.Scatter(x=crop_df.index, y=crop_df[col]/1000, name=lbl,
                            line=dict(color=clr,width=2.2,shape="spline",smoothing=0.6),
                            hovertemplate=f"<b>%{{x|%d %b %y}}</b><br>{lbl}: %{{y:.1f}}k<extra></extra>"))
                fig.update_layout(**_BASE, height=300,
                    title=dict(text=f"{title}  ·  k lots",font=dict(size=12,color="#444"),x=0),
                    margin=dict(l=50,r=20,t=40,b=70),
                    legend=dict(orientation="h",y=-0.24,x=0.5,xanchor="center",font_size=10,bgcolor="rgba(0,0,0,0)"),
                    xaxis=dict(**_ax(x=True),tickformat="%d %b '%y"),
                    yaxis=dict(**_ax(),title_text="k lots",title_font_size=10))
                st.plotly_chart(fig, width='stretch')
            with c2:
                dates2 = old.index.union(other.index).sort_values()
                fig2 = go.Figure([
                    go.Bar(x=dates2, y=old.reindex(dates2)[col]/1000 if col in old.columns else None,
                           name="Old", marker=dict(color=C_OLD,opacity=0.85,line=dict(width=0)),
                           hovertemplate=f"<b>%{{x|%d %b %y}}</b><br>Old: %{{y:.1f}}k<extra></extra>"),
                    go.Bar(x=dates2, y=other.reindex(dates2)[col]/1000 if col in other.columns else None,
                           name="New", marker=dict(color=C_NEW,opacity=0.85,line=dict(width=0)),
                           hovertemplate=f"<b>%{{x|%d %b %y}}</b><br>New: %{{y:.1f}}k<extra></extra>"),
                ])
                fig2.update_layout(**_BASE, barmode="stack", height=280,
                    title=dict(text=f"{title} — Stacked  ·  k lots",font=dict(size=12,color="#444"),x=0),
                    margin=dict(l=50,r=20,t=40,b=70), bargap=0.12,
                    legend=dict(orientation="h",y=-0.26,x=0.5,xanchor="center",font_size=10,bgcolor="rgba(0,0,0,0)"),
                    xaxis=dict(**_ax(x=True),tickformat="%d %b '%y"),
                    yaxis=dict(**_ax(),title_text="k lots",title_font_size=10))
                st.plotly_chart(fig2, width='stretch')




# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — TRADERS
# ══════════════════════════════════════════════════════════════════════════════
CIT_TRADER_GROUPS = {
    "Spec":          ["Traders Spec Long","Traders Spec Short","Traders Spec Spread"],
    "Commercial":    ["Traders Comm Long","Traders Comm Short"],
    "Index":         ["Traders Index Long","Traders Index Short"],
    "All Reportable":["Traders Tot Rept Long","Traders Tot Rept Short"],
}
DISAGG_TRADER_GROUPS = {
    "Managed Money": ["Traders MM Long","Traders MM Short","Traders MM Spread"],
    "Swap Dealers":  ["Traders Swap Long","Traders Swap Short","Traders Swap Spread"],
    "Other Rept":    ["Traders Other Long","Traders Other Short","Traders Other Spread"],
    "Producer":      ["Traders Producer Long","Traders Producer Short"],
    "All Reportable":["Traders Tot Rept Long","Traders Tot Rept Short","Traders Total"],
}
TRADER_COLORS = [C_LONG, C_SHORT, "#94a3b8", C_NET, C_PRICE]



# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — CONCENTRATION
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# TAB 0 — RECAP
# ══════════════════════════════════════════════════════════════════════════════
_RECAP_GROUP_BG = {
    "Gross Positions": "#d1d5db",
    "NET":             "#bae6fd",
    "SPREAD":          "#fed7aa",
    "SP":              "#fed7aa",
    "MM+O+NR":         "#a7f3d0",
    "OI":              "#e5e7eb",
    "OI · k lots":     "#e5e7eb",
    "Δ 1w":            "#f9a8d4",
    "OI %":            "#1e3a8a",
    "Nominal (M USD)": "#d1fae5",
    "Nominal (M GBP)": "#fef9c3",
    "# Traders":       "#ede9fe",
    "k lots / Trader": "#fef08a",
    "Old Crop":        "#fde68a",
    "New Crop":        "#bbf7d0",
    "Net · k lots":    "#bae6fd",
    "MM Long":         "#d1fae5",
    "MM Short":        "#fee2e2",
    "Prod Long":       "#e0e7ff",
    "Prod Short":      "#fce7f3",
    "Rollex Px":       "#fef3c7",
    "Longs · k lots":  "#d1fae5",
    "Shorts · k lots": "#fee2e2",
    "Long % OI":       "#bbf7d0",
    "Short % OI":      "#fecaca",
}
_RECAP_GROUP_TEXT = {
    "OI %": "#ffffff",
}
_CHANGE_BG = "#f9a8d4"

_RECAP_CSS = """
<style>
.rtbl{border-collapse:collapse;font-size:.67rem;width:100%;font-family:-apple-system,sans-serif}
.rtbl th,.rtbl td{border:1px solid #e5e7eb;padding:2px 4px;text-align:center}
.rtbl td{white-space:nowrap}
.rtbl .grp{text-align:center;font-weight:700;font-size:.64rem;letter-spacing:.02em;white-space:normal;max-width:60px}
.rtbl .idx{text-align:left;font-weight:600;color:#374151;background:#f9fafb;min-width:52px;white-space:nowrap}
.rtbl .sub{background:#f9fafb;font-size:.60rem;color:#555;font-weight:600;text-align:center;white-space:normal;max-width:48px;line-height:1.25}
.rtbl tbody tr:hover td{background:#f0f9ff!important}
.rpos{color:#16a34a}.rneg{color:#dc2626}
.rtbl .gsep{box-shadow:inset 3px 0 0 #6b7280}
.rtbl .gsub{box-shadow:inset 1.5px 0 0 #b8c0cc}
.rtbl th.sub[data-tt]{position:relative;cursor:help}
.rtbl th.sub[data-tt]::after{
  content:attr(data-tt);
  position:absolute;
  top:calc(100% + 4px);
  left:50%;
  transform:translateX(-50%);
  background:#1e293b;
  color:#f1f5f9;
  padding:5px 10px;
  border-radius:5px;
  font-size:.69rem;
  font-weight:400;
  white-space:nowrap;
  z-index:9999;
  pointer-events:none;
  opacity:0;
  transition:opacity .15s ease;
  box-shadow:0 2px 8px rgba(0,0,0,.30);
  line-height:1.5;
}
.rtbl th.sub[data-tt]::before{
  content:'';
  position:absolute;
  top:100%;
  left:50%;
  transform:translateX(-50%);
  border:5px solid transparent;
  border-bottom-color:#1e293b;
  z-index:9999;
  opacity:0;
  transition:opacity .15s ease;
  pointer-events:none;
}
.rtbl th.sub[data-tt]:hover::after,.rtbl th.sub[data-tt]:hover::before{opacity:1}
</style>
"""

_COLUMN_TOOLTIPS = {
    ("NET", "Large+Small"):      "Large Spec Net + Non-Rep Net",
    ("NET", "Lrg+Sml+Idx"):     "Large Spec Net + Non-Rep Net + Index Net",
    ("MM+O+NR", "Long"):              "MM Long + Other Long + Non-Rep Long",
    ("MM+O+NR", "Short"):             "MM Short + Other Short + Non-Rep Short",
    ("NET", "MM+O+NR"):               "MM Net + Other Net + Non-Rep Net",
    ("NET", "Rest"):                  "Other Net + Non-Rep Net",
    ("NET", "MM"):                    "Managed Money Net",
    ("NET", "Comm"):                  "Producer/Commercial Net",
    ("Gross Positions", "L+S Long"):  "Large Long + Small Long (Spec + Non-Rep)",
    ("Gross Positions", "L+S Short"): "Large Short + Small Short (Spec + Non-Rep)",
    ("Gross Positions", "L+S+I Long"):  "Large + Small + Index Long (all ex-Commercial)",
    ("Gross Positions", "L+S+I Short"): "Large + Small + Index Short (all ex-Commercial)",
}

# Sub-group separators within Gross Positions (medium border before each new pair)
_RECAP_COL_SUBSEP = {
    ("Gross Positions", "L+S Long"),      # CIT: after Large pair
    ("Gross Positions", "Index Long"),    # CIT: after L+S pair
    ("Gross Positions", "L+S+I Long"),    # CIT: after Index pair
    ("Gross Positions", "Comm Long"),     # CIT + Disagg: start of commercial
    ("Gross Positions", "Other Long"),    # Disagg: after MM pair
    ("Gross Positions", "Non-Rep Long"),  # Disagg: after Other pair
    ("Gross Positions", "Swap Long"),     # Disagg: after Non-Rep pair
    ("MM+O+NR", "Long"),                  # Disagg: aggregate pair separator
}

def _recap_html(df, signed=False, change_table=False, scroll=False, signed_groups=None,
                pct_groups=None, pct_subcols=None, signed_rows=None, z_rows=None, max_height=None):
    if df.empty: return ""
    cols = list(df.columns)
    # Build group spans
    groups, prev = [], None
    for c in cols:
        g = c[0]
        if g == prev: groups[-1][1] += 1
        else: groups.append([g, 1]); prev = g

    # Pre-compute border class per column: gsep = major group start, gsub = sub-group within Gross
    col_sep = []
    ci = 0
    for g, span in groups:
        for j in range(span):
            c = cols[ci + j]
            if j == 0:
                col_sep.append("gsep")
            elif c in _RECAP_COL_SUBSEP:
                col_sep.append("gsub")
            else:
                col_sep.append("")
        ci += span

    # Header row 1 — merged group headers (bold left border on each group)
    h1 = '<tr><th class="idx sub"></th>'
    for g, span in groups:
        bg = _RECAP_GROUP_BG.get(g, "#f9fafb")
        fg = _RECAP_GROUP_TEXT.get(g, "#111827")
        h1 += (f'<th colspan="{span}" class="grp" '
               f'style="background:{bg};color:{fg};box-shadow:inset 3px 0 0 #6b7280">{g}</th>')
    h1 += '</tr>'

    # Header row 2 — sub-column names (with hover tooltips where defined)
    h2 = '<tr><th class="idx sub"></th>'
    for i, c in enumerate(cols):
        g = c[0]
        sep_cls = col_sep[i]
        tip = _COLUMN_TOOLTIPS.get(c)
        tip_attr = f' data-tt="{tip}"' if tip else ''
        label = f'{c[1]}&thinsp;<span style="font-size:.6rem;color:#9ca3af;font-weight:400">ⓘ</span>' if tip else c[1]
        fsz = ";font-size:.62rem" if len(c[1]) > 9 else ""
        cls_str = f"sub {sep_cls}".strip()
        if g in _RECAP_GROUP_TEXT:
            bg = _RECAP_GROUP_BG.get(g, "#f9fafb")
            fg = _RECAP_GROUP_TEXT[g]
            h2 += f'<th class="{cls_str}" style="background:{bg};color:{fg}{fsz}"{tip_attr}>{label}</th>'
        else:
            style_attr = f' style="font-size:.62rem"' if fsz else ''
            h2 += f'<th class="{cls_str}"{style_attr}{tip_attr}>{label}</th>'
    h2 += '</tr>'

    # Body rows
    body = ""
    for idx, row in df.iterrows():
        body += f'<tr><td class="idx">{idx}</td>'
        for i, c in enumerate(cols):
            sep_cls = col_sep[i]
            v = row[c]
            if pd.isna(v): body += f'<td class="{sep_cls}">—</td>'; continue
            is_z_row  = z_rows and idx in z_rows
            use_signed = (signed or change_table
                          or (signed_rows and idx in signed_rows)
                          or (signed_groups and isinstance(c, tuple) and c[0] in signed_groups))
            use_pct = ((pct_groups and isinstance(c, tuple) and c[0] in pct_groups) or
                       (pct_subcols and isinstance(c, tuple) and c in pct_subcols))
            fmt = ".2f" if is_z_row else ".1f"
            if use_signed:
                txt = f"{v:+{fmt}}"
                cls = "rpos" if v > 0 else ("rneg" if v < 0 else "")
            elif use_pct:
                txt = f"{v:.1f}%"; cls = ""
            else:
                txt = f"{v:{fmt}}"; cls = ""
            full_cls = f"{cls} {sep_cls}".strip()
            body += f'<td class="{full_cls}">{txt}</td>'
        body += '</tr>'

    if max_height is not None:
        scroll_style = f"overflow-x:auto;overflow-y:auto;max-height:{max_height}px;"
    elif scroll:
        scroll_style = "overflow-x:auto;overflow-y:auto;max-height:420px;"
    else:
        scroll_style = "overflow-x:auto;"
    return (f'{_RECAP_CSS}<div style="{scroll_style}margin-bottom:6px">'
            f'<table class="rtbl"><thead>{h1}{h2}</thead>'
            f'<tbody>{body}</tbody></table></div>')

def _build_recap_df(d, report):
    d = d.sort_values("Date", ascending=True).reset_index(drop=True)
    if d.empty:
        return pd.DataFrame(), pd.DataFrame()

    def gc(name):
        return d[name].astype(float) if name in d.columns else pd.Series(0.0, index=d.index)

    cols = {}

    if report == "CIT":
        for src, dst in [("Spec Long","Large Long"),("Spec Short","Large Short"),
                         ("Non Rep Long","Small Long"),("Non Rep Short","Small Short")]:
            if src in d.columns: cols[("Gross Positions", dst)] = gc(src) / 1000
        cols[("Gross Positions", "L+S Long")]    = (gc("Spec Long") + gc("Non Rep Long"))  / 1000
        cols[("Gross Positions", "L+S Short")]   = (gc("Spec Short")+ gc("Non Rep Short")) / 1000
        for src, dst in [("Index Long","Index Long"),("Index Short","Index Short")]:
            if src in d.columns: cols[("Gross Positions", dst)] = gc(src) / 1000
        cols[("Gross Positions", "L+S+I Long")]  = (gc("Spec Long") + gc("Non Rep Long")  + gc("Index Long"))  / 1000
        cols[("Gross Positions", "L+S+I Short")] = (gc("Spec Short")+ gc("Non Rep Short") + gc("Index Short")) / 1000
        for src, dst in [("Comm Long","Comm Long"),("Comm Short","Comm Short")]:
            if src in d.columns: cols[("Gross Positions", dst)] = gc(src) / 1000

        cols[("NET", "Large")]        = gc("Spec Net")   / 1000
        cols[("NET", "Small")]        = gc("Non Rep Net") / 1000
        cols[("NET", "Index")]        = gc("Index Net")   / 1000
        cols[("NET", "Comm")]         = gc("Comm Net")    / 1000
        cols[("NET", "Large+Small")]  = (gc("Spec Net") + gc("Non Rep Net")) / 1000
        cols[("NET", "Lrg+Sml+Idx")] = (gc("Spec Net") + gc("Non Rep Net") + gc("Index Net")) / 1000

        if "Spec Spread" in d.columns:
            cols[("SPREAD", "Spec Spread")] = gc("Spec Spread") / 1000

        cols[("OI", "Total OI")] = gc("Total OI") / 1000

    else:  # Disagg
        for src, dst in [
            ("MM Long",       "MM Long"),    ("MM Short",       "MM Short"),
            ("Other Long",    "Other Long"), ("Other Short",    "Other Short"),
            ("Non Rep Long",  "Non-Rep Long"),("Non Rep Short", "Non-Rep Short"),
            ("Swap Long",     "Swap Long"),  ("Swap Short",     "Swap Short"),
            ("Producer Long", "Comm Long"),  ("Producer Short", "Comm Short"),
        ]:
            if src in d.columns:
                cols[("Gross Positions", dst)] = gc(src) / 1000

        cols[("MM+O+NR", "Long")]  = (gc("MM Long")  + gc("Other Long")  + gc("Non Rep Long"))  / 1000
        cols[("MM+O+NR", "Short")] = (gc("MM Short") + gc("Other Short") + gc("Non Rep Short")) / 1000

        cols[("NET", "MM")]      = gc("MM Net")   / 1000
        cols[("NET", "Rest")]    = (gc("Other Net") + gc("Non Rep Net")) / 1000
        cols[("NET", "MM+O+NR")] = (gc("MM Net") + gc("Other Net") + gc("Non Rep Net")) / 1000
        cols[("NET", "Swap")]    = gc("Swap Net")  / 1000
        cols[("NET", "Comm")]    = gc("Comm Net")  / 1000

        for src, dst in [
            ("MM Spread",    "MM Spread"),
            ("Other Spread", "Other Spread"),
            ("Swap Spread",  "Swap Spread"),
        ]:
            if src in d.columns:
                cols[("SP", dst)] = gc(src) / 1000

        cols[("OI", "Total OI")] = gc("Total OI") / 1000


    body = pd.DataFrame(cols)
    body.index = pd.to_datetime(d["Date"])
    body = body.iloc[::-1]  # newest first

    row_1w, row_4w = {}, {}
    for c in body.columns:
        if len(body) >= 2:
            row_1w[c] = body.iloc[0][c] - body.iloc[1][c]
        if len(body) >= 5:
            row_4w[c] = body.iloc[0][c] - body.iloc[4][c]


    # Z-Score, Avg, Min, Max computed over full history (all columns incl. Δ% 1w)
    row_z, row_avg, row_min, row_max = {}, {}, {}, {}
    for c in body.columns:
        series = body[c].replace([np.inf, -np.inf], np.nan).dropna()
        if len(series) >= 4:
            mu, sigma = series.mean(), series.std()
            row_z[c]   = (series.iloc[0] - mu) / sigma if sigma > 0 else 0.0
            row_avg[c] = mu
            row_min[c] = series.min()
            row_max[c] = series.max()

    summary = pd.DataFrame(
        [row_1w, row_4w, row_z, row_avg, row_min, row_max],
        index=["Δ 1w", "Δ 1m", "Z-Score", "Avg", "Min", "Max"],
        columns=body.columns,
    )


    body.index = [f"{dt.day}-{dt.strftime('%b-%y')}" for dt in body.index]
    return summary, body


def _build_oi_df(d, report):
    d = d.sort_values("Date", ascending=True).reset_index(drop=True)
    if d.empty:
        return pd.DataFrame()

    def gc(name):
        return d[name].astype(float) if name in d.columns else pd.Series(0.0, index=d.index)

    total_oi = gc("Total OI") / 1000

    if report == "CIT":
        oi_cols = {
            "Large Spec": (gc("Spec Long") + gc("Spec Short")) / 2 / 1000 + gc("Spec Spread") / 1000,
            "Small Spec": (gc("Non Rep Long") + gc("Non Rep Short")) / 2 / 1000,
            "Index":      (gc("Index Long") + gc("Index Short")) / 2 / 1000,
            "Commercial": (gc("Comm Long") + gc("Comm Short")) / 2 / 1000,
        }
    else:
        oi_cols = {
            "MM":         (gc("MM Long") + gc("MM Short")) / 2 / 1000 + gc("MM Spread") / 1000,
            "Other":      (gc("Other Long") + gc("Other Short")) / 2 / 1000 + gc("Other Spread") / 1000,
            "Swap":       (gc("Swap Long") + gc("Swap Short")) / 2 / 1000 + gc("Swap Spread") / 1000,
            "Commercial": (gc("Producer Long") + gc("Producer Short")) / 2 / 1000,
            "Non-Rep":    (gc("Non Rep Long") + gc("Non Rep Short")) / 2 / 1000,
        }

    oi_df = pd.DataFrame(oi_cols)
    oi_df.index = pd.to_datetime(d["Date"])
    oi_df = oi_df.iloc[::-1].iloc[:20]  # newest first, last 20

    total_s = pd.Series(total_oi.values, index=pd.to_datetime(d["Date"])).iloc[::-1].iloc[:20]
    pct_df  = oi_df.div(total_s.values, axis=0) * 100   # % before adding Total OI col

    oi_df["Total OI"] = total_s.values                  # add Total OI after pct calc
    chg_df = oi_df.diff(-1)

    cats     = list(oi_cols.keys())
    all_cats = cats + ["Total OI"]
    combined = pd.concat([oi_df[all_cats], pct_df[cats], chg_df[all_cats]], axis=1)
    combined.columns = pd.MultiIndex.from_tuples(
        [("OI · k lots", c) for c in all_cats] +
        [("OI %",        c) for c in cats] +
        [("Δ 1w",        c) for c in all_cats]
    )
    combined.index = [f"{dt.day}-{dt.strftime('%b-%y')}" for dt in combined.index]
    return combined


def _build_gross_legs_df(d, report):
    d = d.sort_values("Date", ascending=True).reset_index(drop=True)
    if d.empty:
        return pd.DataFrame()

    def gc(name):
        return d[name].astype(float) if name in d.columns else pd.Series(0.0, index=d.index)

    total_oi = gc("Total OI")

    if report == "CIT":
        cats = ["Large Spec", "Index", "Commercial", "Non-Rep"]
        longs = {
            "Large Spec": (gc("Spec Long")  + gc("Spec Spread")) / 1000,
            "Index":       gc("Index Long")  / 1000,
            "Commercial":  gc("Comm Long")   / 1000,
            "Non-Rep":     gc("Non Rep Long") / 1000,
        }
        shorts = {
            "Large Spec": (gc("Spec Short") + gc("Spec Spread")) / 1000,
            "Index":       gc("Index Short")  / 1000,
            "Commercial":  gc("Comm Short")   / 1000,
            "Non-Rep":     gc("Non Rep Short") / 1000,
        }
    else:
        cats = ["MM", "Other", "Swap", "Commercial", "Non-Rep"]
        longs = {
            "MM":         (gc("MM Long")    + gc("MM Spread"))    / 1000,
            "Other":      (gc("Other Long") + gc("Other Spread")) / 1000,
            "Swap":       (gc("Swap Long")  + gc("Swap Spread"))  / 1000,
            "Commercial":  gc("Producer Long") / 1000,
            "Non-Rep":     gc("Non Rep Long")  / 1000,
        }
        shorts = {
            "MM":         (gc("MM Short")    + gc("MM Spread"))    / 1000,
            "Other":      (gc("Other Short") + gc("Other Spread")) / 1000,
            "Swap":       (gc("Swap Short")  + gc("Swap Spread"))  / 1000,
            "Commercial":  gc("Producer Short") / 1000,
            "Non-Rep":     gc("Non Rep Short")  / 1000,
        }

    long_df  = pd.DataFrame(longs).iloc[::-1].iloc[:20]
    short_df = pd.DataFrame(shorts).iloc[::-1].iloc[:20]
    idx      = pd.to_datetime(d["Date"]).iloc[::-1].iloc[:20]
    tot_s    = (total_oi / 1000).iloc[::-1].iloc[:20].values

    long_pct  = long_df.div(tot_s, axis=0) * 100
    short_pct = short_df.div(tot_s, axis=0) * 100

    combined = pd.concat([long_df[cats], short_df[cats], long_pct[cats], short_pct[cats]], axis=1)
    combined.columns = pd.MultiIndex.from_tuples(
        [("Longs · k lots",  c) for c in cats] +
        [("Shorts · k lots", c) for c in cats] +
        [("Long % OI",       c) for c in cats] +
        [("Short % OI",      c) for c in cats]
    )
    combined.index = [f"{dt.day}-{dt.strftime('%b-%y')}" for dt in idx]
    return combined




def _summary_and_body(cols_dict, d_index, n=20):
    body = pd.DataFrame(cols_dict)
    body.index = pd.to_datetime(d_index)
    body = body.iloc[::-1].iloc[:n]
    row_1w, row_4w = {}, {}
    for c in body.columns:
        if len(body) >= 2: row_1w[c] = body.iloc[0][c] - body.iloc[1][c]
        if len(body) >= 5: row_4w[c] = body.iloc[0][c] - body.iloc[4][c]
    summary = pd.DataFrame([row_1w, row_4w], index=["+/-1w", "+/-4w"], columns=body.columns)
    body.index = [f"{dt.day}-{dt.strftime('%b-%y')}" for dt in body.index]
    return summary, body


def _build_traders_df(d, report):
    d = d.sort_values("Date", ascending=True).reset_index(drop=True)
    if d.empty: return pd.DataFrame(), pd.DataFrame()
    def gc(name): return d[name].astype(float) if name in d.columns else pd.Series(0.0, index=d.index)

    if report == "CIT":
        cols = {
            ("# Traders", "Lrg Long"):  gc("Traders Spec Long"),
            ("# Traders", "Lrg Short"): gc("Traders Spec Short"),
            ("# Traders", "Idx Long"):  gc("Traders Index Long"),
            ("# Traders", "Idx Short"): gc("Traders Index Short"),
            ("# Traders", "Lrg Spread"):gc("Traders Spec Spread"),
            ("# Traders", "Comm Long"): gc("Traders Comm Long"),
            ("# Traders", "Comm Short"):gc("Traders Comm Short"),
        }
    else:
        cols = {
            ("# Traders", "MM Long"):    gc("Traders MM Long"),
            ("# Traders", "MM Short"):   gc("Traders MM Short"),
            ("# Traders", "MM Spread"):  gc("Traders MM Spread"),
            ("# Traders", "Swap Long"):  gc("Traders Swap Long"),
            ("# Traders", "Swap Short"): gc("Traders Swap Short"),
            ("# Traders", "Swap Spread"):gc("Traders Swap Spread"),
            ("# Traders", "Other Long"): gc("Traders Other Long"),
            ("# Traders", "Other Short"):gc("Traders Other Short"),
            ("# Traders", "Prod Long"):  gc("Traders Producer Long"),
            ("# Traders", "Prod Short"): gc("Traders Producer Short"),
        }
    return _summary_and_body(cols, d["Date"])


def _build_lots_per_trader_df(d, report):
    d = d.sort_values("Date", ascending=True).reset_index(drop=True)
    if d.empty: return pd.DataFrame(), pd.DataFrame()
    def gc(name): return d[name].astype(float) if name in d.columns else pd.Series(0.0, index=d.index)
    def safe_div(num, den): return num.where(den == 0, num / den.replace(0, np.nan))

    if report == "CIT":
        cols = {
            ("k lots / Trader", "Lrg Long"):  safe_div(gc("Spec Long")  / 1000, gc("Traders Spec Long")),
            ("k lots / Trader", "Lrg Short"): safe_div(gc("Spec Short") / 1000, gc("Traders Spec Short")),
            ("k lots / Trader", "Idx Long"):  safe_div(gc("Index Long") / 1000, gc("Traders Index Long")),
            ("k lots / Trader", "Idx Short"): safe_div(gc("Index Short")/ 1000, gc("Traders Index Short")),
            ("k lots / Trader", "Lrg Spread"):safe_div(gc("Spec Spread")/ 1000, gc("Traders Spec Spread")),
            ("k lots / Trader", "Comm Long"): safe_div(gc("Comm Long")  / 1000, gc("Traders Comm Long")),
            ("k lots / Trader", "Comm Short"):safe_div(gc("Comm Short") / 1000, gc("Traders Comm Short")),
        }
    else:
        cols = {
            ("k lots / Trader", "MM Long"):    safe_div(gc("MM Long")       / 1000, gc("Traders MM Long")),
            ("k lots / Trader", "MM Short"):   safe_div(gc("MM Short")      / 1000, gc("Traders MM Short")),
            ("k lots / Trader", "MM Spread"):  safe_div(gc("MM Spread")     / 1000, gc("Traders MM Spread")),
            ("k lots / Trader", "Swap Long"):  safe_div(gc("Swap Long")     / 1000, gc("Traders Swap Long")),
            ("k lots / Trader", "Swap Short"): safe_div(gc("Swap Short")    / 1000, gc("Traders Swap Short")),
            ("k lots / Trader", "Swap Spread"):safe_div(gc("Swap Spread")   / 1000, gc("Traders Swap Spread")),
            ("k lots / Trader", "Other Long"): safe_div(gc("Other Long")    / 1000, gc("Traders Other Long")),
            ("k lots / Trader", "Other Short"):safe_div(gc("Other Short")   / 1000, gc("Traders Other Short")),
            ("k lots / Trader", "Prod Long"):  safe_div(gc("Producer Long") / 1000, gc("Traders Producer Long")),
            ("k lots / Trader", "Prod Short"): safe_div(gc("Producer Short")/ 1000, gc("Traders Producer Short")),
        }
    return _summary_and_body(cols, d["Date"])


def render_recap(d, report, color, commodity="KC", is_options=False):
    if d.empty:
        st.warning("No data for the selected filters."); return

    summary, body = _build_recap_df(d, report)
    if body.empty:
        st.warning("No data."); return

    view = body.iloc[:20]

    _PX_PCT = set()   # no price column in the CFTC/ICE data

    with st.expander("Change summary  ·  k lots", expanded=True):
        st.markdown(_recap_html(summary,
                                signed_rows={"Δ 1w", "Δ 1m", "Z-Score"},
                                z_rows={"Z-Score"},
                                pct_subcols=_PX_PCT,
                                max_height=148), unsafe_allow_html=True)

    with st.expander("Historical positions  ·  k lots", expanded=True):
        st.markdown(_recap_html(view, scroll=True, pct_subcols=_PX_PCT), unsafe_allow_html=True)

    with st.expander("Weekly change  ·  k lots", expanded=True):
        chg = view.diff(-1)
        st.markdown(_recap_html(chg, signed=True, change_table=True, scroll=True, pct_subcols=_PX_PCT), unsafe_allow_html=True)

        # Stats of weekly changes over full selected period
        chg_full = body.diff(-1).dropna()
        if not chg_full.empty:
            rz, ra, rn, rx = {}, {}, {}, {}
            for c in chg_full.columns:
                s = chg_full[c].replace([np.inf, -np.inf], np.nan).dropna()
                if len(s) >= 4:
                    mu, sigma = s.mean(), s.std()
                    ra[c] = mu
                    rn[c] = s.min()
                    rx[c] = s.max()
                    if not chg.empty and c in chg.columns:
                        v = chg.iloc[0][c]
                        rz[c] = (v - mu) / sigma if pd.notna(v) and sigma > 0 else np.nan
            chg_stats = pd.DataFrame(
                [rz, ra, rn, rx],
                index=["Z-Score Δ", "Avg Δ", "Min Δ", "Max Δ"],
                columns=chg_full.columns,
            )
            st.markdown(
                "<p style='font-size:.72rem;color:#6e6e73;margin:10px 0 2px'>"
                "Weekly Δ stats  ·  selected period</p>",
                unsafe_allow_html=True,
            )
            st.markdown(_recap_html(chg_stats, signed=True, z_rows={"Z-Score Δ"}, pct_subcols=_PX_PCT), unsafe_allow_html=True)

    oi_tbl = _build_oi_df(d, report)
    with st.expander("OI by category  ·  k lots  &  %", expanded=False):
        st.markdown(_recap_html(oi_tbl, signed_groups={"Δ 1w"}, pct_groups={"OI %"}, scroll=True), unsafe_allow_html=True)

    gross_tbl = _build_gross_legs_df(d, report)
    with st.expander("Gross legs by category  ·  k lots  &  % OI", expanded=False):
        st.markdown(
            "<p style='font-size:.72rem;color:#6e6e73;margin:0 0 6px'>"
            "Long/Short include spreading positions. % columns are each leg divided by Total OI.</p>",
            unsafe_allow_html=True,
        )
        st.markdown(_recap_html(gross_tbl, pct_groups={"Long % OI", "Short % OI"}, scroll=True), unsafe_allow_html=True)


    tr_summary, tr_body = _build_traders_df(d, report)
    if not tr_body.empty:
        with st.expander("# of Traders", expanded=False):
            st.markdown(_recap_html(tr_summary, signed=True), unsafe_allow_html=True)
            st.markdown(_recap_html(tr_body, scroll=True), unsafe_allow_html=True)

    lpt_summary, lpt_body = _build_lots_per_trader_df(d, report)
    if not lpt_body.empty:
        with st.expander("k lots / Trader  (avg position size per trader)", expanded=False):
            st.markdown(_recap_html(lpt_summary, signed=True), unsafe_allow_html=True)
            st.markdown(_recap_html(lpt_body, scroll=True), unsafe_allow_html=True)

    if report == "CIT":
        guide = """
**Large Long / Large Short** — Non-Commercial

**Small Long / Small Short** — Non-Reportable

**L+S Long / L+S Short** — Large + Small gross (Non-Commercial + Non-Reportable)

**L+S+I Long / L+S+I Short** — Large + Small + Index gross (all ex-Commercial)

**Large+Small** — Non-Commercial Net + Non-Reportable Net (total non-index speculative net)

**Lrg+Sml+Idx** — Non-Commercial Net + Non-Reportable Net + Index Traders Net (everything ex-Commercial)
"""
    else:
        guide = """
**MM+O+NR Long/Short** — MM Long/Short + Other Long/Short + Non-Rep Long/Short (all speculative ex swap dealers)

**MM+O+NR Net** — MM Net + Other Net + Non-Rep Net (combined speculative ex-swap net)

**Rest (NET)** — Other Net + Non-Reportable Net combined
"""
    with st.expander("Column guide", expanded=False):
        st.markdown(guide)


# ── CIT vs Disagg crosswalk ───────────────────────────────────────────────────
CROSSWALK = {
    "Non-Comm vs Managed Money": {
        "cit_long":"Spec Long",    "cit_short":"Spec Short",    "cit_net":"Spec Net",
        "dag_long":"MM Long",      "dag_short":"MM Short",      "dag_net":"MM Net",
        "cit_label":"Non-Commercial (CIT)", "dag_label":"Managed Money (Disagg)",
        "desc":"",
    },
    "Index Traders vs Swap Dealers": {
        "cit_long":"Index Long",   "cit_short":"Index Short",   "cit_net":"Index Net",
        "dag_long":"Swap Long",    "dag_short":"Swap Short",    "dag_net":"Swap Net",
        "cit_label":"Index Traders (CIT)", "dag_label":"Swap Dealers (Disagg)",
        "desc":"",
    },
    "Commercial vs Producer/Merchant": {
        "cit_long":"Comm Long",     "cit_short":"Comm Short",     "cit_net":"Comm Net",
        "dag_long":"Producer Long", "dag_short":"Producer Short", "dag_net":"Comm Net",
        "cit_label":"CIT Commercial", "dag_label":"Producer/Merchant (Disagg)",
        "desc":"Physical hedgers — CIT Commercial includes swap-dealer activity that Disagg separates out.",
    },
    "CIT (NonComm + Index) vs Disagg (MM + Swap + Others)": {
        "cit_long":None, "cit_short":None, "cit_net":"Fin Net",
        "dag_long":None, "dag_short":None, "dag_net":"Fin Net",
        "cit_label":"CIT NonComm + Index", "dag_label":"Disagg MM + Swap + Other",
        "desc":"Total non-physical/financial side — CIT (NonComm+Index) vs Disagg (MM+Swap+Other).",
        "computed":True,
    },
}

CONC_COLS = ["Conc Gross 4 Long","Conc Gross 4 Short",
             "Conc Gross 8 Long","Conc Gross 8 Short",
             "Conc Net 4 Long","Conc Net 4 Short",
             "Conc Net 8 Long","Conc Net 8 Short"]

def render_concentration(d, color):
    avail = [c for c in CONC_COLS if c in d.columns]
    if not avail: st.info("No concentration data available."); return

    latest = d.iloc[-1]

    # Summary table
    st.markdown(f"**Latest — week of {pd.to_datetime(latest['Date']).strftime('%d %b %Y')}**")
    rows = {
        "":         ["4 Traders","8 Traders"],
        "Gross Long": [f"{latest.get('Conc Gross 4 Long',np.nan):.1f}%",
                       f"{latest.get('Conc Gross 8 Long',np.nan):.1f}%"],
        "Gross Short":[f"{latest.get('Conc Gross 4 Short',np.nan):.1f}%",
                       f"{latest.get('Conc Gross 8 Short',np.nan):.1f}%"],
        "Net Long":  [f"{latest.get('Conc Net 4 Long',np.nan):.1f}%",
                      f"{latest.get('Conc Net 8 Long',np.nan):.1f}%"],
        "Net Short": [f"{latest.get('Conc Net 4 Short',np.nan):.1f}%",
                      f"{latest.get('Conc Net 8 Short',np.nan):.1f}%"],
    }
    st.dataframe(pd.DataFrame(rows).set_index(""), width='content', height=130)
    st.markdown("")

    sel = st.multiselect("Series to chart", avail,
                         default=["Conc Gross 4 Long","Conc Gross 4 Short",
                                  "Conc Gross 8 Long","Conc Gross 8 Short"],
                         key="conc_sel")
    CONC_PALETTE = ["#1a56db","#dc2626","#1a56db","#dc2626",
                    "#7c3aed","#059669","#7c3aed","#059669"]
    CONC_DASH    = ["solid","solid","dash","dash","solid","solid","dash","dash"]

    if sel:
        fig = go.Figure()
        for i,col in enumerate(sel):
            fig.add_trace(go.Scatter(x=d["Date"], y=d[col],
                name=col.replace("Conc ",""),
                line=dict(color=CONC_PALETTE[i%8], width=2.0, dash=CONC_DASH[i%8]),
                hovertemplate=f"<b>%{{x|%d %b %Y}}</b><br>{col}: %{{y:.1f}}%<extra></extra>"))
        fig.update_layout(
            **_BASE, height=360,
            title=dict(text="Concentration — % of OI held by largest traders",
                       font=dict(size=12,color="#333"),x=0),
            margin=dict(l=50,r=20,t=42,b=70),
            legend=dict(orientation="h",y=-0.22,x=0.5,xanchor="center",font_size=10),
            xaxis=dict(**_ax(x=True),tickformat="%d %b '%y"),
            yaxis=dict(**_ax(),title_text="% of OI",title_font_size=10))
        st.plotly_chart(fig, width='stretch')

    show_table(d, avail, avail[:4], "Data table — Concentration ratios", scale=False)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — EXPOSURE (Nominal; VaR placeholder)
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# TAB 8 — SCATTER & CORRELATION
# ══════════════════════════════════════════════════════════════════════════════

    # scatter sections moved to dedicated Correlation tab (render_correlation)


# ══════════════════════════════════════════════════════════════════════════════
# CORRELATION TAB — Price vs Positioning, COT cross-scatter, 3D scatters
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# TAB 9 — CIT vs DISAGG COMPARISON
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# COMBINED COMMODITY RENDERER
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# SPEC PROXIMITY TAB — all commodities at once, sequential date table
# ══════════════════════════════════════════════════════════════════════════════


_DEFAULT_THRESH = {"KC": 2.0, "CC": 2.0, "SB": 5.0, "CT": 1.0,
                   "RC": 2.0, "LCC": 1.0, "LSU": 2.0}
_GRID_ROWS = [["KC", "RC", "SB"], ["CC", "LCC", "CT"], ["LSU", None, None]]








# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        "<div style='font-size:1.05rem;font-weight:700;color:#1a56db;"
        "margin-bottom:16px;letter-spacing:.01em'>CFTC DIRECT</div>",
        unsafe_allow_html=True)

    commodity = st.selectbox("Commodity", list(COMM_NAMES.keys()),
                             format_func=lambda x: COMM_NAMES[x], key="sb_commodity")
    color = COMM_COLORS[commodity]

    if commodity in CIT_COMMS:
        report = st.radio("Report", ["CIT","Disagg"], horizontal=True, key="rb_report")
    else:
        report = "Disagg"
        st.markdown("<div style='font-size:.73rem;color:#999;margin:-6px 0 8px'>"
                    f"{commodity} — Disaggregated only</div>", unsafe_allow_html=True)

    version_key = None
    if report == "Disagg":
        version = st.radio("Version", ["F&O combined","Fut only","Options only"], horizontal=True, key="rb_version")
        version_key = "F&O" if "F&O" in version else ("Opt" if "Options" in version else "Fut")

    st.markdown("---")
    st.markdown("<div style='font-size:.78rem;font-weight:600;color:#444;"
                "margin-bottom:6px'>Date range</div>", unsafe_allow_html=True)
    if report == "CIT":
        _cit_df = load_cit()
        _max_date = _cit_df.loc[_cit_df["Commodity"] == commodity, "Date"].max().date()
    else:
        _dag_df = load_disagg("F&O")
        _max_date = _dag_df.loc[_dag_df["Commodity"] == commodity, "Date"].max().date()
    _date_key_suffix = f"{commodity}_{report}"
    start_date = st.date_input("From", value=datetime.date(2020,1,1),
                               min_value=datetime.date(2006,1,1), max_value=_max_date,
                               key=f"dt_from_{_date_key_suffix}")
    end_date   = st.date_input("To",   value=_max_date,
                               min_value=datetime.date(2006,1,1), max_value=_max_date,
                               key=f"dt_to_{_date_key_suffix}")



# ══════════════════════════════════════════════════════════════════════════════
# LOAD + FILTER
# ══════════════════════════════════════════════════════════════════════════════
if report == "CIT":
    raw = load_cit()
    df_all_crops = None
    df = raw[
        (raw["Commodity"]==commodity) &
        (raw["Date"]>=pd.Timestamp(start_date)) &
        (raw["Date"]<=pd.Timestamp(end_date))
    ].sort_values("Date").reset_index(drop=True)
else:
    raw = load_options_only() if version_key == "Opt" else load_disagg(version_key)
    df_all_crops = raw[
        (raw["Commodity"]==commodity) &
        (raw["Date"]>=pd.Timestamp(start_date)) &
        (raw["Date"]<=pd.Timestamp(end_date))
    ].sort_values(["Crop","Date"]).reset_index(drop=True)
    df = df_all_crops[df_all_crops["Crop"]=="All"].sort_values("Date").reset_index(drop=True)

is_options = (report == "Disagg" and version_key == "Opt")


# ══════════════════════════════════════════════════════════════════════════════
# HEADER
# ══════════════════════════════════════════════════════════════════════════════
ver_lbl = "" if report=="CIT" else f" — {version}"
st.markdown(
    f"<div style='display:flex;align-items:center;gap:12px;margin-bottom:4px'>"
    f"<div style='width:5px;height:38px;background:{color};border-radius:3px'></div>"
    f"<div>"
    f"<div style='font-size:1.2rem;font-weight:700;color:{color}'>{COMM_NAMES[commodity]}</div>"
    f"<div style='font-size:.73rem;color:#888'>{report}{ver_lbl} &nbsp;·&nbsp; "
    f"{start_date.strftime('%d %b %Y')} → {end_date.strftime('%d %b %Y')}</div>"
    f"</div></div>", unsafe_allow_html=True)
st.markdown("---")

if df.empty:
    st.warning("No data for the selected filters."); st.stop()


# ══════════════════════════════════════════════════════════════════════════════
# TAB — RECAP (CHARTS)
# ══════════════════════════════════════════════════════════════════════════════
def render_recap_charts(d, report, color, commodity):
    if d.empty:
        st.warning("No data for the selected filters."); return

    d   = d.sort_values("Date").reset_index(drop=True)
    dates = pd.to_datetime(d["Date"])

    def gc(name):
        return d[name].astype(float) if name in d.columns else pd.Series(np.nan, index=d.index)

    # Nominal/price multipliers removed: CFTC and ICE publish positions only.
    oi   = gc("Total OI").replace(0, np.nan)

    def _line(title, series_dict, clrs=None):
        dflt = [C_LONG, C_SHORT, C_NET, "#f59e0b", "#7c3aed"]
        if clrs is None: clrs = dflt
        fig = go.Figure()
        fig.update_layout(
            **_BASE,
            title=dict(text=f"{commodity} — {title}", font=dict(size=10, color="#374151")),
            height=260,
            margin=dict(l=40, r=8, t=36, b=48),
            showlegend=True,
            legend=dict(orientation="h", y=-0.28, font=dict(size=9)),
            xaxis=dict(**_ax(x=True)),
            yaxis=dict(**_ax()),
        )
        for i, (name, y) in enumerate(series_dict.items()):
            fig.add_trace(go.Scatter(
                x=dates, y=y, name=name,
                line=dict(color=clrs[i % len(clrs)], width=1.5)
            ))
        return fig

    # Same column shape for both report types (3 cols x 4 rows) so Streamlit's
    # layout tree stays consistent across reruns when toggling CIT/Disagg —
    # mismatched container shapes cause stale charts to flash during rerender.
    c1, c2, c3    = st.columns(3)
    c4, c5, c6    = st.columns(3)
    c7, c8, c9    = st.columns(3)
    c10, c11, c12 = st.columns(3)

    if report == "CIT":
        large_net = gc("Spec Net")       # Large Spec only (Spec Long - Spec Short)
        small_net = gc("Non Rep Net")    # Small Spec / non-reportables only
        spec_net  = large_net + small_net.fillna(0)  # Net Spec = Large + Small (classic COT convention)
        idx_net   = gc("Index Net")

        # Col 1 — Net positioning. Title spells out the composition.
        with c1:
            st.plotly_chart(_line(
                "Net Spec (Large + Small) & Net Index k lots",
                {"Net Spec": spec_net / 1000, "Net Index": idx_net / 1000},
                [C_NET, C_LONG]
            ), width='stretch')

        # Col 2 — Large Net vs Small Net breakdown, right beside it, so the
        # "Net Spec = Large + Small" composition is visible at a glance.
        with c2:
            st.plotly_chart(_line(
                "Large Net & Small Net k lots",
                {"Large Net": large_net / 1000, "Small Net": small_net / 1000},
                ["#93c5fd", "#c4b5fd"]
            ), width='stretch')

        # Col 9 (was empty in CIT layout) — Spec gross k lots, moved here
        # to make room for the Large/Small breakdown chart above in c2.
        with c9:
            st.plotly_chart(_line(
                "Spec Gross k lots",
                {"Large Long": gc("Spec Long") / 1000, "Large Short": gc("Spec Short") / 1000},
                [C_LONG, C_SHORT]
            ), width='stretch')

        # Col 3 — Spec gross % of OI
        with c3:
            st.plotly_chart(_line(
                "Spec Gross % of OI",
                {"Lrg+Sml Long %":  (gc("Spec Long")  + gc("Non Rep Long"))  / oi * 100,
                 "Lrg+Sml Short %": (gc("Spec Short") + gc("Non Rep Short")) / oi * 100},
                [C_LONG, C_SHORT]
            ), width='stretch')


        # Col 1 bottom — # of Traders
        with c5:
            st.plotly_chart(_line(
                "# of Traders",
                {"Large Long": gc("Traders Spec Long"), "Large Short": gc("Traders Spec Short")},
                [C_LONG, C_SHORT]
            ), width='stretch')

        # Col 2 bottom — Commercial gross k lots
        with c6:
            st.plotly_chart(_line(
                "Commercial Gross k lots",
                {"Comm Long": gc("Comm Long") / 1000, "Comm Short": gc("Comm Short") / 1000},
                [C_LONG, C_SHORT]
            ), width='stretch')

        # Col 3 bottom — Commercial % of OI
        with c7:
            st.plotly_chart(_line(
                "Commercial Gross % of OI",
                {"Comm Long %":  gc("Comm Long")  / oi * 100,
                 "Comm Short %": gc("Comm Short") / oi * 100},
                [C_LONG, C_SHORT]
            ), width='stretch')


    else:  # Disagg
        mm_net   = gc("MM Net")
        swap_net = gc("Swap Net")

        # Row 1 — MM
        with c1:
            st.plotly_chart(_line(
                "MM Gross k lots",
                {"MM Long": gc("MM Long") / 1000, "MM Short": gc("MM Short") / 1000},
                [C_LONG, C_SHORT]
            ), width='stretch')

        with c2:
            st.plotly_chart(_line(
                "MM Gross % of OI",
                {"MM Long %":  gc("MM Long")  / oi * 100,
                 "MM Short %": gc("MM Short") / oi * 100},
                [C_LONG, C_SHORT]
            ), width='stretch')


        # Row 2 — Commercial
        with c4:
            st.plotly_chart(_line(
                "Commercial Gross k lots",
                {"Prod Long": gc("Producer Long") / 1000, "Prod Short": gc("Producer Short") / 1000},
                [C_LONG, C_SHORT]
            ), width='stretch')

        with c5:
            st.plotly_chart(_line(
                "Commercial Gross % of OI",
                {"Prod Long %":  gc("Producer Long")  / oi * 100,
                 "Prod Short %": gc("Producer Short") / oi * 100},
                [C_LONG, C_SHORT]
            ), width='stretch')


        # Row 3 — Other Reportables
        with c7:
            st.plotly_chart(_line(
                "Other Gross k lots",
                {"Other Long": gc("Other Long") / 1000, "Other Short": gc("Other Short") / 1000},
                [C_LONG, C_SHORT]
            ), width='stretch')

        with c8:
            st.plotly_chart(_line(
                "Other Gross % of OI",
                {"Other Long %":  gc("Other Long")  / oi * 100,
                 "Other Short %": gc("Other Short") / oi * 100},
                [C_LONG, C_SHORT]
            ), width='stretch')


        # Row 4 — Cross-category
        with c10:
            st.plotly_chart(_line(
                "MM Net & Swap Net & Other Net k lots",
                {"MM Net": mm_net / 1000, "Swap Net": swap_net / 1000, "Other Net": gc("Other Net") / 1000},
                [C_NET, C_LONG, "#f59e0b"]
            ), width='stretch')

        with c11:
            st.plotly_chart(_line(
                "# of Traders",
                {"MM Long": gc("Traders MM Long"), "MM Short": gc("Traders MM Short"),
                 "Other Long": gc("Traders Other Long"), "Other Short": gc("Traders Other Short")},
                [C_LONG, C_SHORT, "#f59e0b", "#7c3aed"]
            ), width='stretch')

        with c12:
            st.plotly_chart(_line(
                "Other Spread k lots",
                {"Other Spread": gc("Other Spread") / 1000},
                ["#f59e0b"]
            ), width='stretch')







# Fragment wrappers — each tab only reruns itself when its own widgets change,
# preventing the full-page rerun that scrolls back to the top.
@st.fragment
def _tab_recap(d, report, color, commodity, is_options=False):
    render_recap(d, report, color, commodity, is_options)

@st.fragment
def _tab_recap_charts(d, report, color, commodity):
    render_recap_charts(d, report, color, commodity)




@st.fragment
def _tab_old_new(d_crops, color, commodity=""):
    render_old_new(d_crops, color, commodity)

@st.fragment
def _tab_concentration(d, color):
    render_concentration(d, color)








def _na(msg):
    st.markdown(
        f"<div style='margin-top:24px;font-size:.83rem;color:#6b7280;"
        f"padding:12px 16px;background:#f9fafb;border:1px solid #e5e7eb;"
        f"border-radius:8px'>{msg}</div>",
        unsafe_allow_html=True)


# Fixed tab count — Streamlit preserves the active tab when sidebar filters change.
tabs = st.tabs(["Recap", "Recap (Charts)", "Concentration", "Old / New"])

with tabs[0]:  _tab_recap(df, report, color, commodity, is_options)
with tabs[1]:  _tab_recap_charts(df, report, color, commodity)

with tabs[2]:  # Concentration
    if report == "CIT":
        _na("Concentration data is only available in the Disaggregated report.")
    else:
        _tab_concentration(df, color)

with tabs[3]:  # Old / New
    if report == "CIT":
        _na("Old / New crop split is only available in the Disaggregated report.")
    elif commodity in ICE_COMMS:
        _na("Old / New crop split is not published by ICE for the London softs. "
            "ICE reports a single all-crop series for RC, LCC and LSU.")
    elif df_all_crops is not None:
        _tab_old_new(df_all_crops, color, commodity)
    else:
        _na("Old / New crop split is not available for this commodity.")
