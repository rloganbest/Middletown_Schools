#!/usr/bin/env python3
"""
Square footage per child by level (Elementary, Middle, High).

Enrollment: extracted from AMR Schedule of Audited Enrollments.
Square footage: from ACFR J-18 (when available) or data/facilities/level_sqft.csv.

Run: python code/analysis/sqft_per_child.py
"""
from pathlib import Path
import re

import pandas as pd
import pdfplumber

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
AMR_DIR = PROJECT_ROOT / "data" / "AMR"
ACFR_DIR = PROJECT_ROOT / "data" / "ACFR"
FACILITIES_DIR = PROJECT_ROOT / "data" / "facilities"

# Schools misclassified in J-18 (e.g. "Middletown" triggers "Middle")
LEVEL_OVERRIDE = {"Middletown Village": "Elementary"}

# Grade → level mapping
ELEMENTARY_GRADES = ("K", "1", "2", "3", "4", "5")
MIDDLE_GRADES = ("6", "7", "8")
HIGH_GRADES = ("9", "10", "11", "12")

GRADE_ALIASES = {
    "Kindergarten Full Day": "K",
    "Kindergarten": "K",
    "One": "1",
    "Two": "2",
    "Three": "3",
    "Four": "4",
    "Five": "5",
    "Six": "6",
    "Seven": "7",
    "Eight": "8",
    "Nine": "9",
    "Ten": "10",
    "Eleven": "11",
    "Twelve": "12",
}


def extract_enrollment_by_grade(pdf_path: Path) -> dict[str, int] | None:
    """Parse enrollment by grade from AMR Schedule of Audited Enrollments.
    Returns dict like {"K": 597, "1": 569, ...} or None if not found.

    The enrollment table has numbers in order: K,1,2,...,12 (each appears twice).
    We extract the first occurrence of each run of 3-digit numbers (100-999)
    before "Subtotal" to get regular K-12 enrollment.
    """
    with pdfplumber.open(pdf_path) as pdf:
        enrollment_text = ""
        for page in pdf.pages:
            raw = page.extract_text() or ""
            if "TCIRTSID" in raw:  # Rotated DISTRICT
                raw = "\n".join(line[::-1] for line in raw.split("\n"))
            enrollment_text += " " + raw

    # Find all 3-4 digit numbers (100-9999) that look like enrollment
    all_nums = re.findall(r"\b([1-9]\d{2,3})\b", enrollment_text)
    # Take first 13 unique values in order (K through 12) - they appear in pairs
    seen = set()
    grade_nums = []
    for n in all_nums:
        val = int(n)
        if 100 <= val <= 999 and val not in seen:
            seen.add(val)
            grade_nums.append(val)
            if len(grade_nums) >= 13:
                break

    if len(grade_nums) < 12:
        return None

    grades = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
    return dict(zip(grades[: len(grade_nums)], grade_nums))


def enrollment_by_level(grade_enrollment: dict[str, int]) -> dict[str, int]:
    """Aggregate grade enrollment into Elementary, Middle, High."""
    elem = sum(grade_enrollment.get(g, 0) for g in ELEMENTARY_GRADES)
    mid = sum(grade_enrollment.get(g, 0) for g in MIDDLE_GRADES)
    high = sum(grade_enrollment.get(g, 0) for g in HIGH_GRADES)
    return {"Elementary": elem, "Middle": mid, "High": high}


def sqft_by_level_from_j18(acfr_year: int) -> dict[str, int] | None:
    """Sum square footage by level from ACFR J-18. Returns None if not found."""
    j18_path = ACFR_DIR / str(acfr_year) / "acfr_j18_school_building.csv"
    if not j18_path.exists():
        return None
    df = pd.read_csv(j18_path)
    if "Square_Feet" not in df.columns or "Level" not in df.columns:
        return None
    # Apply level overrides
    def level_for(row):
        lvl = LEVEL_OVERRIDE.get(row["School"], row["Level"])
        return lvl if lvl in ("Elementary", "Middle", "High") else None

    df["Level"] = df.apply(level_for, axis=1)
    df = df.dropna(subset=["Level"])
    df["sqft_num"] = pd.to_numeric(df["Square_Feet"].astype(str).str.replace(",", ""), errors="coerce")
    by_level = df.groupby("Level")["sqft_num"].sum().to_dict()
    return {k: int(v) for k, v in by_level.items() if v > 0}


def main():
    # Use most recent AMR for enrollment
    years = sorted([int(d.name) for d in AMR_DIR.iterdir() if d.is_dir() and d.name.isdigit()], reverse=True)
    if not years:
        print("No AMR data found.")
        return

    latest_year = years[0]
    amr_path = AMR_DIR / str(latest_year) / "middletown_amr.pdf"
    if not amr_path.exists():
        print(f"AMR not found: {amr_path}")
        return

    grade_enroll = extract_enrollment_by_grade(amr_path)
    if not grade_enroll:
        print("Could not extract enrollment by grade from AMR.")
        return

    by_level = enrollment_by_level(grade_enroll)
    print(f"\nEnrollment by level (FY {latest_year}, from AMR):")
    for level, n in by_level.items():
        print(f"  {level}: {n:,}")

    # Square footage: prefer ACFR J-18, else level_sqft.csv
    sqft_by_level = sqft_by_level_from_j18(latest_year)
    j18_year = latest_year if sqft_by_level else None
    if sqft_by_level is None:
        acfr_years = sorted([int(d.name) for d in ACFR_DIR.iterdir() if d.is_dir() and d.name.isdigit()], reverse=True)
        for yr in acfr_years:
            sqft_by_level = sqft_by_level_from_j18(yr)
            if sqft_by_level:
                j18_year = yr
                break
    if sqft_by_level:
        print(f"\nSquare footage from ACFR J-18 (FY {j18_year}):")
        for level, sqft in sqft_by_level.items():
            print(f"  {level}: {sqft:,} sq ft")
    else:
        sqft_path = FACILITIES_DIR / "level_sqft.csv"
        if not sqft_path.exists():
            sqft_path.write_text("level,total_sq_ft\nElementary,\nMiddle,\nHigh,\n")
            print(f"\nCreated {sqft_path} — please add total square footage for each level.")
        sqft_df = pd.read_csv(sqft_path)
        sqft_by_level = {}
        for _, row in sqft_df.iterrows():
            sqft = pd.to_numeric(row.get("total_sq_ft", row.get("sq_ft")), errors="coerce")
            if pd.notna(sqft) and sqft > 0:
                sqft_by_level[row["level"]] = int(sqft)
        if not sqft_by_level:
            print("\nNo square footage data. Add values to level_sqft.csv or run ACFR extraction.")

    # Merge enrollment with square footage
    result = []
    for level in ["Elementary", "Middle", "High"]:
        enroll = by_level.get(level, 0)
        sqft = sqft_by_level.get(level) if sqft_by_level else None
        sqft_per = sqft / enroll if enroll and sqft and sqft > 0 else None
        result.append({
            "level": level,
            "enrollment": enroll,
            "total_sq_ft": int(sqft) if sqft else None,
            "sq_ft_per_child": round(sqft_per, 1) if sqft_per else None,
        })

    df = pd.DataFrame(result)
    print("\n" + df.to_string(index=False))

    out_path = FACILITIES_DIR / "sqft_per_child.csv"
    df.to_csv(out_path, index=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
