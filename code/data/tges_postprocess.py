#!/usr/bin/env python3
"""
Post-process TGES extracted CSVs and XLSX: rename headers per TGES Installation Instructions.

Reference: https://www.nj.gov/education/guide/docs/2025/TGES_Installation_Instructions.pdf

Run after unzip. Processes all CSV files and State_and_Group_Averages XLSX in the extraction directory.
"""
from __future__ import annotations

import csv
import shutil
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None

# ---------------------------------------------------------------------------
# Common columns (all files)
# ---------------------------------------------------------------------------
COMMON = {
    "GROUP": "Operating_Type",
    "Group": "Operating_Type",
    "CONAME": "County",
    "Coname": "County",
    "CO": "County_Code",
    "DIST": "District_Code",
    "Dist": "District_Code",
    "DISTNAME": "District_Name",
    "Distname": "District_Name",
    "distname": "District_Name",
    "BOTY": "Budget_Operating_Type",
    "DM": "District_Type",
}

# ---------------------------------------------------------------------------
# CSG1AA_AVGS - Total Spending Per Pupil
# ---------------------------------------------------------------------------
CSG1AA_AVGS = {
    **COMMON,
    "EXP11A": "Total_Expenditures_Yr1",
    "ADE11A": "Avg_Daily_Enrollment_Yr1",
    "PP11A": "Per_Pupil_Expenditures_Yr1",
    "RK11A": "Per_Pupil_Rank_Yr1",
    "EXP21A": "Total_Expenditures_Yr2",
    "ADE21A": "Avg_Daily_Enrollment_Yr2",
    "PP21A": "Per_Pupil_Expenditures_Yr2",
    "RK21A": "Per_Pupil_Rank_Yr2",
}

# ---------------------------------------------------------------------------
# Indicator file structure (TGES spec)
# ---------------------------------------------------------------------------
# Pattern: (PP|RK|PCT|E) + Year(1,2,3) + X where X = indicator number (e.g. 1, 2, 8A, 10).
# So PP11 = Per pupil Year 1 Ind 1, RK21 = Rank Year 2 Ind 1, PCT31 = Pct Year 3 Ind 1.
# Indicators 1, 2, 4, 5, 6, 8, 8a, 10, 12, 13, 15: PP1X–3X, RK1X–3X, PCT1X–3X; Ind 1 also has E11, E21, E31.
# Indicators 3, 7, 9, 11: same plus SBA/SBB/SBC (pct salaries/benefits).
# ---------------------------------------------------------------------------
INDICATOR_NAMES = {
    1: "Budgetary_Per_Pupil_Cost",
    2: "Total_Classroom_Instruction",
    3: "Classroom_Salaries_Benefits",
    4: "Classroom_Supplies_Textbooks",
    5: "Classroom_Purchased_Services",
    6: "Total_Support_Services",
    7: "Support_Services_Salaries_Benefits",
    8: "Administrative_Costs",
    8.1: "Legal_Services",  # 8A
    9: "Administration_Salaries_Benefits",
    10: "Operations_Maintenance_Plant",
    11: "Operations_Maintenance_Salaries_Benefits",
    12: "Food_Service_Cost",
    13: "Extracurricular_Costs",
    14: "Employee_Benefits_Pct_Salaries",
    15: "Total_Equipment_Cost",
    16: "Student_Teacher_Ratio",
    17: "Student_Support_Staff_Ratio",
    18: "Student_Administrator_Ratio",
    19: "Faculty_Administrator_Ratio",
    20: "General_Fund_Balance",
    21: "Excess_Unreserved_Fund_Balance",
}

# Indicators 1, 2, 4, 5, 6, 8, 8a, 10, 12, 13, 15: PP, RK, PCT (and E11/E21/E31 for Ind 1 only).
# Indicators 3, 7, 9, 11: PP, RK, PCT, and SBA/SBB/SBC (% of Total Salaries and Benefits for Yr1/Yr2/Yr3).
INDICATORS_WITH_SB = {3, 7, 9, 11}


def _indicator_col_map(ind_num: float) -> dict[str, str]:
    """Build column map for indicator file (CSG1–CSG21).
    Spec: (PP|RK|PCT|E) + Year(1,2,3) + X → PP1X=Per pupil Yr1 Ind X, RK1X=Rank, PCT1X=Pct of budgetary cost; E11/E21/E31 only for Ind 1.
    """
    suffix = "8A" if ind_num == 8.1 else str(int(ind_num))
    m = {**COMMON}
    for yr in (1, 2, 3):
        m[f"PP{yr}{suffix}"] = f"Per_Pupil_Yr{yr}"
        m[f"RK{yr}{suffix}"] = f"Rank_Yr{yr}"
        m[f"PCT{yr}{suffix}"] = f"Pct_Budgetary_Cost_Yr{yr}"
        if ind_num in INDICATORS_WITH_SB:
            sb = "SBA" if yr == 1 else "SBB" if yr == 2 else "SBC"
            m[f"{sb}{suffix}"] = f"Pct_Salaries_Benefits_Yr{yr}"
    if ind_num == 1:
        m["E11"] = "Enrollment_Yr1"
        m["E21"] = "Enrollment_Yr2"
        m["E31"] = "Enrollment_Yr3"
    return m


# Pre-built indicator maps (Ind 1 uses full map so PP, RK, PCT, E are all renamed)
CSG1_MAP = _indicator_col_map(1)
CSG2_MAP = _indicator_col_map(2)
CSG3_MAP = _indicator_col_map(3)
CSG4_MAP = _indicator_col_map(4)
CSG5_MAP = _indicator_col_map(5)
CSG6_MAP = _indicator_col_map(6)
CSG7_MAP = _indicator_col_map(7)
CSG8_MAP = _indicator_col_map(8)
CSG8A_MAP = _indicator_col_map(8.1)
CSG9_MAP = _indicator_col_map(9)
CSG10_MAP = _indicator_col_map(10)
CSG11_MAP = _indicator_col_map(11)
CSG12_MAP = _indicator_col_map(12)
CSG13_MAP = _indicator_col_map(13)
# Indicator 14: % of Total Salaries only (PP114/PP214/PP314 = Actual Yr1/Yr2, Budgeted Yr3)
CSG14_MAP = {
    **COMMON,
    "PP114": "Pct_Total_Salaries_Yr1",
    "PP214": "Pct_Total_Salaries_Yr2",
    "PP314": "Pct_Total_Salaries_Yr3",
}
# Indicator 15: Per pupil only (PP115/PP215/PP315 = Actual Yr1/Yr2, Budgeted Yr3)
CSG15_MAP = _indicator_col_map(15)

# Indicator 16: STRAT00/01, RK00/01, SALT00/01, RKSAL00/01 (Student/Teacher ratio & salary, Yr2/Yr3)
CSG16_MAP = {
    **COMMON,
    "STRAT0016": "Student_Teacher_Ratio_Yr2",
    "RK0016": "Ratio_Rank_Yr2",
    "SALT0016": "Teacher_Median_Salary_Yr2",
    "RKSAL0016": "Salary_Rank_Yr2",
    "STRAT0116": "Student_Teacher_Ratio_Yr3",
    "RK0116": "Ratio_Rank_Yr3",
    "SALT0116": "Teacher_Median_Salary_Yr3",
    "RKSAL0116": "Salary_Rank_Yr3",
}
# Ind 17: spec doc may say "SSRAT0014"/"SSRRAT0117" (typos); actual files use SSRAT0017/SSRAT0117
CSG17_MAP = {
    **COMMON,
    "SSRAT0017": "Student_Support_Ratio_Yr2",
    "SSRAT0117": "Student_Support_Ratio_Yr3",
    "SSRAT0014": "Student_Support_Ratio_Yr2",  # spec typo alias
    "SSRRAT0117": "Student_Support_Ratio_Yr3",  # spec typo alias
    "RK0017": "Ratio_Rank_Yr2",
    "RK0117": "Ratio_Rank_Yr3",
    "SALS0017": "Support_Staff_Salary_Yr2",
    "SALS0117": "Support_Staff_Salary_Yr3",
    "RKSAL0017": "Salary_Rank_Yr2",
    "RKSAL0117": "Salary_Rank_Yr3",
}
# Indicator 18: SARAT00/01, RK00/01, SALAM00/01, RKSAL00/01 (Student/Admin ratio & salary)
CSG18_MAP = {
    **COMMON,
    "SARAT0018": "Student_Admin_Ratio_Yr2",
    "SARAT0118": "Student_Admin_Ratio_Yr3",
    "RK0018": "Ratio_Rank_Yr2",
    "RK0118": "Ratio_Rank_Yr3",
    "SALAM0018": "Admin_Salary_Yr2",
    "SALAM0118": "Admin_Salary_Yr3",
    "RKSAL0018": "Salary_Rank_Yr2",
    "RKSAL0118": "Salary_Rank_Yr3",
}
# Indicator 19: FARAT00/01, RK00/01 only (Faculty/Admin ratio; no salary)
CSG19_MAP = {
    **COMMON,
    "FARAT0019": "Faculty_Admin_Ratio_Yr2",
    "FARAT0119": "Faculty_Admin_Ratio_Yr3",
    "RK0019": "Ratio_Rank_Yr2",
    "RK0119": "Ratio_Rank_Yr3",
}
# Indicator 20: General Fund Balance and Actual (Yr1/Yr2 only)
CSG20_MAP = {
    **COMMON,
    "DE120": "General_Fund_Balance_Yr1",
    "DE220": "Actual_Yr1",
    "DE320": "General_Fund_Balance_Yr2",
    "DE420": "Actual_Yr2",
}
# Indicator 21: Excess (Yr1/Yr2 only)
CSG21_MAP = {
    **COMMON,
    "EX121": "Excess_Yr1",
    "EX221": "Excess_Yr2",
}

# VITSTAT_TOTAL – Vital Statistics (all Year 2 / latest actual)
# PP3vv, STPCT01vv, LTPCT01vv, FDPCT01vv, TUPCT01vv, FBPCT01vv, OTPCT01vv,
# STRAT01vv, SSRAT01vv, SARAT01vv, PCTSEvv
VITSTAT_MAP = {
    **COMMON,
    "pp3vv": "Total_Spending_Per_Pupil",
    "stpct01vv": "State_Share_Pct_Revenue",
    "ltpct01vv": "Local_Share_Pct_Revenue",
    "fdpct01vv": "Federal_Share_Pct_Revenue",
    "tupct01vv": "Tuition_Pct_Revenue",
    "fbpct01vv": "Free_Balance_Pct_Revenue",
    "otpct01vv": "Other_Revenue_Pct",
    "strat01vv": "Student_Teacher_Ratio",
    "ssrat01vv": "Student_Support_Ratio",
    "sarat01vv": "Student_Admin_Ratio",
    "pctsevv": "Special_Ed_Pct_Enrollment",
}

# SUMYR – Summary files: IND1–IND13, IND15 (costs); IND16a/b–IND18a/b, IND19 (staffing); ENROLL, etc.
SUMYR_MAP = {
    **COMMON,
    "ind1": "ind1_Budgetary_Cost",
    "ind2": "ind2_Classroom_Instruction",
    "ind3": "ind3_Classroom_Salaries",
    "ind4": "ind4_Supplies_Textbooks",
    "ind5": "ind5_Purchased_Services",
    "ind6": "ind6_Support_Services",
    "ind7": "ind7_Support_Salaries",
    "ind8": "ind8_Administrative",
    "ind9": "ind9_Admin_Salaries",
    "ind10": "ind10_Operations_Maintenance",
    "ind11": "ind11_Ops_Maint_Salaries",
    "ind12": "ind12_Food_Service",
    "ind13": "ind13_Extracurricular",
    "ind15": "ind15_Equipment",
    "ind16a": "ind16a_Student_Teacher_Ratio",
    "ind16b": "ind16b_Teacher_Salary",
    "ind17a": "ind17a_Student_Support_Ratio",
    "ind17b": "ind17b_Support_Salary",
    "ind18a": "ind18a_Student_Admin_Ratio",
    "ind18b": "ind18b_Admin_Salary",
    "ind19": "ind19_Faculty_Admin_Ratio",
    "ENROLL": "Enrollment",
    "OPTYPE": "Operating_Type_Code",
    "DFG": "DFG",
    "ABBOTT": "Abbott",
    "FLAG": "Flag",
    "County": "County_Name",
}

# SUMMARY - consolidated format (csg1PP1, csg2pct1, etc.). Use INDICATOR_NAMES for decoded column prefixes.
def _summary_ind_label(ind: int | float) -> str:
    """Return decoded indicator name for Summary file columns (e.g. 8.1 -> Legal_Services)."""
    return INDICATOR_NAMES.get(ind, f"Ind{ind}")


# For already-processed Summary files: rewrite Ind* prefix to decoded name (try longest first)
SUMMARY_IND_PREFIXES = [
    ("Ind8a", _summary_ind_label(8.1)),
    *[(f"Ind{i}", _summary_ind_label(i)) for i in (10, 11, 12, 13, 14, 15, 16, 17, 18, 19)],
    *[(f"Ind{i}", _summary_ind_label(i)) for i in range(1, 10)],
]


def _decode_summary_ind_prefix(header: str) -> str:
    """If header starts with Ind8a_, Ind1_, etc., replace with decoded indicator name."""
    for prefix, label in SUMMARY_IND_PREFIXES:
        if header.startswith(prefix + "_"):
            return label + "_" + header[len(prefix) + 1:]
    return header


def _summary_col_map() -> dict[str, str]:
    m = dict(COMMON)
    # Pattern: csg{N}{PP|RK|pct|sba|sbb|sbc}{1|2|3} -> {IndicatorName}_{Metric}_Yr{yr}
    for ind in range(1, 16):
        label = _summary_ind_label(ind)
        for yr in (1, 2, 3):
            m[f"csg{ind}PP{yr}"] = f"{label}_Per_Pupil_Yr{yr}"
            m[f"csg{ind}RK{yr}"] = f"{label}_Rank_Yr{yr}"
            m[f"csg{ind}pct{yr}"] = f"{label}_Pct_Budget_Yr{yr}"
        if ind in (3, 7, 9, 11):
            m[f"csg{ind}sba"] = f"{label}_Pct_Salaries_Yr1"
            m[f"csg{ind}sbb"] = f"{label}_Pct_Salaries_Yr2"
            m[f"csg{ind}sbc"] = f"{label}_Pct_Salaries_Yr3"
    for ind in (16, 17, 18, 19):
        label = _summary_ind_label(ind)
        m[f"csg{ind}STRAT00"] = f"{label}_Ratio_Yr2"
        m[f"csg{ind}STRAT01"] = f"{label}_Ratio_Yr3"
        m[f"csg{ind}SALT00"] = f"{label}_Salary_Yr2"
        m[f"csg{ind}SALT01"] = f"{label}_Salary_Yr3"
        m[f"csg{ind}RK00"] = f"{label}_Rank_Yr2"
        m[f"csg{ind}RK01"] = f"{label}_Rank_Yr3"
        m[f"csg{ind}RKSAL00"] = f"{label}_Salary_Rank_Yr2"
        m[f"csg{ind}RKSAL01"] = f"{label}_Salary_Rank_Yr3"
    label17 = _summary_ind_label(17)
    m["csg17SSRAT00"] = f"{label17}_Ratio_Yr2"
    m["csg17SSRAT01"] = f"{label17}_Ratio_Yr3"
    m["csg17SALS00"] = f"{label17}_Support_Salary_Yr2"
    m["csg17SALS01"] = f"{label17}_Support_Salary_Yr3"
    label18 = _summary_ind_label(18)
    m["csg18SARAT00"] = f"{label18}_Ratio_Yr2"
    m["csg18SARAT01"] = f"{label18}_Ratio_Yr3"
    m["csg18SALAM00"] = f"{label18}_Admin_Salary_Yr2"
    m["csg18SALAM01"] = f"{label18}_Admin_Salary_Yr3"
    label19 = _summary_ind_label(19)
    m["csg19FARAT00"] = f"{label19}_Ratio_Yr2"
    m["csg19FARAT01"] = f"{label19}_Ratio_Yr3"
    # Indicator 8a (Legal Services) – decoded as Legal_Services_*
    label8a = _summary_ind_label(8.1)
    m["csg8aPP1"] = f"{label8a}_Per_Pupil_Yr1"
    m["csg8aPP2"] = f"{label8a}_Per_Pupil_Yr2"
    m["csg8aPP3"] = f"{label8a}_Per_Pupil_Yr3"
    m["csg8aRK1"] = f"{label8a}_Rank_Yr1"
    m["csg8aRK2"] = f"{label8a}_Rank_Yr2"
    m["csg8aRK3"] = f"{label8a}_Rank_Yr3"
    m["csg8apct1"] = f"{label8a}_Pct_Yr1"
    m["csg8apct2"] = f"{label8a}_Pct_Yr2"
    m["csg8apct3"] = f"{label8a}_Pct_Yr3"
    m["csg1aEXP1"] = "Total_Expenditures_Yr1"
    m["csg1aADE1"] = "Avg_Daily_Enrollment_Yr1"
    m["csg1aPP1"] = "Per_Pupil_Expenditures_Yr1"
    m["csg1aRK1"] = "Per_Pupil_Rank_Yr1"
    m["csg1aEXP2"] = "Total_Expenditures_Yr2"
    m["csg1aADE2"] = "Avg_Daily_Enrollment_Yr2"
    m["csg1aPP2"] = "Per_Pupil_Expenditures_Yr2"
    m["csg1aRK2"] = "Per_Pupil_Rank_Yr2"
    return m


def _year_from_extract_dir(extract_root: Path) -> int | None:
    """Infer TGES download year from path (e.g. .../2025 or .../2025/extracted -> 2025)."""
    for name in (extract_root.name, extract_root.parent.name):
        try:
            y = int(name)
            if 2011 <= y <= 2030:
                return y
        except (ValueError, AttributeError):
            continue
    return None


def _apply_year_labels(headers: list[str], year: int) -> list[str]:
    """Replace Yr1, Yr2, Yr3 in header strings with actual year labels."""
    # For download year N: Yr1=N-2, Yr2=N-1, Yr3=N_budgeted
    yr1 = str(year - 2)
    yr2 = str(year - 1)
    yr3 = f"{year}_budgeted"
    out = []
    for h in headers:
        s = h.replace("Yr1", yr1).replace("Yr2", yr2).replace("Yr3", yr3)
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# File renames: original name -> readable name (for display in file browser)
# ---------------------------------------------------------------------------
FILE_RENAMES: dict[str, str] = {
    "CSG1AA_AVGS.CSV": "Total Spending Per Pupil.csv",
    "CSG1AA_AVGS.csv": "Total Spending Per Pupil.csv",
    "CSG1.CSV": "Indicator 1-Budgetary Per Pupil Cost.csv",
    "CSG1.csv": "Indicator 1-Budgetary Per Pupil Cost.csv",
    "CSG2.CSV": "Indicator 2-Total Classroom Instruction.csv",
    "CSG2.csv": "Indicator 2-Total Classroom Instruction.csv",
    "CSG3.CSV": "Indicator 3-Classroom Salaries and Benefits.csv",
    "CSG3.csv": "Indicator 3-Classroom Salaries and Benefits.csv",
    "CSG4.CSV": "Indicator 4-Classroom General Supplies and Textbooks.csv",
    "CSG4.csv": "Indicator 4-Classroom General Supplies and Textbooks.csv",
    "CSG5.CSV": "Indicator 5-Classroom Purchased Services and Other.csv",
    "CSG5.csv": "Indicator 5-Classroom Purchased Services and Other.csv",
    "CSG6.CSV": "Indicator 6-Total Support Services.csv",
    "CSG6.csv": "Indicator 6-Total Support Services.csv",
    "CSG7.CSV": "Indicator 7-Support Services Salaries and Benefits.csv",
    "CSG7.csv": "Indicator 7-Support Services Salaries and Benefits.csv",
    "CSG8.CSV": "Indicator 8-Total Administrative Costs per Pupil.csv",
    "CSG8.csv": "Indicator 8-Total Administrative Costs per Pupil.csv",
    "CSG8A.CSV": "Indicator 8A-Legal Services per Pupil.csv",
    "CSG8A.csv": "Indicator 8A-Legal Services per Pupil.csv",
    "CSG8a.CSV": "Indicator 8A-Legal Services per Pupil.csv",
    "CSG8a.csv": "Indicator 8A-Legal Services per Pupil.csv",
    "CSG9.CSV": "Indicator 9-Administration Salaries and Benefits.csv",
    "CSG9.csv": "Indicator 9-Administration Salaries and Benefits.csv",
    "CSG10.CSV": "Indicator 10-Operations and Maintenance of Plant.csv",
    "CSG10.csv": "Indicator 10-Operations and Maintenance of Plant.csv",
    "CSG11.CSV": "Indicator 11-Operations and Maintenance of Plant Salaries and Benefits.csv",
    "CSG11.csv": "Indicator 11-Operations and Maintenance of Plant Salaries and Benefits.csv",
    "CSG12.CSV": "Indicator 12-Food Service Cost per Pupil and Benefits.csv",
    "CSG12.csv": "Indicator 12-Food Service Cost per Pupil and Benefits.csv",
    "CSG13.CSV": "Indicator 13-Extracurricular Costs per Pupil and Benefits.csv",
    "CSG13.csv": "Indicator 13-Extracurricular Costs per Pupil and Benefits.csv",
    "CSG14.CSV": "Indicator 14-Personal Services - Employee Benefits.csv",
    "CSG14.csv": "Indicator 14-Personal Services - Employee Benefits.csv",
    "CSG15.CSV": "Indicator 15-Total Equipment Cost per Pupil.csv",
    "CSG15.csv": "Indicator 15-Total Equipment Cost per Pupil.csv",
    "CSG16.CSV": "Indicator 16-Ratio of Students to Teachers, Median Salary.csv",
    "CSG16.csv": "Indicator 16-Ratio of Students to Teachers, Median Salary.csv",
    "CSG17.CSV": "Indicator 17-Ratio of Students to Special Service, Median Salary.csv",
    "CSG17.csv": "Indicator 17-Ratio of Students to Special Service, Median Salary.csv",
    "CSG18.CSV": "Indicator 18-Ratio of Students to Administrators, Median Salary.csv",
    "CSG18.csv": "Indicator 18-Ratio of Students to Administrators, Median Salary.csv",
    "CSG19.CSV": "Indicator 19-Ratio of Faculty to Administrators.csv",
    "CSG19.csv": "Indicator 19-Ratio of Faculty to Administrators.csv",
    "CSG20.CSV": "Indicator 20-Budgeted General Fund Balance vs Actual (used).csv",
    "CSG20.csv": "Indicator 20-Budgeted General Fund Balance vs Actual (used).csv",
    "CSG21.CSV": "Indicator 21-Excess Unreserved General Fund Balances.csv",
    "CSG21.csv": "Indicator 21-Excess Unreserved General Fund Balances.csv",
    "SUMMARY.CSV": "Summary - State Average and Median for each operating type.csv",
    "VITSTAT_TOTAL.CSV": "Summary of Vital Statistics.csv",
    "VITSTAT_TOTAL.csv": "Summary of Vital Statistics.csv",
    "VitStat_Total.CSV": "Summary of Vital Statistics.csv",
    "VitStat_Total.csv": "Summary of Vital Statistics.csv",
    "Summary.csv": "Summary - State Average and Median for each operating type.csv",
    "SUMYR3.CSV": "Summary - 2022-23 Actual Costs, Regular Districts.csv",
    "SUMYR3.csv": "Summary - 2022-23 Actual Costs, Regular Districts.csv",
    "SUMYR3C.CSV": "Summary - 2022-23 Actual Costs, Charter Schools.csv",
    "SUMYR3C.csv": "Summary - 2022-23 Actual Costs, Charter Schools.csv",
    "SUMYR4.CSV": "Summary - 2023-24 Actual Costs, Regular Districts.csv",
    "SUMYR4.csv": "Summary - 2023-24 Actual Costs, Regular Districts.csv",
    "SUMYR4C.CSV": "Summary - 2023-24 Actual Costs, Charter Schools.csv",
    "SUMYR4C.csv": "Summary - 2023-24 Actual Costs, Charter Schools.csv",
    "SUMYR5.CSV": "Summary - 2024-25 Original Budget Totals, Regular Districts.csv",
    "SUMYR5.csv": "Summary - 2024-25 Original Budget Totals, Regular Districts.csv",
    "SUMYR5C.CSV": "Summary - 2024-25 Original Budget Totals, Charter Districts.csv",
    "SUMYR5C.csv": "Summary - 2024-25 Original Budget Totals, Charter Districts.csv",
    # Fix previously-renamed file (Charter Schools -> Charter Districts)
    "Summary - 2024-25 Original Budget Totals, Charter Schools.csv": "Summary - 2024-25 Original Budget Totals, Charter Districts.csv",
}
EXCEL_RENAMES: dict[str, str] = {
    "Detail_FY23_raw": "Total Spending Per Pupil Details FY23.xlsx",
    "Detail_FY24_raw": "Total Spending Per Pupil Details FY24.xlsx",
    "October2024_DRTRS_raw": "Bus Utilization Efficiency Ratings.xlsx",
}


def _get_file_rename(path: Path) -> str | None:
    """Return new filename for path if it should be renamed, else None."""
    name = path.name
    # CSV: exact or case-insensitive match
    if name in FILE_RENAMES:
        return FILE_RENAMES[name]
    for k, v in FILE_RENAMES.items():
        if k.upper() == name.upper():
            return v
    # Excel: match stem (exact, to avoid renaming duplicate copies like _raw__2)
    if path.suffix.lower() in (".xlsx", ".xls"):
        stem = path.stem
        if stem in EXCEL_RENAMES:
            return EXCEL_RENAMES[stem]
    return None


FILE_MAPS: dict[str, dict[str, str]] = {
    "CSG1AA_AVGS.CSV": CSG1AA_AVGS,
    "CSG1.CSV": CSG1_MAP,
    "CSG2.CSV": CSG2_MAP,
    "CSG3.CSV": CSG3_MAP,
    "CSG4.CSV": CSG4_MAP,
    "CSG5.CSV": CSG5_MAP,
    "CSG6.CSV": CSG6_MAP,
    "CSG7.CSV": CSG7_MAP,
    "CSG8.CSV": CSG8_MAP,
    "CSG8A.CSV": CSG8A_MAP,
    "CSG9.CSV": CSG9_MAP,
    "CSG10.CSV": CSG10_MAP,
    "CSG11.CSV": CSG11_MAP,
    "CSG12.CSV": CSG12_MAP,
    "CSG13.CSV": CSG13_MAP,
    "CSG14.CSV": CSG14_MAP,
    "CSG15.CSV": CSG15_MAP,
    "CSG16.CSV": CSG16_MAP,
    "CSG17.CSV": CSG17_MAP,
    "CSG18.CSV": CSG18_MAP,
    "CSG19.CSV": CSG19_MAP,
    "CSG20.CSV": CSG20_MAP,
    "CSG21.CSV": CSG21_MAP,
    "VITSTAT_TOTAL.CSV": VITSTAT_MAP,
    "VitStat_Total.CSV": VITSTAT_MAP,
    "SUMMARY.CSV": _summary_col_map(),
    "Summary - State Average and Median for each operating type.csv": _summary_col_map(),
    "SUMYR3.CSV": SUMYR_MAP,
    "SUMYR3C.CSV": SUMYR_MAP,
    "SUMYR4.CSV": SUMYR_MAP,
    "SUMYR4C.CSV": SUMYR_MAP,
    "SUMYR5.CSV": SUMYR_MAP,
    "SUMYR5C.CSV": SUMYR_MAP,
}


def _get_col_map(path: Path) -> dict[str, str] | None:
    name = path.name
    if name in FILE_MAPS:
        return FILE_MAPS[name]
    for k, v in FILE_MAPS.items():
        if k.upper() == name.upper():
            return v
    return None


def _lookup_header(col_map: dict[str, str], header: str) -> str:
    """Return mapped header name; exact match then case-insensitive."""
    out = col_map.get(header) or col_map.get(header.strip())
    if out is not None:
        return out
    hu = header.upper()
    for k, v in col_map.items():
        if k.upper() == hu:
            return v
    return header


def _read_csv_headers(path: Path) -> list[str] | None:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        try:
            return next(reader)
        except StopIteration:
            return None


def _map_headers(headers: list[str], col_map: dict[str, str], year: int | None, decode_summary: bool) -> list[str]:
    out = [_lookup_header(col_map, h) for h in headers]
    if year is not None:
        out = _apply_year_labels(out, year)
    if decode_summary:
        out = [_decode_summary_ind_prefix(h) for h in out]
    return out


def _write_csv(path: Path, headers: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def _process_csv(
    path: Path,
    col_map: dict[str, str],
    year: int | None = None,
    *,
    decode_summary_inds: bool = False,
) -> bool:
    """Rewrite CSV headers from col_map; apply year labels and optional Ind* decode. Returns True if file was changed."""
    headers = _read_csv_headers(path)
    if headers is None:
        return False
    new_headers = _map_headers(headers, col_map, year, decode_summary_inds)
    if new_headers == headers:
        return False
    with path.open("r", encoding="utf-8", errors="replace") as f:
        rows = list(csv.reader(f))[1:]
    _write_csv(path, new_headers, rows)
    return True


def _safe_sheet_basename(sheet_name: str) -> str:
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in str(sheet_name))


def _xlsx_sheet_to_csv(
    xl: pd.ExcelFile,
    sheet_name: str,
    out_path: Path,
    summary_map: dict[str, str],
    year: int | None,
) -> bool:
    df = pd.read_excel(xl, sheet_name=sheet_name)
    if df.empty or len(df.columns) == 0:
        return False
    new_cols = [summary_map.get(str(c), str(c)) for c in df.columns]
    if year is not None:
        new_cols = _apply_year_labels(new_cols, year)
    df.columns = new_cols
    df.to_csv(out_path, index=False)
    return True


def _process_state_averages_xlsx(
    xlsx_path: Path, summary_map: dict[str, str], year: int | None = None
) -> int:
    """Convert State_and_Group_Averages XLSX sheets to CSV with readable headers. Returns sheet count."""
    if pd is None:
        return 0
    try:
        xl = pd.ExcelFile(xlsx_path, engine="openpyxl")
    except Exception:
        return 0
    base = xlsx_path.stem
    count = 0
    for sheet_name in xl.sheet_names:
        safe = _safe_sheet_basename(sheet_name)
        csv_path = xlsx_path.parent / f"{base}_{safe}.csv"
        if _xlsx_sheet_to_csv(xl, sheet_name, csv_path, summary_map, year):
            count += 1
    return count


def _move_file_to_root(path: Path, root: Path) -> None:
    dest = root / path.name
    if dest == path:
        return
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        for i in range(2, 10_000):
            dest = root / f"{stem}__{i}{suffix}"
            if not dest.exists():
                break
    shutil.move(str(path), str(dest))


def _remove_empty_dirs(root: Path) -> None:
    dirs = sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True)
    for d in dirs:
        if d.exists() and not any(d.iterdir()):
            d.rmdir()


def _flatten_to_root(root: Path) -> None:
    """Move all files from subdirectories into root; then remove empty dirs."""
    to_move = [p for p in root.rglob("*") if p.is_file() and p.parent != root]
    for p in to_move:
        _move_file_to_root(p, root)
    _remove_empty_dirs(root)


def _iter_csv_paths(root: Path):
    """Yield each CSV file under root once (handles both .CSV and .csv)."""
    seen: set[Path] = set()
    for p in root.rglob("*.CSV"):
        if p.is_file() and p not in seen:
            seen.add(p)
            yield p
    for p in root.rglob("*.csv"):
        if p.is_file() and p not in seen:
            seen.add(p)
            yield p


def _is_summary_csv(path: Path) -> bool:
    n = path.name
    return n in ("SUMMARY.CSV", "Summary.csv") or "Summary - State Average" in n


def _maybe_rename_file(path: Path, new_name: str | None) -> bool:
    if not new_name or path.name == new_name:
        return False
    path.rename(path.parent / new_name)
    return True


def _process_csvs_with_maps(extract_root: Path, year: int | None) -> int:
    count = 0
    for path in _iter_csv_paths(extract_root):
        col_map = _get_col_map(path)
        if not col_map:
            continue
        if _process_csv(path, col_map, year, decode_summary_inds=_is_summary_csv(path)):
            count += 1
            print(f"  - renamed headers: {path.relative_to(extract_root)}")
            new_name = _get_file_rename(path)
            if _maybe_rename_file(path, new_name):
                print(f"    -> {new_name}")
    return count


def _apply_csv_file_renames(extract_root: Path) -> int:
    count = 0
    for path in _iter_csv_paths(extract_root):
        new_name = _get_file_rename(path)
        if _maybe_rename_file(path, new_name):
            count += 1
            print(f"  - renamed: {path.name} -> {new_name}")
    return count


def _apply_xlsx_renames(extract_root: Path) -> int:
    count = 0
    for path in extract_root.rglob("*.xlsx"):
        if not path.is_file():
            continue
        new_name = _get_file_rename(path)
        if _maybe_rename_file(path, new_name):
            count += 1
            print(f"  - renamed: {path.name} -> {new_name}")
    return count


def _convert_state_averages_xlsx(extract_root: Path, year: int | None) -> int:
    summary_map = _summary_col_map()
    count = 0
    for path in extract_root.rglob("State_and_Group_Averages*.xlsx"):
        if not path.is_file() or path.stem.endswith("_raw"):
            continue
        n = _process_state_averages_xlsx(path, summary_map, year)
        if n > 0:
            count += n
            print(f"  - converted {n} sheet(s) to CSV: {path.relative_to(extract_root)}")
    return count


def _process_extracted_dir(extract_root: Path, year: int | None = None) -> int:
    if year is None:
        year = _year_from_extract_dir(extract_root)
    count = 0
    count += _process_csvs_with_maps(extract_root, year)
    count += _apply_csv_file_renames(extract_root)
    count += _apply_xlsx_renames(extract_root)
    count += _convert_state_averages_xlsx(extract_root, year)
    _flatten_to_root(extract_root)
    return count


def postprocess_extracted(extract_dir: Path, year: int | None = None) -> int:
    """
    Post-process all TGES CSVs in extract_dir. Renames headers per Installation Instructions.
    Replaces Yr1/Yr2/Yr3 with year labels (e.g. 2025 -> 2023, 2024, 2025_budgeted).
    Returns number of files processed.
    """
    if not extract_dir.exists():
        return 0
    return _process_extracted_dir(extract_dir, year)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Post-process TGES extracted CSVs: rename headers, replace Yr1/Yr2/Yr3 with year labels"
    )
    p.add_argument("extract_dir", type=Path, nargs="?", help="Year directory (default: all data/TGES/<year>)")
    p.add_argument("--year", type=int, help="TGES year (for Yr1/Yr2/Yr3 labels; default: inferred from path)")
    args = p.parse_args()

    root = Path(__file__).resolve().parents[2] / "data" / "TGES"
    if args.extract_dir:
        d = Path(args.extract_dir).resolve()
        dirs = [d] if d.is_dir() else []
    else:
        dirs = [d for d in root.iterdir() if d.is_dir() and d.name.isdigit()]

    total = 0
    for d in dirs:
        try:
            label = d.relative_to(root)
        except ValueError:
            label = d
        print(f"\nProcessing: {label}")
        n = postprocess_extracted(d, year=args.year)
        total += n
    print(f"\nDone. Processed {total} files.")
