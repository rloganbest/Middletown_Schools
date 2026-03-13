"""
NJ School Finance Explorer — Streamlit dashboard
-------------------------------------------------
Run from project root:
    streamlit run app/tges_dashboard.py
"""
from __future__ import annotations
import warnings
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

warnings.filterwarnings("ignore")

# ── Project root ──────────────────────────────────────────────────────────────

def _find_project_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(6):
        if (candidate / "data" / "TGES").is_dir():
            return candidate
        candidate = candidate.parent
    raise FileNotFoundError("Could not locate data/TGES/")

PROJECT_ROOT = _find_project_root()
TGES_ROOT    = PROJECT_ROOT / "data" / "TGES"
YEARS        = list(range(2011, 2026))
NULL_VALS    = {"N.A.", "N.R.", "", "N/A", "NA"}

# ── Indicator catalogs ────────────────────────────────────────────────────────
# Tuples: (csv_file, value_col, label, fmt, y_label, scale)
# scale: multiply raw value × scale for display (100 for stored-as-decimal pct)

SPENDING_INDICATORS = [
    ("CSG1.CSV",  "PP11",  "Budgetary Per-Pupil Cost",             "$",     "Per-pupil cost ($)", 1),
    ("CSG2.CSV",  "PP12",  "Classroom Instruction",                "$",     "Per-pupil cost ($)", 1),
    ("CSG6.CSV",  "PP16",  "Support Services",                     "$",     "Per-pupil cost ($)", 1),
    ("CSG8.CSV",  "PP18",  "Total Administration",                 "$",     "Per-pupil cost ($)", 1),
    ("CSG10.CSV", "PP110", "Operations & Maintenance",             "$",     "Per-pupil cost ($)", 1),
    ("CSG13.CSV", "PP113", "Extracurricular Costs",                "$",     "Per-pupil cost ($)", 1),
    ("CSG15.CSV", "PP115", "Equipment Costs",                      "$",     "Per-pupil cost ($)", 1),
]

RATIO_INDICATORS = [
    ("CSG16.CSV", "STRAT0016", "Student:Teacher Ratio",      "ratio", "Students per teacher",       1),
    ("CSG17.CSV", "SSRAT0017", "Student:Support Staff Ratio","ratio", "Students per support staff", 1),
    ("CSG18.CSV", "SARAT0018", "Student:Admin Ratio",        "ratio", "Students per administrator", 1),
    ("CSG19.CSV", "FARAT0019", "Faculty:Admin Ratio",        "ratio", "Faculty per administrator",  1),
]

SALARY_INDICATORS = [
    ("CSG16.CSV", "SALT0016",  "Median Teacher Salary",          "salary", "Median salary ($)", 1),
    ("CSG17.CSV", "SALS0017",  "Median Support Staff Salary",    "salary", "Median salary ($)", 1),
    ("CSG18.CSV", "SALAM0018", "Median Admin Salary",            "salary", "Median salary ($)", 1),
]

FUND_INDICATORS = [
    ("CSG20.CSV", "DE120",  "Budgeted Drawdown — Y1",     "$", "Total $", 1),
    ("CSG20.CSV", "DE220",  "Actual Change — Y1",         "$", "Total $", 1),
    ("CSG20.CSV", "DE320",  "Budgeted Drawdown — Y2",     "$", "Total $", 1),
    ("CSG20.CSV", "DE420",  "Actual Change — Y2",         "$", "Total $", 1),
    ("CSG21.CSV", "EX121",  "Excess Surplus — Y1",        "$", "Total $", 1),
    ("CSG21.CSV", "EX221",  "Excess Surplus — Y2",        "$", "Total $", 1),
]

VITSTAT_INDICATORS = [
    ("VITSTAT_TOTAL.CSV", "pctsevv", "% Students in Special Ed", "pct", "% of Enrollment", 100),
    ("VITSTAT_TOTAL.CSV", "pp3vv",   "Total Spending Per Pupil", "$",   "Per-pupil ($)",    1),
]

# Revenue section — Total PP + three revenue splits
REVENUE_INDICATORS = [
    ("VITSTAT_TOTAL.CSV", "pp3vv",     "Total Spending Per Pupil", "$",   "Per-pupil ($)",  1),
    ("VITSTAT_TOTAL.CSV", "stpct01vv", "State Revenue %",          "pct", "% of Revenue", 100),
    ("VITSTAT_TOTAL.CSV", "ltpct01vv", "Local Revenue %",          "pct", "% of Revenue", 100),
    ("VITSTAT_TOTAL.CSV", "fdpct01vv", "Federal Revenue %",        "pct", "% of Revenue", 100),
]
REVENUE_CHART_INDICATORS = [i for i in REVENUE_INDICATORS if i[3] == "pct"]  # chartable %

# All sub-components used for breakdown tables / sub-col loading
ALL_INDICATORS_MAP: dict[str, tuple] = {
    i[2]: i for i in [
        ("CSG1.CSV",  "PP11",   "Budgetary Per-Pupil Cost",       "$", 1),
        ("CSG2.CSV",  "PP12",   "Classroom Instruction Total",    "$", 1),
        ("CSG3.CSV",  "PP13",   "Classroom Salaries & Benefits",  "$", 1),
        ("CSG4.CSV",  "PP14",   "Classroom Supplies/Textbooks",   "$", 1),
        ("CSG5.CSV",  "PP15",   "Classroom Purchased Services",   "$", 1),
        ("CSG6.CSV",  "PP16",   "Support Services Total",         "$", 1),
        ("CSG7.CSV",  "PP17",   "Support Salaries & Benefits",    "$", 1),
        ("CSG8.CSV",  "PP18",   "Total Administration",           "$", 1),
        ("CSG8A.CSV", "PP18A",  "Legal Services",                 "$", 1),
        ("CSG9.CSV",  "PP19",   "Admin Salaries & Benefits",      "$", 1),
        ("CSG10.CSV", "PP110",  "Operations & Maintenance Total", "$", 1),
        ("CSG11.CSV", "PP111",  "O&M Salaries & Benefits",        "$", 1),
        ("CSG12.CSV", "PP112",  "Food Service Contribution",      "$", 1),
        ("CSG13.CSV", "PP113",  "Extracurricular Costs",          "$", 1),
        ("CSG15.CSV", "PP115",  "Equipment Costs",                "$", 1),
    ]
}

BREAKDOWN_MAP: dict[str, list[str]] = {
    # First item is always the parent total (bold header row, pct = 100%)
    "Budgetary Per-Pupil Cost": [
        "Budgetary Per-Pupil Cost",
        "Classroom Instruction Total", "Support Services Total",
        "Total Administration", "Operations & Maintenance Total",
        "Food Service Contribution", "Extracurricular Costs", "Equipment Costs",
    ],
    "Classroom Instruction":    ["Classroom Instruction Total", "Classroom Salaries & Benefits",
                                  "Classroom Supplies/Textbooks", "Classroom Purchased Services"],
    "Support Services":         ["Support Services Total", "Support Salaries & Benefits"],
    "Total Administration":     ["Total Administration", "Legal Services", "Admin Salaries & Benefits"],
    "Operations & Maintenance": ["Operations & Maintenance Total", "O&M Salaries & Benefits"],
}

SPENDING_CATEGORIES = {
    "All":               [i[2] for i in SPENDING_INDICATORS],
    "💰 Overall":        ["Budgetary Per-Pupil Cost"],
    "📚 Classroom":      ["Classroom Instruction"],
    "🤝 Support":        ["Support Services"],
    "🏛 Administration": ["Total Administration"],
    "🏗 Operations":     ["Operations & Maintenance"],
    "🎭 Other":          ["Extracurricular Costs", "Equipment Costs"],
}

# ── Data helpers ──────────────────────────────────────────────────────────────

def get_csv_dir(year: int) -> Path | None:
    base = TGES_ROOT / str(year) / "extracted"
    if not base.is_dir():
        return None
    for d in base.iterdir():
        if d.is_dir() and (d / "CSG1.CSV").exists():
            return d
    return None

def clean_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.strip().replace(list(NULL_VALS), None),
        errors="coerce")

def _read_csv(csv_dir: Path, fname: str) -> pd.DataFrame | None:
    match = next((f for f in csv_dir.iterdir() if f.name.upper() == fname.upper()), None)
    if match is None:
        return None
    df = pd.read_csv(match, encoding="latin-1", dtype=str)
    df.columns = df.columns.str.upper().str.strip()
    df["DISTNAME"] = df["DISTNAME"].str.strip().str.title()
    return df

# ── Cached data loaders ───────────────────────────────────────────────────────

@st.cache_data(show_spinner="Loading district roster…")
def load_roster() -> pd.DataFrame:
    csv_dir = get_csv_dir(2025)
    df = _read_csv(csv_dir, "CSG1.CSV")
    real = df[pd.to_numeric(df["DIST"], errors="coerce").notna()].copy()
    return (
        real[["DISTNAME", "CONAME", "GROUP"]]
        .rename(columns={"DISTNAME": "distname", "CONAME": "county", "GROUP": "group"})
        .drop_duplicates("distname").sort_values("distname").reset_index(drop=True)
    )

@st.cache_data(show_spinner="Computing peer statistics…")
def build_stats(peer_group: str, fname: str, col: str, scale: float = 1) -> pd.DataFrame:
    rows = []
    for year in YEARS:
        csv_dir = get_csv_dir(year)
        if csv_dir is None:
            continue
        df = _read_csv(csv_dir, fname)
        if df is None:
            continue
        col_u = col.upper()
        if col_u not in df.columns:
            continue
        df["_v"] = clean_num(df[col_u]) * scale
        grp  = df[df["GROUP"].str.strip() == peer_group].copy()
        real = grp[pd.to_numeric(grp["DIST"], errors="coerce").notna()].copy()
        peer_vals = real["_v"].dropna()
        if len(peer_vals) < 5:
            continue
        p25, p50, p75 = peer_vals.quantile([0.25, 0.50, 0.75]).values
        peer_distnames = set(real["DISTNAME"].tolist())
        all_vals = (
            df[pd.to_numeric(df["DIST"], errors="coerce").notna()]
            .dropna(subset=["_v"])
            .set_index("DISTNAME")["_v"]
            .to_dict()
        )
        rows.append(dict(
            year=year, n=len(peer_vals),
            mean=peer_vals.mean(), std=peer_vals.std(ddof=1),
            p25=p25, p50=p50, p75=p75,
            max_val=peer_vals.max(), min_val=peer_vals.min(),
            peer_distnames=peer_distnames, all_vals=all_vals,
        ))
    return pd.DataFrame(rows).set_index("year") if rows else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_multi_col_table(year: int, col_defs: list[tuple], peer_group: str) -> pd.DataFrame:
    """
    Load multiple value columns for all peer districts in one table.
    col_defs: list of (fname, col, label, fmt, y_label, scale)
    Returns DataFrame indexed by DISTNAME with one column per indicator.
    """
    csv_dir = get_csv_dir(year)
    if csv_dir is None:
        return pd.DataFrame()
    frames = {}
    for fname, col, label, fmt, y_label, scale in col_defs:
        df = _read_csv(csv_dir, fname)
        if df is None:
            continue
        col_u = col.upper()
        if col_u not in df.columns:
            continue
        grp  = df[df["GROUP"].str.strip() == peer_group]
        real = grp[pd.to_numeric(grp["DIST"], errors="coerce").notna()].copy()
        real["_v"] = clean_num(real[col_u]) * scale
        # Drop duplicate district names (keep first) before indexing
        frames[label] = (real.drop_duplicates("DISTNAME")
                             .set_index("DISTNAME")["_v"])
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames)


@st.cache_data(show_spinner=False)
def load_breakdown(year: int, child_labels: list[str],
                   district: str, peer_group: str) -> pd.DataFrame:
    csv_dir = get_csv_dir(year)
    if csv_dir is None:
        return pd.DataFrame()
    records = []
    for label in child_labels:
        entry = ALL_INDICATORS_MAP.get(label)
        if not entry:
            continue
        fname, col = entry[0], entry[1]
        df = _read_csv(csv_dir, fname)
        if df is None:
            continue
        col_u = col.upper()
        if col_u not in df.columns:
            continue
        def fv(mask):
            sub = df[mask]
            if sub.empty:
                return None
            try: return float(sub.iloc[0][col_u])
            except: return None
        dist_val  = fv(df["DISTNAME"] == district.strip().title())
        grp       = df[df["GROUP"].str.strip() == peer_group]
        real      = grp[pd.to_numeric(grp["DIST"], errors="coerce").notna()].copy()
        peer_vals = pd.to_numeric(real[col_u].replace(list(NULL_VALS), None),
                                  errors="coerce").dropna()
        peer_med  = peer_vals.median() if len(peer_vals) > 0 else None
        records.append({"label": label, "dist_val": dist_val, "peer_med": peer_med})
    if not records:
        return pd.DataFrame()
    result = pd.DataFrame(records)
    total = result.iloc[0]["dist_val"]
    result["pct"] = result["dist_val"].apply(
        lambda v: v / total * 100 if (v is not None and total) else None)
    return result


@st.cache_data(show_spinner=False)
def load_subcomponent_cols(year: int, child_labels: list[str], peer_group: str) -> pd.DataFrame:
    csv_dir = get_csv_dir(year)
    if csv_dir is None:
        return pd.DataFrame()
    frames = {}
    for label in child_labels:
        entry = ALL_INDICATORS_MAP.get(label)
        if not entry:
            continue
        fname, col = entry[0], entry[1]
        df = _read_csv(csv_dir, fname)
        if df is None:
            continue
        col_u = col.upper()
        if col_u not in df.columns:
            continue
        real = df[pd.to_numeric(df["DIST"], errors="coerce").notna()].copy()
        real["_v"] = pd.to_numeric(real[col_u].replace(list(NULL_VALS), None), errors="coerce")
        frames[label] = (real.drop_duplicates("DISTNAME")
                             .set_index("DISTNAME")["_v"])
    return pd.DataFrame(frames) if frames else pd.DataFrame()

# ── Chart helpers ─────────────────────────────────────────────────────────────

OVERLAY_COLORS = [
    "#E63946", "#6A4C93", "#F4A261", "#2A9D8F",
    "#E9C46A", "#264653", "#E76F51", "#457B9D",
]

def fmt_val(v, fmt: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    if fmt in ("$", "salary"):
        return f"${v:,.0f}"
    if fmt == "pct":
        return f"{v:.1f}%"
    return f"{v:.2f}"

def _y_range(stats_df: pd.DataFrame, primary_series: pd.Series) -> list[float]:
    p75_max = stats_df["p75"].max()
    fence   = p75_max + 8 * stats_df["std"].mean()
    mt_max  = primary_series.max(skipna=True)
    y_max   = max(fence, mt_max if pd.notna(mt_max) else 0) * 1.10
    return [0, y_max]

def extract_district_series(stats_df: pd.DataFrame, name: str) -> pd.Series:
    return pd.Series(
        {yr: row["all_vals"].get(name) for yr, row in stats_df.iterrows()},
        dtype=float)

def make_chart(stats_df, primary_name, compare_names, fmt, y_label, title,
               height=600) -> go.Figure:
    if stats_df.empty:
        return go.Figure().update_layout(title="No data available")

    years  = stats_df.index.values
    p25    = stats_df["p25"].values
    p75    = stats_df["p75"].values
    p50    = stats_df["p50"].values
    ns     = stats_df["n"].values

    primary_series = extract_district_series(stats_df, primary_name)
    all_series     = {d: extract_district_series(stats_df, d)
                      for d in [primary_name] + compare_names}

    pctile_ranks = {}
    for yr, row in stats_df.iterrows():
        mv       = primary_series.get(yr)
        peer_dn  = row.get("peer_distnames", set())
        # Use peer group only — same population as the IQR bands
        peers    = [v for k, v in row["all_vals"].items()
                    if k != primary_name and k in peer_dn]
        if mv is not None and not pd.isna(mv) and peers:
            pctile_ranks[yr] = sum(v < mv for v in peers) / len(peers) * 100

    fig = go.Figure()

    # IQR band
    fig.add_trace(go.Scatter(x=years, y=p75, mode="lines",
                             line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=years, y=p25, mode="lines",
                             line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(66,165,245,0.22)",
                             name="Middle 50% of peers (IQR)",
                             legendgroup="band", hoverinfo="skip"))

    # Peer median
    fig.add_trace(go.Scatter(
        x=years, y=p50, mode="lines",
        line=dict(color="#457B9D", width=1.5, dash="dot"),
        name="Peer median",
        hovertemplate="<b>%{x}</b><br>Peer median: %{text}<extra>Peer median</extra>",
        text=[fmt_val(v, fmt) for v in p50]))

    # Comparison districts
    for i, name in enumerate(compare_names):
        vals  = [all_series[name].get(yr) for yr in years]
        color = OVERLAY_COLORS[(i + 1) % len(OVERLAY_COLORS)]
        fig.add_trace(go.Scatter(
            x=years, y=vals, mode="lines+markers",
            line=dict(color=color, width=2, dash="dashdot"),
            marker=dict(size=7, color=color, symbol="diamond",
                        line=dict(color="white", width=1)),
            name=name,
            hovertemplate=f"<b>%{{x}}</b><br>{name}: %{{text}}<extra>{name}</extra>",
            text=[fmt_val(v, fmt) for v in vals]))

    # Primary district
    pv      = [primary_series.get(yr) for yr in years]
    pr_vals = [pctile_ranks.get(yr) for yr in years]
    labels  = [f"{p:.0f}%" if p is not None else "" for p in pr_vals]
    hover   = []
    for yr, v, p in zip(years, pv, pr_vals):
        if v is None or pd.isna(v):
            hover.append("N/A"); continue
        if p is not None:
            if   p <  10: p_desc = f"{p:.0f}th pctile  (bottom 10%)"
            elif p <  25: p_desc = f"{p:.0f}th pctile  (below IQR)"
            elif p <= 75: p_desc = f"{p:.0f}th pctile  (within IQR)"
            elif p <= 90: p_desc = f"{p:.0f}th pctile  (above IQR)"
            else:         p_desc = f"{p:.0f}th pctile  (top 10%)"
        else:
            p_desc = ""
        hover.append(f"{fmt_val(v, fmt)}<br>{p_desc}<br>vs {ns[list(years).index(yr)]} peers")

    dot_colors = [
        "#E63946" if (p is not None and 25 <= p <= 75)
        else "#E97D23" if (p is not None and 10 <= p <= 90)
        else "#9B1D1D" for p in pr_vals]

    fig.add_trace(go.Scatter(
        x=years, y=pv, mode="lines+markers+text",
        line=dict(color="#E63946", width=2.5),
        marker=dict(size=9, color=dot_colors, line=dict(color="white", width=1.5)),
        text=labels, textposition="top center",
        textfont=dict(size=10, color="#333"),
        name=primary_name,
        hovertemplate="<b>%{x}</b><br>" + primary_name + ": %{customdata}<extra>" + primary_name + "</extra>",
        customdata=hover))

    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color="#1A1A2E"), x=0, y=0.98,
                   xanchor="left", yanchor="top"),
        xaxis=dict(title="School Year", dtick=1, gridcolor="#eee", tickangle=-45),
        yaxis=dict(
            title=y_label, gridcolor="#eee",
            tickprefix="$" if fmt in ("$", "salary") else "",
            ticksuffix="%" if fmt == "pct" else "",
            tickformat="," if fmt in ("$", "salary") else ".1f",
            autorange=True),
        plot_bgcolor="white", paper_bgcolor="white",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.18,
                    xanchor="left", x=0, font=dict(size=11),
                    bgcolor="rgba(255,255,255,0.8)"),
        height=height, margin=dict(t=60, b=160, l=70, r=70))
    return fig


def make_ranking_table(stats_df, highlight_districts, fmt, value_label="Value",
                       year=2025, county_filter=None, roster=None,
                       peers_only=True, subcols_df=None) -> pd.DataFrame:
    if stats_df.empty or year not in stats_df.index:
        return pd.DataFrame()
    row           = stats_df.loc[year]
    highlight_set = set(highlight_districts)
    peer_set      = row.get("peer_distnames", set())

    county_set: set[str] = set()
    if county_filter and roster is not None:
        county_set = set(roster[roster["county"].isin(county_filter)]["distname"].tolist())

    records = []
    for dist, val in row["all_vals"].items():
        if val is None or pd.isna(val):
            continue
        is_hl = dist in highlight_set
        if peers_only and dist not in peer_set and not is_hl:
            continue
        if county_filter and not is_hl and dist not in county_set:
            continue
        records.append({"distname": dist, "value": val})
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).sort_values("value").reset_index(drop=True)
    df["Rank"]     = df.index + 1
    df["District"] = df["distname"].apply(lambda d: f"★ {d}" if d in highlight_set else d)
    df[value_label] = df["value"].apply(lambda v: fmt_val(v, fmt))

    if subcols_df is not None and not subcols_df.empty:
        # Drop any sub-column that would collide with the main value column
        safe_subcols = subcols_df.drop(
            columns=[c for c in subcols_df.columns if c == value_label],
            errors="ignore",
        )
        if not safe_subcols.empty:
            df = df.join(safe_subcols, on="distname", how="left")
            for col in safe_subcols.columns:
                df[col] = df[col].apply(lambda v: fmt_val(v, fmt))

    base_cols  = ["Rank", "District", value_label]
    extra_cols = [c for c in df.columns if c not in base_cols + ["distname", "value"]]
    return df[base_cols + extra_cols].reset_index(drop=True)


def make_multi_col_ranking_table(multi_df, highlight_districts, fmt_map,
                                 sort_col, county_filter=None, roster=None,
                                 peers_only=True, peer_distnames=None) -> pd.DataFrame:
    """
    Multi-column ranking table: one column per indicator, ranked by sort_col.
    Returns NUMERIC values for data columns so Streamlit can sort them correctly.
    Use build_col_config(fmt_map) to get the matching column_config for st.dataframe().
    """
    if multi_df.empty or sort_col not in multi_df.columns:
        return pd.DataFrame()

    highlight_set = set(highlight_districts)
    peer_set      = peer_distnames or set()
    county_set: set[str] = set()
    if county_filter and roster is not None:
        county_set = set(roster[roster["county"].isin(county_filter)]["distname"].tolist())

    df = multi_df.reset_index().rename(columns={"DISTNAME": "distname",
                                                  "index": "distname"})
    if "distname" not in df.columns:
        df = df.reset_index().rename(columns={"index": "distname"})

    df = df.dropna(subset=[sort_col]).copy()

    mask = pd.Series([True] * len(df), index=df.index)
    if peers_only and peer_set:
        mask &= df["distname"].isin(peer_set) | df["distname"].isin(highlight_set)
    if county_filter and county_set:
        mask &= df["distname"].isin(county_set) | df["distname"].isin(highlight_set)
    df = df[mask].sort_values(sort_col).reset_index(drop=True)

    df["Rank"]     = df.index + 1
    df["District"] = df["distname"].apply(lambda d: f"★ {d}" if d in highlight_set else d)

    result = df[["Rank", "District"]].copy()
    for col in multi_df.columns:
        result[col] = pd.to_numeric(df[col], errors="coerce")  # keep numeric

    return result.reset_index(drop=True)


def build_col_config(fmt_map: dict) -> dict:
    """Build st.column_config entries so numeric columns display with correct format."""
    cfg = {}
    for col, fmt in fmt_map.items():
        if fmt in ("$", "salary"):
            cfg[col] = st.column_config.NumberColumn(col, format="$%,.0f")
        elif fmt == "pct":
            cfg[col] = st.column_config.NumberColumn(col, format="%.1f%%")
        else:
            cfg[col] = st.column_config.NumberColumn(col, format="%.2f")
    return cfg


# ── Streamlit App ─────────────────────────────────────────────────────────────

st.set_page_config(page_title="NJ School Finance Explorer", page_icon="🏫",
                   layout="wide", initial_sidebar_state="expanded")
st.title("🏫 NJ School Finance Explorer")
st.caption(
    "Source: NJ Department of Education — Taxpayers' Guide to Education Spending (TGES), 2011–2025.  "
    "Shaded band = middle 50% of peer districts (IQR). "
    "Labels on each dot = that year's percentile rank within the peer group.")

roster = load_roster()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📍 Primary District")
    all_districts    = sorted(roster["distname"].tolist())
    default_dist_idx = all_districts.index("Middletown Twp") if "Middletown Twp" in all_districts else 0
    primary_district = st.selectbox("Search district", all_districts, index=default_dist_idx)

    peer_group_row = roster[roster["distname"] == primary_district]
    peer_group     = peer_group_row["group"].iloc[0] if not peer_group_row.empty else "G. K-12 / 3501 +"
    st.caption(f"Peer group: **{peer_group}**")

    st.divider()
    st.header("📊 Compare With")
    peers_only   = st.toggle("Peers only", value=True)
    counties_list = sorted(roster["county"].unique().tolist())
    comp_counties = st.multiselect("Filter by county (optional)", counties_list, key="comp_counties")
    comp_roster   = roster.copy()
    if peers_only:
        comp_roster = comp_roster[comp_roster["group"] == peer_group]
    if comp_counties:
        comp_roster = comp_roster[comp_roster["county"].isin(comp_counties)]
    comp_options      = sorted([d for d in comp_roster["distname"].tolist() if d != primary_district])
    compare_districts = st.multiselect("Add districts", comp_options, key="compare")

    st.divider()
    st.header("📋 Section")
    section = st.radio("", [
        "💰 Per Pupil Spending",
        "🏛 Revenue Sources",
        "👩‍🏫 Staffing Ratios",
        "💵 Staffing Salaries",
        "🏦 Fund Balances",
        "📊 Special Ed",
    ], label_visibility="collapsed")

    st.divider()

    # Section-specific controls
    if section == "💰 Per Pupil Spending":
        ind_label = st.selectbox("Category", [i[2] for i in SPENDING_INDICATORS])

    elif section == "🏛 Revenue Sources":
        rev_chart_labels = [i[2] for i in REVENUE_CHART_INDICATORS]
        default_rev_idx  = rev_chart_labels.index("Local Revenue %") if "Local Revenue %" in rev_chart_labels else 0
        ind_label = st.selectbox("Chart this revenue source", rev_chart_labels, index=default_rev_idx)

    elif section == "👩‍🏫 Staffing Ratios":
        ratio_labels = [i[2] for i in RATIO_INDICATORS]
        ind_label    = st.selectbox("Chart this ratio", ratio_labels)

    elif section == "💵 Staffing Salaries":
        sal_labels = [i[2] for i in SALARY_INDICATORS]
        ind_label  = st.selectbox("Chart this salary", sal_labels)

    elif section == "🏦 Fund Balances":
        fund_labels      = [i[2] for i in FUND_INDICATORS]
        default_fund_idx = next((i for i, l in enumerate(fund_labels) if "Excess Surplus" in l and "Y1" in l), 0)
        ind_label        = st.selectbox("Indicator", fund_labels, index=default_fund_idx)

    elif section == "📊 Special Ed":
        vs_labels = [i[2] for i in VITSTAT_INDICATORS]
        ind_label = st.selectbox("Chart this stat", vs_labels)

    chart_height = st.slider("Chart height (px)", 400, 1000, 600, step=50)

# ── Resolve indicator metadata ────────────────────────────────────────────────
all_ind_catalog = (SPENDING_INDICATORS + RATIO_INDICATORS + SALARY_INDICATORS
                   + FUND_INDICATORS + VITSTAT_INDICATORS + REVENUE_INDICATORS)
ind_meta  = next(i for i in all_ind_catalog if i[2] == ind_label)
fname, col, label, fmt, y_label, scale = ind_meta

# ── Load stats ────────────────────────────────────────────────────────────────
with st.spinner("Loading data…"):
    stats_df = build_stats(peer_group, fname, col, scale)

if stats_df.empty:
    st.error("No data found for this indicator and peer group.")
    st.stop()

latest_year  = max(stats_df.index)
all_selected = [primary_district] + compare_districts

# ── Chart ─────────────────────────────────────────────────────────────────────
fig = make_chart(stats_df, primary_district, compare_districts,
                 fmt, y_label,
                 title=f"{ind_label}  ·  {primary_district} vs {peer_group}",
                 height=chart_height)
st.plotly_chart(fig, use_container_width=True)

# ── Spending breakdown (pie + sub-table) ──────────────────────────────────────
if section == "💰 Per Pupil Spending" and ind_label in BREAKDOWN_MAP:
    st.divider()
    st.subheader(f"{latest_year} Spending Breakdown — {primary_district}")
    child_labels = BREAKDOWN_MAP[ind_label]
    bd = load_breakdown(latest_year, child_labels, primary_district, peer_group)
    if not bd.empty:
        col_tbl, col_pie = st.columns([1, 1])
        with col_tbl:
            rows = [{"Component": r["label"],
                     primary_district: fmt_val(r["dist_val"], "$"),
                     "Peer Median": fmt_val(r["peer_med"], "$"),
                     "% of Total": f"{r['pct']:.1f}%" if pd.notna(r["pct"]) else "—"}
                    for _, r in bd.iterrows()]
            tbl = pd.DataFrame(rows)
            def _style_total(row):
                # Bold only the first row — the parent/total indicator
                if row["Component"] == child_labels[0]:
                    return ["font-weight: bold; background-color: #f0f4f8"] * len(row)
                return [""] * len(row)
            st.dataframe(tbl.style.apply(_style_total, axis=1),
                         use_container_width=True, hide_index=True)
        with col_pie:
            pie_df = bd[~bd["label"].str.endswith("Total")].dropna(subset=["dist_val"])
            if not pie_df.empty:
                pie_colors = ["#2A9D8F","#457B9D","#E9C46A","#E76F51","#6A4C93","#F4A261","#264653"]
                fig_pie = go.Figure(go.Pie(
                    labels=pie_df["label"], values=pie_df["dist_val"],
                    marker_colors=pie_colors[:len(pie_df)],
                    textinfo="percent",
                    textfont=dict(size=13),
                    insidetextorientation="radial",
                    hole=0.35,
                    hovertemplate="<b>%{label}</b><br>$%{value:,.0f}  (%{percent})<extra></extra>",
                ))
                fig_pie.update_layout(
                    showlegend=True,
                    legend=dict(
                        orientation="v",
                        yanchor="middle", y=0.5,
                        xanchor="left",   x=1.02,
                        font=dict(size=12),
                    ),
                    margin=dict(t=20, b=20, l=20, r=160),
                    height=320,
                    paper_bgcolor="white",
                )
                st.plotly_chart(fig_pie, use_container_width=True)

# ── Revenue Sources: table + pie ─────────────────────────────────────────────
if section == "🏛 Revenue Sources":
    st.divider()
    st.subheader(f"{latest_year} Revenue Sources Ranking")
    st.caption("★ marks selected districts. Ranked by selected revenue source (lowest → highest).")

    with st.spinner("Loading revenue data…"):
        rev_multi = load_multi_col_table(latest_year, REVENUE_INDICATORS, peer_group)

    if not rev_multi.empty:
        peer_dn = stats_df.loc[latest_year, "peer_distnames"] if latest_year in stats_df.index else set()
        fmt_map = {i[2]: i[3] for i in REVENUE_INDICATORS}

        col_tbl, col_pie = st.columns([3, 2])

        with col_tbl:
            tbl = make_multi_col_ranking_table(
                rev_multi, all_selected, fmt_map, sort_col="Total Spending Per Pupil",
                county_filter=comp_counties if comp_counties else None,
                roster=roster, peers_only=peers_only, peer_distnames=peer_dn)
            if not tbl.empty:
                def _style_rev(row):
                    if str(row["District"]).startswith("★"):
                        return ["background-color: #fff3cd; font-weight: bold"] * len(row)
                    return [""] * len(row)
                st.dataframe(tbl.style.apply(_style_rev, axis=1),
                             use_container_width=True, hide_index=True, height=600,
                             column_config=build_col_config(fmt_map))

        with col_pie:
            # Pull primary district's revenue splits for latest year
            dist_row = rev_multi[rev_multi.index == primary_district.strip().title()]
            if not dist_row.empty:
                rev_vals = {
                    "State":   dist_row["State Revenue %"].iloc[0],
                    "Local":   dist_row["Local Revenue %"].iloc[0],
                    "Federal": dist_row["Federal Revenue %"].iloc[0],
                }
                rev_vals = {k: v for k, v in rev_vals.items()
                            if v is not None and not pd.isna(v) and v > 0}
                if rev_vals:
                    st.markdown(f"**{primary_district} — {latest_year} Revenue Mix**")
                    fig_pie = go.Figure(go.Pie(
                        labels=list(rev_vals.keys()),
                        values=list(rev_vals.values()),
                        marker_colors=["#E9C46A", "#2A9D8F", "#E76F51"],
                        textinfo="percent",
                        textfont=dict(size=13),
                        insidetextorientation="radial",
                        hole=0.38,
                        hovertemplate="<b>%{label}</b><br>%{value:.1f}%<extra></extra>",
                    ))
                    fig_pie.update_layout(
                        showlegend=True,
                        legend=dict(
                            orientation="v",
                            yanchor="middle", y=0.5,
                            xanchor="left",   x=1.02,
                            font=dict(size=13),
                        ),
                        margin=dict(t=30, b=20, l=20, r=120),
                        height=340,
                        paper_bgcolor="white",
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)

# ── Ranking table ─────────────────────────────────────────────────────────────
if section not in ("🏛 Revenue Sources", "📊 Special Ed", "🏦 Fund Balances"):
    st.divider()

if section in ("👩‍🏫 Staffing Ratios", "💵 Staffing Salaries"):
    # Multi-column table: all ratios or all salaries side by side
    ind_group   = RATIO_INDICATORS if section == "👩‍🏫 Staffing Ratios" else SALARY_INDICATORS
    group_fmt   = "ratio" if section == "👩‍🏫 Staffing Ratios" else "salary"
    col_labels  = [i[2] for i in ind_group]
    col_scales  = [i[5] for i in ind_group]

    st.subheader(f"{latest_year} Full Ranking — {section.split()[-1]} ({primary_district} peer group)")
    st.caption("★ marks selected districts. Rank 1 = lowest value.")

    with st.spinner("Loading all columns…"):
        multi_df = load_multi_col_table(latest_year, ind_group, peer_group)

    if not multi_df.empty:
        # Get peer distnames from main stats_df for filtering
        peer_dn = stats_df.loc[latest_year, "peer_distnames"] if latest_year in stats_df.index else set()
        fmt_map  = {lbl: group_fmt for lbl in col_labels}
        sort_col = "Student:Teacher Ratio" if section == "👩‍🏫 Staffing Ratios" else ind_label
        tbl = make_multi_col_ranking_table(
            multi_df, all_selected, fmt_map, sort_col=sort_col,
            county_filter=comp_counties if comp_counties else None,
            roster=roster, peers_only=peers_only, peer_distnames=peer_dn)
        if not tbl.empty:
            def _style_hl(row):
                if str(row["District"]).startswith("★"):
                    return ["background-color: #fff3cd; font-weight: bold"] * len(row)
                return [""] * len(row)
            st.dataframe(tbl.style.apply(_style_hl, axis=1),
                         use_container_width=True, hide_index=True, height=600,
                         column_config=build_col_config(fmt_map))

elif section == "📊 Special Ed":
    # Multi-column table sorted by % Students in Special Ed
    st.subheader(f"{latest_year} Special Ed Ranking ({primary_district} peer group)")
    st.caption("★ marks selected districts. Rank 1 = lowest % in Special Ed.")
    with st.spinner("Loading Special Ed data…"):
        multi_df = load_multi_col_table(latest_year, VITSTAT_INDICATORS, peer_group)
    if not multi_df.empty:
        peer_dn = stats_df.loc[latest_year, "peer_distnames"] if latest_year in stats_df.index else set()
        fmt_map = {i[2]: i[3] for i in VITSTAT_INDICATORS}
        tbl = make_multi_col_ranking_table(
            multi_df, all_selected, fmt_map, sort_col="% Students in Special Ed",
            county_filter=comp_counties if comp_counties else None,
            roster=roster, peers_only=peers_only, peer_distnames=peer_dn)
        if not tbl.empty:
            def _style_hl2(row):
                if str(row["District"]).startswith("★"):
                    return ["background-color: #fff3cd; font-weight: bold"] * len(row)
                return [""] * len(row)
            st.dataframe(tbl.style.apply(_style_hl2, axis=1),
                         use_container_width=True, hide_index=True, height=600,
                         column_config=build_col_config(fmt_map))

elif section == "🏦 Fund Balances":
    st.subheader(f"{latest_year} Fund Balances Ranking")
    st.caption("★ marks selected districts. Rank 1 = lowest value.")
    with st.spinner("Loading fund balance data…"):
        multi_df = load_multi_col_table(latest_year, FUND_INDICATORS, peer_group)
    if not multi_df.empty:
        peer_dn = stats_df.loc[latest_year, "peer_distnames"] if latest_year in stats_df.index else set()
        fmt_map = {i[2]: i[3] for i in FUND_INDICATORS}
        tbl = make_multi_col_ranking_table(
            multi_df, all_selected, fmt_map, sort_col=ind_label,
            county_filter=comp_counties if comp_counties else None,
            roster=roster, peers_only=peers_only, peer_distnames=peer_dn)
        if not tbl.empty:
            def _style_fund(row):
                if str(row["District"]).startswith("★"):
                    return ["background-color: #fff3cd; font-weight: bold"] * len(row)
                return [""] * len(row)
            st.dataframe(tbl.style.apply(_style_fund, axis=1),
                         use_container_width=True, hide_index=True, height=600,
                         column_config=build_col_config(fmt_map))

elif section not in ("🏛 Revenue Sources", "📊 Special Ed", "🏦 Fund Balances"):
    # Standard single-column ranking table (Per Pupil Spending)
    st.subheader(f"{latest_year} Full Ranking — least to most expensive")
    st.caption("★ marks selected districts. Rank 1 = lowest value in the group.")

    subcols_df = None
    if section == "💰 Per Pupil Spending" and ind_label in BREAKDOWN_MAP:
        # Exclude any child whose source (fname, col) is the same as the parent
        # to avoid duplicating the main value column in the table
        parent_fname, parent_col = fname.upper(), col.upper()
        children = [
            c for c in BREAKDOWN_MAP[ind_label]
            if c in ALL_INDICATORS_MAP
            and not (ALL_INDICATORS_MAP[c][0].upper() == parent_fname
                     and ALL_INDICATORS_MAP[c][1].upper() == parent_col)
        ]
        if children:
            raw_sc = load_subcomponent_cols(latest_year, children, peer_group)
            if not raw_sc.empty:
                subcols_df = raw_sc

    ranking = make_ranking_table(
        stats_df, all_selected, fmt,
        value_label=ind_label, year=latest_year,
        county_filter=comp_counties if comp_counties else None,
        roster=roster, peers_only=peers_only, subcols_df=subcols_df)

    if not ranking.empty:
        def _style_hl3(row):
            if str(row["District"]).startswith("★"):
                return ["background-color: #fff3cd; font-weight: bold"] * len(row)
            return [""] * len(row)
        st.dataframe(ranking.style.apply(_style_hl3, axis=1),
                     use_container_width=True, hide_index=True, height=600)

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "**How to read the chart:** Blue band = IQR (middle 50% of peer districts). "
    "Dotted line = peer median. Numbers on each dot = percentile rank that year. "
    "Red = within IQR · Orange = outside IQR · Dark red = outside top/bottom 10%.")
