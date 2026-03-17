#!/usr/bin/env python3
"""
Extract tables from Middletown ACFR PDF.
- Exhibit J-12: Ratios of Overlapping Governmental Activities Debt
- Exhibit J-13: Legal Debt Margin Information (vertical text)
- Exhibit J-18: School Building Information (pages 189-190)
"""
import argparse
import re
import tempfile
from pathlib import Path

import pandas as pd
import pdfplumber

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "ACFR"


def find_exhibit_page(pdf, exhibit_name: str) -> int | None:
    """Find 0-based page index containing exhibit (e.g. 'J-12', 'J-13')."""
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if exhibit_name in text and "EXHIBIT" in text.upper():
            return i
        # J-13 has vertical text: "31-J" (J-13 reversed), "NIGRAM" (MARGIN reversed)
        if exhibit_name == "J-13" and ("31-J" in text or "NIGRAM" in text):
            return i
        # J-18 has vertical text: "81-J" (J-18 reversed), "GNIDLIUB" (BUILDING reversed)
        if exhibit_name == "J-18" and ("81-J" in text or "GNIDLIUB" in text):
            return i
    return None


def unreverse_num(s: str) -> str:
    """Reverse comma-separated groups: 000,094,16 -> 16,094,000"""
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return ",".join(reversed(parts))


def unreverse_year(s: str) -> str:
    """2102 -> 2012"""
    if re.match(r"^\d{4}$", str(s)):
        return s[::-1]
    return s


def unreverse_pct(s: str) -> str:
    """%05.31 -> 31.05% (vertical text: swap parts before/after decimal)"""
    m = re.search(r"(\d+)\.?(\d*)", s)
    if m:
        a, b = m.group(1), m.group(2) or "0"
        return f"{b}.{a}%"
    return s


def _parse_j12_from_text(text: str) -> pd.DataFrame:
    """Parse Exhibit J-12 table from extracted text."""
    rows = [
        ["Governmental Unit", "Outstanding Debt", "Percentage Applicable", "Estimated Share of Overlapping Debt"],
        ["Debt Repaid With Property Taxes:", "", "", ""],
    ]
    # Township of Middletown $ 70,290,902 100.0% $ 70,290,902
    m = re.search(
        r"Township of Middletown\s+\$\s*([\d,]+)\s+([\d.]+%)\s+\$\s*([\d,]+)",
        text,
    )
    if m:
        rows.append(["Township of Middletown", f"${m.group(1)}", m.group(2), f"${m.group(3)}"])
    rows.append(["Other Debt:", "", "", ""])
    # County of Monmouth - Township's Share (%) 1,643,106,400 8.5000% 139,664,044
    m = re.search(
        r"County of Monmouth[^0-9]*([\d,]+)\s+([\d.]+%)\s+([\d,]+)",
        text,
    )
    if m:
        rows.append(
            [
                "County of Monmouth - Township's Share",
                f"${m.group(1)}",
                m.group(2),
                f"${m.group(3)}",
            ]
        )
    # Township of Middletown Sewerage Authority 8,222,469 100.0% 8,222,469
    m = re.search(
        r"Township of Middletown Sewerage Authority\s+([\d,]+)\s+([\d.]+%)\s+([\d,]+)",
        text,
    )
    if m:
        rows.append(
            [
                "Township of Middletown Sewerage Authority",
                f"${m.group(1)}",
                m.group(2),
                f"${m.group(3)}",
            ]
        )
    # Subtotal, Overlapping Debt 218,177,415
    m = re.search(r"Subtotal, Overlapping Debt\s+([\d,]+)", text)
    if m:
        rows.append(["Subtotal, Overlapping Debt", "", "", f"${m.group(1)}"])
    # Middletown Township School District Direct Debt 31,987,308
    m = re.search(r"Middletown Township School District Direct Debt\s+([\d,]+)", text)
    if m:
        rows.append(["Middletown Township School District Direct Debt", f"${m.group(1)}", "", ""])
    # Total Direct & Overlapping Debt $ 250,164,723
    m = re.search(r"Total Direct & Overlapping Debt\s+\$\s*([\d,]+)", text)
    if m:
        rows.append(["Total Direct & Overlapping Debt", "", "", f"${m.group(1)}"])
    return pd.DataFrame(rows[1:], columns=rows[0])


def extract_j12(pdf, page_idx: int) -> pd.DataFrame:
    """Exhibit J-12: Ratios of Overlapping Governmental Activities Debt"""
    text = pdf.pages[page_idx].extract_text() or ""
    return _parse_j12_from_text(text)


def extract_j13(pdf, page_idx: int) -> pd.DataFrame:
    """Exhibit J-13: Legal Debt Margin Information (vertical text in PDF)"""
    page = pdf.pages[page_idx]
    words = page.extract_words()

    nums = [(w["text"], w["x0"], w["top"]) for w in words if re.match(r"^[\d,.\$%]+$", w["text"])]

    # Years (6102 -> 2016), sorted by vertical position
    year_pos = [(unreverse_year(t), y) for t, x, y in nums if re.match(r"^\d{4}$", t)]
    year_pos = [(yr, y) for yr, y in year_pos if 2011 <= int(yr) <= 2030]
    year_pos.sort(key=lambda a: (a[1], a[0]))
    seen = set()
    years = []
    for yr, _ in year_pos:
        if yr not in seen:
            seen.add(yr)
            years.append(yr)
    years = years[:15]

    # Debt limits: x~133-142, values 1M-100M (e.g. 86,029,000)
    debt_limits = []
    for t, x, y in sorted(nums, key=lambda a: a[2]):
        if not re.match(r"^[\d,]+$", t) or "," not in t or x < 133 or x > 142:
            continue
        ur = unreverse_num(t)
        try:
            val = int(ur.replace(",", ""))
        except ValueError:
            continue
        if 1_000_000 <= val <= 100_000_000:
            debt_limits.append(ur)

    # Net total debt: x~118-128, values 50M-1B (e.g. 114,012,019)
    net_totals = []
    for t, x, y in sorted(nums, key=lambda a: a[2]):
        if not re.match(r"^\d{1,3}(,\d{3})+$", t) or x < 118 or x > 128:
            continue
        ur = unreverse_num(t)
        try:
            val = int(ur.replace(",", ""))
        except ValueError:
            continue
        if 50_000_000 <= val <= 1_000_000_000:
            net_totals.append(ur)

    # Margins (sorted by position)
    pct_words = [(w["text"], w["top"]) for w in words if "%" in w.get("text", "")]
    pct_words.sort(key=lambda a: a[1])
    margins = [unreverse_pct(t) for t, _ in pct_words[:15]]

    n = max(len(years), len(debt_limits), len(net_totals), len(margins))
    rows = []
    for i in range(n):
        row = [
            years[i] if i < len(years) else "",
            debt_limits[i] if i < len(debt_limits) else "",
            net_totals[i] if i < len(net_totals) else "",
            margins[i] if i < len(margins) else "",
        ]
        rows.append(row)

    df = pd.DataFrame(
        rows,
        columns=[
            "Fiscal Year",
            "Debt Limit ($)",
            "Applicable Net Total Debt ($)",
            "Legal Debt Margin %",
        ],
    )
    if not df.empty and "Fiscal Year" in df.columns:
        df = df[df["Fiscal Year"].astype(str).str.match(r"^\d{4}$", na=False)]
        df = df.sort_values("Fiscal Year").reset_index(drop=True)
    return df


def _create_rotated_j18_pdf(pdf_path: Path, start_page_idx: int) -> Path:
    """Create temp PDF with J-18 pages rotated +90° for readable extraction."""
    if fitz is None:
        raise ImportError("PyMuPDF (pymupdf) required for J-18 rotation. pip install pymupdf")
    doc = fitz.open(pdf_path)
    new_doc = fitz.open()
    end = min(start_page_idx + 2, len(doc))
    new_doc.insert_pdf(doc, from_page=start_page_idx, to_page=end - 1)
    for i in range(len(new_doc)):
        new_doc[i].set_rotation(90)  # +90° makes vertical text horizontal
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    new_doc.save(tmp)
    new_doc.close()
    doc.close()
    return Path(tmp)


def _parse_j18_from_text(text: str) -> pd.DataFrame:
    """Parse J-18 school blocks from rotated text. Format:
    School Name (year):
    Square Feet val val ...
    Capacity val val ...
    Enrollment (a)? val val ...
    """
    years = list(range(2016, 2026))  # 2016-2025
    # Pattern: "School Name (year):" then Square Feet, Capacity, Enrollment lines
    block_pat = re.compile(
        r"([A-Za-z\s]+(?:Elementary|Middle|High)?)\s*\((\d{4})\):?\s*"
        r"Square Feet\s+([\d,\s]+)\s*"
        r"Capacity\s+([\d,\s]+)\s*"
        r"Enrollment\s*(?:\(a\))?\s*([\d,\s]+)",
        re.DOTALL,
    )
    rows = []
    for m in block_pat.finditer(text):
        school_raw, year_built, sqft_line, cap_line, enroll_line = m.groups()
        school = school_raw.strip().rstrip(":")
        # Determine level from school name (check High before Middle: "Middletown High School")
        if "Elementary" in school:
            level = "Elementary"
        elif "High" in school:
            level = "High"
        elif "Middle" in school or "Middle School" in school:
            level = "Middle"
        else:
            level = ""
        # Extract numbers (handle "44,000 44,000" or "4 4,000" glitches)
        sqft_vals = re.findall(r"[\d,]+", sqft_line)
        sq_ft = sqft_vals[0] if sqft_vals else ""
        cap_vals = re.findall(r"[\d,]+", cap_line)
        capacity = cap_vals[0] if cap_vals else ""
        # Enrollment: merge split numbers (e.g. "3 33" -> 333, "1 186" -> 1186)
        enroll_raw = re.findall(r"\d+", enroll_line)
        enroll_vals = []
        i = 0
        while i < len(enroll_raw) and len(enroll_vals) < len(years):
            s = enroll_raw[i]
            # Try merging 1-2 digit with next to form 3-4 digit enrollment
            if len(s) <= 2 and i + 1 < len(enroll_raw):
                nxt = enroll_raw[i + 1]
                merged = s + nxt
                if 100 <= int(merged) <= 9999:
                    enroll_vals.append(merged)
                    i += 2
                    continue
            if 50 <= int(s) <= 9999:
                enroll_vals.append(s)
            i += 1
        # PDF columns are 2025, 2024, ..., 2016 (left to right); reverse to match years
        enroll_vals_ordered = list(reversed(enroll_vals)) if len(enroll_vals) == len(years) else enroll_vals
        enroll_by_year = {y: enroll_vals_ordered[i] if i < len(enroll_vals_ordered) else "" for i, y in enumerate(years)}
        row = [school, level, year_built, sq_ft, capacity] + [
            enroll_by_year[y] for y in years
        ]
        rows.append(row)
    cols = ["School", "Level", "Year_Built", "Square_Feet", "Capacity"] + [
        f"Enrollment_{y}" for y in years
    ]
    return pd.DataFrame(rows, columns=cols)


def extract_j18(pdf_path: Path, start_page_idx: int) -> pd.DataFrame:
    """Exhibit J-18: School Building Information. Rotates pages +90° then extracts."""
    tmp_path = _create_rotated_j18_pdf(pdf_path, start_page_idx)
    try:
        with pdfplumber.open(tmp_path) as pdf:
            text = ""
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
        return _parse_j18_from_text(text)
    finally:
        tmp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Extract ACFR tables (J-12, J-13) from Middletown PDF")
    parser.add_argument("--year", type=int, default=2025, help="ACFR year (default: 2025)")
    parser.add_argument("--pdf", type=Path, help="Override PDF path")
    args = parser.parse_args()

    pdf_path = args.pdf or (DATA_DIR / str(args.year) / "middletown_acfr.pdf")
    output_dir = DATA_DIR / str(args.year)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        return

    with pdfplumber.open(pdf_path) as pdf:
        j12_idx = find_exhibit_page(pdf, "J-12")
        j13_idx = find_exhibit_page(pdf, "J-13")

        if j12_idx is None:
            print("Exhibit J-12 not found")
        else:
            df12 = extract_j12(pdf, j12_idx)
            out12 = output_dir / "acfr_j12_overlapping_debt.csv"
            df12.to_csv(out12, index=False)
            print(f"Saved: {out12} ({len(df12)} rows)")

        if j13_idx is None:
            print("Exhibit J-13 not found")
        else:
            df13 = extract_j13(pdf, j13_idx)
            out13 = output_dir / "acfr_j13_legal_debt_margin.csv"
            df13.to_csv(out13, index=False)
            print(f"Saved: {out13} ({len(df13)} rows)")

        j18_idx = find_exhibit_page(pdf, "J-18")
        if j18_idx is None:
            print("Exhibit J-18 not found")
        else:
            df18 = extract_j18(pdf_path, j18_idx)
            out18 = output_dir / "acfr_j18_school_building.csv"
            df18.to_csv(out18, index=False)
            print(f"Saved: {out18} ({len(df18)} rows)")

    print(f"\nExtraction complete. Output: {output_dir}")


if __name__ == "__main__":
    main()
