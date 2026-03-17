"""
NJ School Finance Explorer — Streamlit dashboard
-------------------------------------------------
Run from project root:
    python3 -m streamlit run app/tges_dashboard.py
"""
from __future__ import annotations

import sys
from pathlib import Path


def _find_project_root() -> Path:
    """Locate project root (directory containing data/TGES)."""
    candidate = Path(__file__).resolve().parent.parent
    for _ in range(6):
        if (candidate / "data" / "TGES").is_dir():
            return candidate
        candidate = candidate.parent
    raise FileNotFoundError("Could not locate data/TGES/")


PROJECT_ROOT = _find_project_root()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import warnings
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.tges_models import County, District

warnings.filterwarnings("ignore")

# Sections that have their own table block (no standard single-column ranking)
SECTIONS_WITH_DEDICATED_TABLE = ("🏛 Revenue Sources", "📊 Special Ed", "🏦 Fund Balances", "👥 Enrollment")


def _normalize_county_filter(county_filter: list[str] | list[County] | None) -> list[str] | None:
    """Convert County enum values to strings for roster lookup."""
    if not county_filter:
        return None
    return [c.value if isinstance(c, County) else c for c in county_filter]


def _county_district_set(roster: pd.DataFrame, county_filter: list[str] | None) -> set[str]:
    """Set of district names in the given counties (for filtering ranking tables)."""
    if not county_filter or roster is None:
        return set()
    return set(roster[roster["county"].isin(county_filter)]["distname"].tolist())

# ── Paths and globals ──────────────────────────────────────────────────────────
TGES_ROOT = PROJECT_ROOT / "data" / "TGES"
YEARS        = list(range(2011, 2026))
NULL_VALS    = {"N.A.", "N.R.", "", "N/A", "NA"}

# ── Indicator catalogs ────────────────────────────────────────────────────────
# Files and columns use postprocessed names (see code/data/tges_postprocess.py).
# Tuples: (csv_file, value_col, label, fmt, y_label, scale)
# value_col: base name (e.g. "Per_Pupil") → resolved as {base}_{year}_budgeted; or full column name for VITSTAT/fund.
# scale: multiply raw value × scale for display (100 for stored-as-decimal pct)

INDICATOR_1 = "Indicator 1-Budgetary Per Pupil Cost.csv"
INDICATOR_2 = "Indicator 2-Total Classroom Instruction.csv"
INDICATOR_6 = "Indicator 6-Total Support Services.csv"
INDICATOR_8 = "Indicator 8-Total Administrative Costs per Pupil.csv"
INDICATOR_10 = "Indicator 10-Operations and Maintenance of Plant.csv"
INDICATOR_13 = "Indicator 13-Extracurricular Costs per Pupil and Benefits.csv"
INDICATOR_14 = "Indicator 14-Personal Services - Employee Benefits.csv"
INDICATOR_15 = "Indicator 15-Total Equipment Cost per Pupil.csv"
INDICATOR_16 = "Indicator 16-Ratio of Students to Teachers, Median Salary.csv"
INDICATOR_17 = "Indicator 17-Ratio of Students to Special Service, Median Salary.csv"
INDICATOR_18 = "Indicator 18-Ratio of Students to Administrators, Median Salary.csv"
INDICATOR_19 = "Indicator 19-Ratio of Faculty to Administrators.csv"
INDICATOR_20 = "Indicator 20-Budgeted General Fund Balance vs Actual (used).csv"
INDICATOR_21 = "Indicator 21-Excess Unreserved General Fund Balances.csv"
VITSTAT_FILE = "Summary of Vital Statistics.csv"
TOTAL_SPENDING_FILE = "Total Spending Per Pupil.csv"
STATE_AVG_FILE = "Summary - State Average and Median for each operating type.csv"

SPENDING_INDICATORS = [
    (INDICATOR_1,  "Per_Pupil", "Budgetary Per-Pupil Cost",             "$",     "Per-pupil cost ($)", 1),
    (INDICATOR_2,  "Per_Pupil", "Classroom Instruction",                "$",     "Per-pupil cost ($)", 1),
    (INDICATOR_6,  "Per_Pupil", "Support Services",                     "$",     "Per-pupil cost ($)", 1),
    (INDICATOR_8,  "Per_Pupil", "Total Administration",                 "$",     "Per-pupil cost ($)", 1),
    (INDICATOR_10, "Per_Pupil", "Operations & Maintenance",             "$",     "Per-pupil cost ($)", 1),
    (INDICATOR_13, "Per_Pupil", "Extracurricular Costs",                "$",     "Per-pupil cost ($)", 1),
    (INDICATOR_15, "Per_Pupil", "Equipment Costs",                      "$",     "Per-pupil cost ($)", 1),
    (INDICATOR_14, "Pct_Total_Salaries", "Employee Benefits % of Salaries", "pct", "% of Salaries", 100),
]

RATIO_INDICATORS = [
    (INDICATOR_16, "Student_Teacher_Ratio", "Student:Teacher Ratio",      "ratio", "Students per teacher",       1),
    (INDICATOR_17, "Student_Support_Ratio", "Student:Support Staff Ratio", "ratio", "Students per support staff", 1),
    (INDICATOR_18, "Student_Admin_Ratio",   "Student:Admin Ratio",          "ratio", "Students per administrator", 1),
    (INDICATOR_19, "Faculty_Admin_Ratio",   "Faculty:Admin Ratio",         "ratio", "Faculty per administrator",  1),
]

SALARY_INDICATORS = [
    (INDICATOR_16, "Teacher_Median_Salary",   "Median Teacher Salary",       "salary", "Median salary ($)", 1),
    (INDICATOR_17, "Support_Staff_Salary",   "Median Support Staff Salary",  "salary", "Median salary ($)", 1),
    (INDICATOR_18, "Admin_Salary",           "Median Admin Salary",          "salary", "Median salary ($)", 1),
]

# Fund columns are Yr1/Yr2 only in postprocessed files (e.g. 2023, 2024 for 2025 release)
FUND_INDICATORS = [
    (INDICATOR_20, "General_Fund_Balance", "General Fund Balance", "$", "Total $", 1),
    (INDICATOR_21, "Excess", "Excess Surplus", "$", "Total $", 1),
]

VITSTAT_INDICATORS = [
    (VITSTAT_FILE, "Special_Ed_Pct_Enrollment", "% Students in Special Ed", "pct", "% of Enrollment", 100),
    (VITSTAT_FILE, "Total_Spending_Per_Pupil",   "Total Spending Per Pupil", "$",   "Per-pupil ($)",    1),
]

ENROLLMENT_INDICATORS = [
    (INDICATOR_1, "Enrollment", "Enrollment", "int", "Students", 1),
]

REVENUE_INDICATORS = [
    (VITSTAT_FILE, "Total_Spending_Per_Pupil", "Total Spending Per Pupil", "$",   "Per-pupil ($)",  1),
    (VITSTAT_FILE, "State_Share_Pct_Revenue",   "State Revenue %",          "pct", "% of Revenue", 100),
    (VITSTAT_FILE, "Local_Share_Pct_Revenue",   "Local Revenue %",          "pct", "% of Revenue", 100),
    (VITSTAT_FILE, "Federal_Share_Pct_Revenue", "Federal Revenue %",       "pct", "% of Revenue", 100),
    (VITSTAT_FILE, "Tuition_Pct_Revenue",       "Tuition %",                "pct", "% of Revenue", 100),
    (VITSTAT_FILE, "Free_Balance_Pct_Revenue",  "Free Balance %",          "pct", "% of Revenue", 100),
    (VITSTAT_FILE, "Other_Revenue_Pct",         "Other Revenue %",          "pct", "% of Revenue", 100),
]

# All sub-components used for breakdown tables / sub-col loading (postprocessed file/column names)
INDICATOR_3 = "Indicator 3-Classroom Salaries and Benefits.csv"
INDICATOR_4 = "Indicator 4-Classroom General Supplies and Textbooks.csv"
INDICATOR_5 = "Indicator 5-Classroom Purchased Services and Other.csv"
INDICATOR_7 = "Indicator 7-Support Services Salaries and Benefits.csv"
INDICATOR_8A = "Indicator 8A-Legal Services per Pupil.csv"
INDICATOR_9 = "Indicator 9-Administration Salaries and Benefits.csv"
INDICATOR_11 = "Indicator 11-Operations and Maintenance of Plant Salaries and Benefits.csv"
INDICATOR_12 = "Indicator 12-Food Service Cost per Pupil and Benefits.csv"

ALL_INDICATORS_MAP: dict[str, tuple] = {
    i[2]: i for i in [
        (INDICATOR_1,  "Per_Pupil", "Budgetary Per-Pupil Cost",       "$", 1),
        (INDICATOR_2,  "Per_Pupil", "Classroom Instruction Total",    "$", 1),
        (INDICATOR_3,  "Per_Pupil", "Classroom Salaries & Benefits",  "$", 1),
        (INDICATOR_4,  "Per_Pupil", "Classroom Supplies/Textbooks",   "$", 1),
        (INDICATOR_5,  "Per_Pupil", "Classroom Purchased Services",   "$", 1),
        (INDICATOR_6,  "Per_Pupil", "Support Services Total",         "$", 1),
        (INDICATOR_7,  "Per_Pupil", "Support Salaries & Benefits",    "$", 1),
        (INDICATOR_8,  "Per_Pupil", "Total Administration",           "$", 1),
        (INDICATOR_8A, "Per_Pupil", "Legal Services",                 "$", 1),
        (INDICATOR_9,  "Per_Pupil", "Admin Salaries & Benefits",      "$", 1),
        (INDICATOR_10, "Per_Pupil", "Operations & Maintenance Total", "$", 1),
        (INDICATOR_11, "Per_Pupil", "O&M Salaries & Benefits",        "$", 1),
        (INDICATOR_12, "Per_Pupil", "Food Service Contribution",      "$", 1),
        (INDICATOR_13, "Per_Pupil", "Extracurricular Costs",          "$", 1),
        (INDICATOR_15, "Per_Pupil", "Equipment Costs",                "$", 1),
        (INDICATOR_14, "Pct_Total_Salaries", "Employee Benefits % of Salaries", "pct", 100),
    ]
}

BREAKDOWN_MAP: dict[str, list[str]] = {
    # First item is always the parent total (bold header row, pct = 100%)
    "Budgetary Per-Pupil Cost": [
        "Budgetary Per-Pupil Cost",
        "Classroom Instruction Total", "Support Services Total",
        "Total Administration", "Operations & Maintenance Total",
        "Extracurricular Costs", "Equipment Costs",
    ],
    "Classroom Instruction":    ["Classroom Instruction Total", "Classroom Salaries & Benefits",
                                  "Classroom Supplies/Textbooks", "Classroom Purchased Services"],
    "Support Services":         ["Support Services Total", "Support Salaries & Benefits"],
    "Total Administration":     ["Total Administration", "Legal Services", "Admin Salaries & Benefits"],
    "Operations & Maintenance": ["Operations & Maintenance Total", "O&M Salaries & Benefits"],
}

# ── Data helpers ──────────────────────────────────────────────────────────────
# Postprocessed files use readable names; columns use {base}_{year}_budgeted for indicators.

# State average file: (fname, col) -> (state_column_base, use_year_budgeted).
# use_year_budgeted True -> col is {base}_{year}_budgeted; False -> {base}_{year-1}.
STATE_AVG_COL: dict[tuple[str, str], tuple[str, bool]] = {
    (INDICATOR_1, "Per_Pupil"): ("Budgetary_Per_Pupil_Cost_Per_Pupil", True),
    (INDICATOR_2, "Per_Pupil"): ("Total_Classroom_Instruction_Per_Pupil", True),
    (INDICATOR_6, "Per_Pupil"): ("Total_Support_Services_Per_Pupil", True),
    (INDICATOR_8, "Per_Pupil"): ("Administrative_Costs_Per_Pupil", True),
    (INDICATOR_10, "Per_Pupil"): ("Operations_Maintenance_Plant_Per_Pupil", True),
    (INDICATOR_13, "Per_Pupil"): ("Extracurricular_Costs_Per_Pupil", True),
    (INDICATOR_15, "Per_Pupil"): ("Total_Equipment_Cost_Per_Pupil", True),
    (INDICATOR_14, "Pct_Total_Salaries"): ("Employee_Benefits_Pct_Salaries_Per_Pupil", True),
    (TOTAL_SPENDING_FILE, "Avg_Daily_Enrollment"): ("Avg_Daily_Enrollment", False),
    (INDICATOR_1, "Enrollment"): ("Avg_Daily_Enrollment", False),
    (TOTAL_SPENDING_FILE, "Total_Expenditures"): ("Total_Expenditures", False),
}

# Base names for year-suffixed columns (value column = f"{base}_{year}_budgeted")
COL_BASE = frozenset({
    "Per_Pupil", "Student_Teacher_Ratio", "Student_Support_Ratio", "Student_Admin_Ratio", "Faculty_Admin_Ratio",
    "Teacher_Median_Salary", "Support_Staff_Salary", "Admin_Salary",
    "Pct_Total_Salaries",
    "Enrollment",  # Indicator 1 has Enrollment_2023, Enrollment_2024, Enrollment_{year}_budgeted
})
# Columns of form {base}_{data_year}; use year-1 then year-2 (Total Spending, Fund files)
LATEST_ACTUAL_BASE = frozenset({"Avg_Daily_Enrollment", "Total_Expenditures", "Per_Pupil_Expenditures"})
FUND_BASE = frozenset({"General_Fund_Balance", "Excess"})
DATA_YEAR_BASE = LATEST_ACTUAL_BASE | FUND_BASE


def _resolve_col(df: pd.DataFrame, col: str, year: int) -> str | None:
    """Resolve value column: base → {base}_{year}_budgeted; data-year → {base}_{year-1}; else literal."""
    for c in df.columns:
        if c.upper() == col.upper():
            return c
    if col in COL_BASE:
        candidate = f"{col}_{year}_budgeted"
        for c in df.columns:
            if c.upper() == candidate.upper():
                return c
    if col in DATA_YEAR_BASE:
        for data_yr in (year - 1, year - 2):
            if data_yr < 2010:
                break
            candidate = f"{col}_{data_yr}"
            for c in df.columns:
                if c.upper() == candidate.upper():
                    return c
    return None


def get_csv_dir(year: int) -> Path | None:
    """Return directory containing postprocessed TGES CSVs for the given year (flat layout: .../2025/)."""
    base = TGES_ROOT / str(year)
    if not base.is_dir():
        return None
    if (base / INDICATOR_1).exists():
        return base
    # Backward compatibility: CSVs may live in a subdir (e.g. 2025/extracted/...)
    for d in base.iterdir():
        if d.is_dir() and (d / INDICATOR_1).exists():
            return d
        if d.is_dir():
            for sub in d.iterdir():
                if sub.is_dir() and (sub / INDICATOR_1).exists():
                    return sub
    return None


def _find_file(csv_dir: Path, fname: str) -> Path | None:
    path = csv_dir / fname
    return path if path.exists() else None

def clean_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.strip().replace(list(NULL_VALS), None),
        errors="coerce")

def _read_csv(csv_dir: Path, fname: str) -> pd.DataFrame | None:
    match = _find_file(csv_dir, fname)
    if match is None:
        return None
    df = pd.read_csv(match, encoding="latin-1", dtype=str)
    df.columns = df.columns.str.strip()
    col_map = {}
    if "Operating_Type" in df.columns:
        col_map["Operating_Type"] = "GROUP"
    if "Budget_Operating_Type" in df.columns:
        col_map["Budget_Operating_Type"] = "GROUP"
    if "County" in df.columns:
        col_map["County"] = "CONAME"
    if "District_Code" in df.columns:
        col_map["District_Code"] = "DIST"
    if "District_Name" in df.columns:
        col_map["District_Name"] = "DISTNAME"
    if col_map:
        df = df.rename(columns=col_map)
    df.columns = df.columns.str.upper().str.strip()
    df["DISTNAME"] = df["DISTNAME"].str.strip().str.title()
    return df


def _district_value(df: pd.DataFrame, col: str, district: str):
    """Single district value for a column; None if missing."""
    sub = df[df["DISTNAME"] == district.strip().title()]
    if sub.empty:
        return None
    try:
        return float(sub.iloc[0][col])
    except (TypeError, ValueError, KeyError):
        return None


def _peer_median(df: pd.DataFrame, col: str, peer_group: str):
    """Median of col over real districts in peer_group."""
    grp = df[df["GROUP"].str.strip() == peer_group]
    real = grp[pd.to_numeric(grp["DIST"], errors="coerce").notna()]
    vals = pd.to_numeric(real[col].replace(list(NULL_VALS), None), errors="coerce").dropna()
    return vals.median() if len(vals) > 0 else None

# ── Cached data loaders ───────────────────────────────────────────────────────

def _load_enrollment_2025(csv_dir: Path) -> pd.Series:
    """Load enrollment (Avg Daily Enrollment 2024) from Total Spending file. Index = DIST."""
    df = _read_csv(csv_dir, TOTAL_SPENDING_FILE)
    if df is None:
        return pd.Series(dtype=float)
    en_col = "AVG_DAILY_ENROLLMENT_2024"
    if en_col not in df.columns:
        return pd.Series(dtype=float)
    real = df[pd.to_numeric(df["DIST"], errors="coerce").notna()].copy()
    real["_en"] = clean_num(real[en_col])
    return real.drop_duplicates("DIST").set_index("DIST")["_en"]


@st.cache_data(show_spinner="Loading district roster…")
def load_roster() -> pd.DataFrame:
    csv_dir = get_csv_dir(2025)
    if csv_dir is None:
        return pd.DataFrame(columns=["distname", "county", "group", "enrollment"])
    df = _read_csv(csv_dir, INDICATOR_1)
    real = df[pd.to_numeric(df["DIST"], errors="coerce").notna()].copy()
    roster = (
        real[["DIST", "DISTNAME", "CONAME", "GROUP"]]
        .rename(columns={"DISTNAME": "distname", "CONAME": "county", "GROUP": "group"})
        .drop_duplicates("distname")
        .sort_values("distname")
        .reset_index(drop=True)
    )
    enrollment = _load_enrollment_2025(csv_dir)
    roster["enrollment"] = roster["DIST"].astype(str).map(enrollment)
    roster = roster.drop(columns=["DIST"])
    return roster

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
        col_u = _resolve_col(df, col, year) or col.upper()
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
def load_state_avg_series(
    peer_group: str, fname: str, col: str, scale: float = 1
) -> dict[int, float]:
    """Load group average from State Average file per year. Returns {year: value} for chart reference line."""
    key = (fname, col)
    if key not in STATE_AVG_COL:
        return {}
    base, use_budgeted = STATE_AVG_COL[key]
    out = {}
    for year in YEARS:
        csv_dir = get_csv_dir(year)
        if csv_dir is None:
            continue
        df = _read_csv(csv_dir, STATE_AVG_FILE)
        if df is None:
            continue
        if use_budgeted:
            state_col = f"{base}_{year}_budgeted"
        else:
            data_yr = year - 1
            if data_yr < 2010:
                continue
            state_col = f"{base}_{data_yr}"
        state_col_u = state_col.upper()
        if state_col_u not in df.columns:
            continue
        mask = (df["GROUP"].str.strip() == peer_group.strip()) & (
            df["DISTNAME"].str.contains("Group average", case=False, na=False)
        )
        row = df.loc[mask]
        if row.empty:
            continue
        val = clean_num(row[state_col_u]).iloc[0]
        if pd.notna(val):
            v = float(val) * scale
            if np.isfinite(v):
                out[year] = v
    return out


@st.cache_data(show_spinner=False)
def load_multi_col_table(year: int, col_defs: list[tuple], peer_group: str,
                        peers_only: bool = True) -> pd.DataFrame:
    """
    Load multiple value columns for districts in one table.
    col_defs: list of (fname, col, label, fmt, y_label, scale)
    peers_only: if True, only load peer group districts; if False, load all districts.
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
        col_u = _resolve_col(df, col, year) or col.upper()
        if col_u not in df.columns:
            continue
        if peers_only:
            grp  = df[df["GROUP"].str.strip() == peer_group]
            real = grp[pd.to_numeric(grp["DIST"], errors="coerce").notna()].copy()
        else:
            real = df[pd.to_numeric(df["DIST"], errors="coerce").notna()].copy()
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
        col_u = _resolve_col(df, col, year) or col.upper()
        if col_u not in df.columns:
            continue
        dist_val = _district_value(df, col_u, district)
        peer_med = _peer_median(df, col_u, peer_group)
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
        col_u = _resolve_col(df, col, year) or col.upper()
        if col_u not in df.columns:
            continue
        real = df[pd.to_numeric(df["DIST"], errors="coerce").notna()].copy()
        real["_v"] = clean_num(real[col_u])
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
    if fmt == "int":
        return f"{v:,.0f}"
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


def _pctile_ranks(stats_df: pd.DataFrame, primary_name: str) -> dict:
    """Percentile rank of primary district within peer group for each year."""
    primary_series = extract_district_series(stats_df, primary_name)
    out = {}
    for yr, row in stats_df.iterrows():
        mv = primary_series.get(yr)
        peer_dn = row.get("peer_distnames", set())
        peers = [v for k, v in row["all_vals"].items()
                 if k != primary_name and k in peer_dn]
        if mv is not None and not pd.isna(mv) and peers:
            out[yr] = sum(v < mv for v in peers) / len(peers) * 100
    return out


def _pctile_description(p: float | None) -> str:
    if p is None:
        return ""
    if p < 10:
        return f"{p:.0f}th pctile  (bottom 10%)"
    if p < 25:
        return f"{p:.0f}th pctile  (below IQR)"
    if p <= 75:
        return f"{p:.0f}th pctile  (within IQR)"
    if p <= 90:
        return f"{p:.0f}th pctile  (above IQR)"
    return f"{p:.0f}th pctile  (top 10%)"


def _add_iqr_band(fig: go.Figure, years, p25, p75) -> None:
    fig.add_trace(go.Scatter(x=years, y=p75, mode="lines",
                             line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=years, y=p25, mode="lines",
                             line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(66,165,245,0.22)",
                             name="Middle 50% of peers (IQR)",
                             legendgroup="band", hoverinfo="skip"))


def _add_peer_median_trace(fig: go.Figure, years, p50, fmt: str) -> None:
    fig.add_trace(go.Scatter(
        x=years, y=p50, mode="lines",
        line=dict(color="#457B9D", width=1.5, dash="dot"),
        name="Peer median",
        hovertemplate="<b>%{x}</b><br>Peer median: %{text}<extra>Peer median</extra>",
        text=[fmt_val(v, fmt) for v in p50]))


def _add_state_avg_trace(
    fig: go.Figure, years, state_avg_series: dict[int, float], fmt: str
) -> None:
    vals = [state_avg_series.get(int(yr)) for yr in years]
    if not any(v is not None and np.isfinite(v) for v in vals):
        return
    fig.add_trace(go.Scatter(
        x=years, y=vals, mode="lines",
        line=dict(color="#7B68EE", width=1.5, dash="dash"),
        name="Group avg (state)",
        hovertemplate="<b>%{x}</b><br>Group avg: %{text}<extra>State summary</extra>",
        text=[fmt_val(v, fmt) for v in vals]))


def _add_compare_traces(fig: go.Figure, years, all_series, compare_names, fmt: str) -> None:
    for i, name in enumerate(compare_names):
        vals = [all_series[name].get(yr) for yr in years]
        color = OVERLAY_COLORS[(i + 1) % len(OVERLAY_COLORS)]
        fig.add_trace(go.Scatter(
            x=years, y=vals, mode="lines+markers",
            line=dict(color=color, width=2, dash="dashdot"),
            marker=dict(size=7, color=color, symbol="diamond",
                        line=dict(color="white", width=1)),
            name=name,
            hovertemplate=f"<b>%{{x}}</b><br>{name}: %{{text}}<extra>{name}</extra>",
            text=[fmt_val(v, fmt) for v in vals]))


def _add_primary_trace(fig: go.Figure, years, primary_series, pctile_ranks,
                       primary_name: str, ns, fmt: str, *,
                       show_value_as_label: bool = False) -> None:
    pv = [primary_series.get(yr) for yr in years]
    pr_vals = [pctile_ranks.get(yr) for yr in years]
    if show_value_as_label:
        labels = [fmt_val(v, fmt) if v is not None and not (isinstance(v, float) and pd.isna(v)) else "" for v in pv]
    else:
        labels = [f"{p:.0f}%" if p is not None else "" for p in pr_vals]
    hover = []
    for yr, v, p in zip(years, pv, pr_vals):
        if v is None or pd.isna(v):
            hover.append("N/A")
            continue
        p_desc = _pctile_description(p)
        n_peers = ns[list(years).index(yr)]
        hover.append(f"{fmt_val(v, fmt)}<br>{p_desc}<br>vs {n_peers} peers")
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


def _chart_layout(
    fig: go.Figure,
    title: str,
    y_label: str,
    fmt: str,
    height: int,
    *,
    x_title: str = "School Year",
) -> None:
    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color="#1A1A2E"), x=0, y=0.98,
                   xanchor="left", yanchor="top"),
        xaxis=dict(title=x_title, dtick=1, gridcolor="#eee", tickangle=-45),
        yaxis=dict(
            title=y_label, gridcolor="#eee",
            tickprefix="$" if fmt in ("$", "salary") else "",
            ticksuffix="%" if fmt == "pct" else "",
            tickformat="," if fmt in ("$", "salary") else ",.0f" if fmt == "int" else ".1f",
            autorange=True),
        plot_bgcolor="white", paper_bgcolor="white",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.18,
                    xanchor="left", x=0, font=dict(size=11),
                    bgcolor="rgba(255,255,255,0.8)"),
        height=height, margin=dict(t=60, b=160, l=70, r=70))


def make_chart(stats_df, primary_name, compare_names, fmt, y_label, title,
               height=600, *, x_title: str = "School Year",
               state_avg_series: dict[int, float] | None = None,
               show_value_as_label: bool = False) -> go.Figure:
    if stats_df.empty:
        return go.Figure().update_layout(title="No data available")
    years = stats_df.index.values
    p25 = stats_df["p25"].values
    p75 = stats_df["p75"].values
    p50 = stats_df["p50"].values
    ns = stats_df["n"].values
    primary_series = extract_district_series(stats_df, primary_name)
    all_series = {d: extract_district_series(stats_df, d) for d in [primary_name] + compare_names}
    pctile_ranks = _pctile_ranks(stats_df, primary_name)

    fig = go.Figure()
    _add_iqr_band(fig, years, p25, p75)
    _add_peer_median_trace(fig, years, p50, fmt)
    if state_avg_series:
        _add_state_avg_trace(fig, years, state_avg_series, fmt)
    _add_compare_traces(fig, years, all_series, compare_names, fmt)
    _add_primary_trace(fig, years, primary_series, pctile_ranks, primary_name, ns, fmt,
                       show_value_as_label=show_value_as_label)
    _chart_layout(fig, title, y_label, fmt, height, x_title=x_title)
    return fig


def make_ranking_table(stats_df, highlight_districts, fmt, value_label="Value",
                       year=2025, county_filter=None, roster=None,
                       peers_only=True, subcols_df=None) -> pd.DataFrame:
    if stats_df.empty or year not in stats_df.index:
        return pd.DataFrame()
    row = stats_df.loc[year]
    highlight_set = set(highlight_districts)
    peer_set = row.get("peer_distnames", set())
    counties = _normalize_county_filter(county_filter)
    county_set = _county_district_set(roster, counties)

    records = []
    for dist, val in row["all_vals"].items():
        if val is None or pd.isna(val):
            continue
        is_hl = dist in highlight_set
        if peers_only and dist not in peer_set and not is_hl:
            continue
        if counties and not is_hl and dist not in county_set:
            continue
        records.append({"distname": dist, "value": val})
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).sort_values("value").reset_index(drop=True)
    df["Rank"] = df.index + 1
    df["District"] = df["distname"].apply(lambda d: f"★ {d}" if d in highlight_set else d)
    # Keep value numeric so Streamlit sorts by number, not string
    df[value_label] = pd.to_numeric(df["value"], errors="coerce")

    if subcols_df is not None and not subcols_df.empty:
        safe_subcols = subcols_df.drop(
            columns=[c for c in subcols_df.columns if c == value_label],
            errors="ignore",
        )
        if not safe_subcols.empty:
            df = df.join(safe_subcols, on="distname", how="left")
            # Keep numeric so Streamlit sorts by number
            for col in safe_subcols.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

    base_cols  = ["Rank", "District", value_label]
    extra_cols = [c for c in df.columns if c not in base_cols + ["distname", "value"]]
    return df[base_cols + extra_cols].reset_index(drop=True)


def make_multi_col_ranking_table(multi_df, highlight_districts, fmt_map,
                                 sort_col, county_filter=None, roster=None,
                                 peers_only=True, peer_distnames=None) -> pd.DataFrame:
    """
    Multi-column ranking table: one column per indicator, ranked by sort_col.
    If roster has "enrollment", adds an Enrollment column. Returns numeric values
    so Streamlit can sort. Use build_col_config(fmt_map) for st.dataframe();
    include "Enrollment": "int" in fmt_map when roster is used.
    """
    if multi_df.empty or sort_col not in multi_df.columns:
        return pd.DataFrame()

    highlight_set = set(highlight_districts)
    peer_set = peer_distnames or set()
    counties = _normalize_county_filter(county_filter)
    county_set = _county_district_set(roster, counties)

    df = multi_df.reset_index().rename(columns={"DISTNAME": "distname",
                                                  "index": "distname"})
    if "distname" not in df.columns:
        df = df.reset_index().rename(columns={"index": "distname"})

    df = df.dropna(subset=[sort_col]).copy()

    mask = pd.Series([True] * len(df), index=df.index)
    if peers_only and peer_set:
        mask &= df["distname"].isin(peer_set) | df["distname"].isin(highlight_set)
    if counties and county_set:
        mask &= df["distname"].isin(county_set) | df["distname"].isin(highlight_set)
    df = df[mask].sort_values(sort_col).reset_index(drop=True)

    df["Rank"]     = df.index + 1
    df["District"] = df["distname"].apply(lambda d: f"★ {d}" if d in highlight_set else d)

    result = df[["Rank", "District"]].copy()
    if roster is not None and "enrollment" in roster.columns:
        result["Enrollment"] = df["distname"].map(
            roster.set_index("distname")["enrollment"]
        )
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
        elif fmt == "int":
            cfg[col] = st.column_config.NumberColumn(col, format="%.0f")
        else:
            cfg[col] = st.column_config.NumberColumn(col, format="%.2f")
    return cfg


def _fmt_map_with_enrollment(indicator_tuples: list, roster: pd.DataFrame) -> dict:
    """Build fmt_map from (..., label, fmt, ...) tuples and add Enrollment if present."""
    fmt_map = {t[2]: t[3] for t in indicator_tuples}
    if "enrollment" in roster.columns:
        fmt_map["Enrollment"] = "int"
    return fmt_map


def _style_highlight(row, highlight_prefix: str = "★") -> list:
    """Row style: highlight if District column starts with highlight_prefix."""
    if str(row.get("District", "")).startswith(highlight_prefix):
        return ["background-color: #fff3cd; font-weight: bold"] * len(row)
    return [""] * len(row)


def _render_ranking_dataframe(tbl: pd.DataFrame, fmt_map: dict, height: int = 600) -> None:
    """Display ranking table with highlight styling and column format."""
    if tbl.empty:
        return
    st.dataframe(
        tbl.style.apply(lambda row: _style_highlight(row), axis=1),
        use_container_width=True, hide_index=True, height=height,
        column_config=build_col_config(fmt_map),
    )


def _breakdown_table_style(row, first_label: str, n_cols: int) -> list:
    """Bold and background for breakdown table first row (total)."""
    if row.get("Component") == first_label:
        return ["font-weight: bold; background-color: #f0f4f8"] * n_cols
    return [""] * n_cols


def _render_spending_breakdown(bd: pd.DataFrame, primary_district: str, child_labels: list) -> None:
    """Render breakdown table and pie for spending components."""
    col_tbl, col_pie = st.columns([1, 1])
    with col_tbl:
        rows = [
            {
                "Component": r["label"],
                primary_district: fmt_val(r["dist_val"], "$"),
                "Peer Median": fmt_val(r["peer_med"], "$"),
                "% of Total": f"{r['pct']:.1f}%" if pd.notna(r["pct"]) else "—",
            }
            for _, r in bd.iterrows()
        ]
        tbl = pd.DataFrame(rows)
        n_cols = len(tbl.columns)
        st.dataframe(
            tbl.style.apply(lambda row: _breakdown_table_style(row, child_labels[0], n_cols), axis=1),
            use_container_width=True, hide_index=True,
        )
    with col_pie:
        pie_df = bd[~bd["label"].str.endswith("Total")].dropna(subset=["dist_val"])
        if not pie_df.empty:
            pie_colors = ["#2A9D8F", "#457B9D", "#E9C46A", "#E76F51", "#6A4C93", "#F4A261", "#264653"]
            fig_pie = go.Figure(go.Pie(
                labels=pie_df["label"], values=pie_df["dist_val"],
                marker_colors=pie_colors[: len(pie_df)],
                textinfo="percent",
                textfont=dict(size=13),
                insidetextorientation="radial",
                hole=0.35,
                hovertemplate="<b>%{label}</b><br>$%{value:,.0f}  (%{percent})<extra></extra>",
            ))
            fig_pie.update_layout(
                showlegend=True,
                legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02, font=dict(size=12)),
                margin=dict(t=20, b=20, l=20, r=160),
                height=320,
                paper_bgcolor="white",
            )
            st.plotly_chart(fig_pie, use_container_width=True)


def _revenue_mix_pie(rev_multi: pd.DataFrame, primary_district: str, year: int) -> None:
    """Render pie chart of State/Local/Federal revenue for primary district."""
    dist_row = rev_multi[rev_multi.index == primary_district.strip().title()]
    if dist_row.empty:
        return
    rev_vals = {
        "State": dist_row["State Revenue %"].iloc[0],
        "Local": dist_row["Local Revenue %"].iloc[0],
        "Federal": dist_row["Federal Revenue %"].iloc[0],
    }
    rev_vals = {k: v for k, v in rev_vals.items() if v is not None and not pd.isna(v) and v > 0}
    if not rev_vals:
        return
    st.markdown(f"**{primary_district} — {year} Revenue Mix**")
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
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02, font=dict(size=13)),
        margin=dict(t=30, b=20, l=20, r=120),
        height=340,
        paper_bgcolor="white",
    )
    st.plotly_chart(fig_pie, use_container_width=True)


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
    default_dist_idx = (
        all_districts.index(District.MIDDLETOWN.display_name)
        if District.MIDDLETOWN.display_name in all_districts
        else 0
    )
    primary_district = st.selectbox("Search district", all_districts, index=default_dist_idx)

    peer_group_row = roster[roster["distname"] == primary_district]
    peer_group     = peer_group_row["group"].iloc[0] if not peer_group_row.empty else "G. K-12 / 3501 +"
    en_val = peer_group_row["enrollment"].iloc[0] if not peer_group_row.empty else None
    en_str = f"{en_val:,.0f}" if pd.notna(en_val) and en_val > 0 else "—"
    st.caption(f"Peer group: **{peer_group}** · Enrollment (2024): **{en_str}**")

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
        "👥 Enrollment",
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

    elif section == "👥 Enrollment":
        ind_label = st.selectbox("Chart", [i[2] for i in ENROLLMENT_INDICATORS])

    elif section == "🏛 Revenue Sources":
        rev_chart_labels = [i[2] for i in REVENUE_INDICATORS]
        default_rev_idx = rev_chart_labels.index("Total Spending Per Pupil") if "Total Spending Per Pupil" in rev_chart_labels else 0
        ind_label = st.selectbox("Chart this revenue source", rev_chart_labels, index=default_rev_idx)

    elif section == "👩‍🏫 Staffing Ratios":
        ratio_labels = [i[2] for i in RATIO_INDICATORS]
        ind_label    = st.selectbox("Chart this ratio", ratio_labels)

    elif section == "💵 Staffing Salaries":
        sal_labels = [i[2] for i in SALARY_INDICATORS]
        ind_label  = st.selectbox("Chart this salary", sal_labels)

    elif section == "🏦 Fund Balances":
        fund_labels = [i[2] for i in FUND_INDICATORS]
        default_fund_idx = next(
            (i for i, lbl in enumerate(fund_labels) if "General Fund Balance" in lbl), 0
        )
        ind_label = st.selectbox("Indicator", fund_labels, index=default_fund_idx)

    elif section == "📊 Special Ed":
        vs_labels = [i[2] for i in VITSTAT_INDICATORS]
        ind_label = st.selectbox("Chart this stat", vs_labels)

    chart_height = st.slider("Chart height (px)", 400, 1000, 600, step=50)

# ── Resolve indicator metadata ────────────────────────────────────────────────
all_ind_catalog = (SPENDING_INDICATORS + ENROLLMENT_INDICATORS + RATIO_INDICATORS + SALARY_INDICATORS
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
# Vital Statistics (Revenue / VITSTAT) use release year; each release reports prior-year actual (e.g. 2025 → 2024 data).
is_vitstat_chart = fname == VITSTAT_FILE
x_title = "TGES release year" if is_vitstat_chart else "School Year"
state_avg_series = load_state_avg_series(peer_group, fname, col, scale) if (fname, col) in STATE_AVG_COL else {}
show_value_label = section in ("👥 Enrollment", "📊 Special Ed")
fig = make_chart(stats_df, primary_district, compare_districts,
                 fmt, y_label,
                 title=f"{ind_label}  ·  {primary_district} vs {peer_group}",
                 height=chart_height, x_title=x_title, state_avg_series=state_avg_series or None,
                 show_value_as_label=show_value_label)
st.plotly_chart(fig, use_container_width=True)
if is_vitstat_chart:
    st.caption("Vital Statistics: each point is a TGES release; data are latest actual (e.g. 2025 release = 2024 data).")

# ── Enrollment: table ──────────────────────────────────────────────────────────
if section == "👥 Enrollment":
    st.divider()
    st.subheader(f"{latest_year} Enrollment Ranking")
    st.caption("★ marks selected districts. Rank 1 = smallest enrollment.")
    ranking = make_ranking_table(
        stats_df, all_selected, fmt,
        value_label=ind_label, year=latest_year,
        county_filter=comp_counties if comp_counties else None,
        roster=roster, peers_only=peers_only, subcols_df=None)
    if not ranking.empty:
        rank_fmt_map = {ind_label: fmt}
        st.dataframe(
            ranking.style.apply(lambda row: _style_highlight(row), axis=1),
            use_container_width=True, hide_index=True, height=600,
            column_config=build_col_config(rank_fmt_map),
        )

# ── Spending breakdown (pie + sub-table) ──────────────────────────────────────
if section == "💰 Per Pupil Spending" and ind_label in BREAKDOWN_MAP:
    st.divider()
    st.subheader(f"{latest_year} Spending Breakdown — {primary_district}")
    child_labels = BREAKDOWN_MAP[ind_label]
    bd = load_breakdown(latest_year, child_labels, primary_district, peer_group)
    if not bd.empty:
        _render_spending_breakdown(bd, primary_district, child_labels)

# ── Revenue Sources: table + pie ─────────────────────────────────────────────
if section == "🏛 Revenue Sources":
    st.divider()
    st.subheader(f"{latest_year} Revenue Sources Ranking")
    st.caption("★ marks selected districts. Ranked by selected revenue source (lowest → highest).")

    with st.spinner("Loading revenue data…"):
        rev_multi = load_multi_col_table(latest_year, REVENUE_INDICATORS, peer_group,
                                         peers_only=peers_only)

    if not rev_multi.empty:
        peer_dn = stats_df.loc[latest_year, "peer_distnames"] if latest_year in stats_df.index else set()
        fmt_map = _fmt_map_with_enrollment(REVENUE_INDICATORS, roster)
        col_tbl, col_pie = st.columns([3, 2])
        with col_tbl:
            tbl = make_multi_col_ranking_table(
                rev_multi, all_selected, fmt_map, sort_col="Total Spending Per Pupil",
                county_filter=comp_counties if comp_counties else None,
                roster=roster, peers_only=peers_only, peer_distnames=peer_dn)
            _render_ranking_dataframe(tbl, fmt_map)

        with col_pie:
            _revenue_mix_pie(rev_multi, primary_district, latest_year)

# ── Ranking table ─────────────────────────────────────────────────────────────
if section not in SECTIONS_WITH_DEDICATED_TABLE:
    st.divider()

if section in ("👩‍🏫 Staffing Ratios", "💵 Staffing Salaries"):
    ind_group  = RATIO_INDICATORS if section == "👩‍🏫 Staffing Ratios" else SALARY_INDICATORS
    group_fmt  = "ratio" if section == "👩‍🏫 Staffing Ratios" else "salary"
    col_labels = [i[2] for i in ind_group]

    st.subheader(f"{latest_year} Full Ranking — {section.split()[-1]} ({primary_district} peer group)")
    st.caption("★ marks selected districts. Rank 1 = lowest value.")

    with st.spinner("Loading all columns…"):
        multi_df = load_multi_col_table(latest_year, ind_group, peer_group,
                                        peers_only=peers_only)

    if not multi_df.empty:
        peer_dn = stats_df.loc[latest_year, "peer_distnames"] if latest_year in stats_df.index else set()
        fmt_map = {lbl: group_fmt for lbl in col_labels}
        if "enrollment" in roster.columns:
            fmt_map["Enrollment"] = "int"
        sort_col = "Student:Teacher Ratio" if section == "👩‍🏫 Staffing Ratios" else ind_label
        tbl = make_multi_col_ranking_table(
            multi_df, all_selected, fmt_map, sort_col=sort_col,
            county_filter=comp_counties if comp_counties else None,
            roster=roster, peers_only=peers_only, peer_distnames=peer_dn)
        _render_ranking_dataframe(tbl, fmt_map)

elif section == "📊 Special Ed":
    # Multi-column table sorted by % Students in Special Ed
    st.subheader(f"{latest_year} Special Ed Ranking ({primary_district} peer group)")
    st.caption("★ marks selected districts. Rank 1 = lowest % in Special Ed.")
    with st.spinner("Loading Special Ed data…"):
        multi_df = load_multi_col_table(latest_year, VITSTAT_INDICATORS, peer_group,
                                        peers_only=peers_only)
    if not multi_df.empty:
        peer_dn = stats_df.loc[latest_year, "peer_distnames"] if latest_year in stats_df.index else set()
        fmt_map = _fmt_map_with_enrollment(VITSTAT_INDICATORS, roster)
        tbl = make_multi_col_ranking_table(
            multi_df, all_selected, fmt_map, sort_col="% Students in Special Ed",
            county_filter=comp_counties if comp_counties else None,
            roster=roster, peers_only=peers_only, peer_distnames=peer_dn)
        _render_ranking_dataframe(tbl, fmt_map)

elif section == "🏦 Fund Balances":
    st.subheader(f"{latest_year} Fund Balances Ranking")
    st.caption("★ marks selected districts. Rank 1 = lowest value.")
    with st.spinner("Loading fund balance data…"):
        multi_df = load_multi_col_table(latest_year, FUND_INDICATORS, peer_group,
                                        peers_only=peers_only)
    if not multi_df.empty:
        peer_dn = stats_df.loc[latest_year, "peer_distnames"] if latest_year in stats_df.index else set()
        fmt_map = _fmt_map_with_enrollment(FUND_INDICATORS, roster)
        tbl = make_multi_col_ranking_table(
            multi_df, all_selected, fmt_map, sort_col=ind_label,
            county_filter=comp_counties if comp_counties else None,
            roster=roster, peers_only=peers_only, peer_distnames=peer_dn)
        _render_ranking_dataframe(tbl, fmt_map)

elif section not in SECTIONS_WITH_DEDICATED_TABLE:
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
        # Format value columns for display but keep numeric so sorting works
        rank_fmt_map = {ind_label: fmt}
        for c in ranking.columns:
            if c not in ("Rank", "District") and c not in rank_fmt_map:
                rank_fmt_map[c] = fmt
        st.dataframe(
            ranking.style.apply(lambda row: _style_highlight(row), axis=1),
            use_container_width=True, hide_index=True, height=600,
            column_config=build_col_config(rank_fmt_map),
        )

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "**How to read the chart:** Blue band = IQR (middle 50% of peer districts). "
    "Dotted line = peer median. Numbers on each dot = percentile rank that year. "
    "Red = within IQR · Orange = outside IQR · Dark red = outside top/bottom 10%.")
