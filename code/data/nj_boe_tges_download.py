#!/usr/bin/env python3
"""
Download NJ BOE TGES files for a range of years (2011-2025).

Two distinct download modes determined by what the NJ BOE publishes per year:

  BUNDLE years (2011-2023)
    A single ZIP archive is linked from the main guide index:
      https://www.nj.gov/education/guide/docs/{year}_TGES.zip
    Saved as:  {year}_TGES_raw.zip
    Extracted: {year}/extracted/  (Excel files renamed with _raw suffix)

  INDIVIDUAL years (2024+)
    A dedicated year page exists at:
      https://www.nj.gov/education/guide/{year}tges.shtml
    Up to three files are scraped from that page and saved as:
      {year}_TGES_Installation_Instructions_raw.pdf
      {year}_TGES_Zipped_Excel_files_raw.zip
      {year}_State_Averages_Medians_raw.xlsx
    The ZIP is also extracted and its Excel files renamed with _raw suffix.
"""

from __future__ import annotations

import argparse
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Iterator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}

# 2011-2023: single bundled ZIP on the guide index; no per-year shtml page.
# 2024+: individual year page with PDF + ZIP + XLSX.
BUNDLE_YEAR_CUTOFF = 2024  # first year with an individual year page


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Anchor:
    href: str
    text: str


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_a = False
        self._current_href: str | None = None
        self._text_parts: list[str] = []
        self.anchors: list[Anchor] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = None
        for k, v in attrs:
            if k.lower() == "href" and v:
                href = v.strip()
                break
        if href:
            self._in_a = True
            self._current_href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_a:
            s = data.strip()
            if s:
                self._text_parts.append(s)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a":
            return
        if self._in_a and self._current_href:
            text = " ".join(self._text_parts).strip()
            self.anchors.append(Anchor(href=self._current_href, text=text))
        self._in_a = False
        self._current_href = None
        self._text_parts = []


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _headers(referer: str | None = None) -> dict[str, str]:
    h = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    }
    if referer:
        h["Referer"] = referer
    return h


def _open_with_retries(
    url: str,
    timeout_s: float,
    *,
    referer: str | None,
    retries: int,
    backoff_s: float,
):
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=_headers(referer))
            return urllib.request.urlopen(req, timeout=timeout_s)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in RETRYABLE_HTTP_STATUS and attempt < retries:
                sleep_s = backoff_s * (2 ** (attempt - 1))
                print(
                    f"    retryable HTTP {e.code}; "
                    f"sleeping {sleep_s:.1f}s then retry ({attempt}/{retries})"
                )
                time.sleep(sleep_s)
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            if attempt < retries:
                sleep_s = backoff_s * (2 ** (attempt - 1))
                print(
                    f"    URL error; sleeping {sleep_s:.1f}s "
                    f"then retry ({attempt}/{retries}): {e.reason}"
                )
                time.sleep(sleep_s)
                continue
            raise
    raise RuntimeError(f"Failed to open URL after retries: {url}") from last_err


def _http_get_bytes(url: str, timeout_s: float, *, retries: int, backoff_s: float) -> bytes:
    with _open_with_retries(url, timeout_s, referer=None, retries=retries, backoff_s=backoff_s) as resp:
        return resp.read()


def _download(
    url: str,
    dest: Path,
    timeout_s: float,
    *,
    force: bool,
    referer: str | None,
    retries: int,
    backoff_s: float,
) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"  - exists, skip: {dest.name}")
        return True

    tmp = dest.with_suffix(dest.suffix + ".part")
    if tmp.exists():
        tmp.unlink()

    try:
        with _open_with_retries(
            url, timeout_s, referer=referer, retries=retries, backoff_s=backoff_s
        ) as resp, tmp.open("wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise

    if tmp.stat().st_size == 0:
        tmp.unlink()
        raise RuntimeError(f"Downloaded empty file from {url}")

    tmp.replace(dest)
    print(f"  - downloaded ({dest.stat().st_size // 1024:,} KB): {dest.name}")
    return True


def _download_first(
    urls: Iterable[str],
    dest: Path,
    timeout_s: float,
    *,
    force: bool,
    referer: str | None,
    retries: int,
    backoff_s: float,
) -> str | None:
    """Try each URL in order; return the successful URL, or None if all fail."""
    tried = False
    for url in urls:
        tried = True
        try:
            print(f"  - try: {url}")
            _download(
                url,
                dest=dest,
                timeout_s=timeout_s,
                force=force,
                referer=referer,
                retries=retries,
                backoff_s=backoff_s,
            )
            return url
        except urllib.error.HTTPError as e:
            print(f"    HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            print(f"    URL error: {e.reason}")
        except Exception as e:
            print(f"    error: {e}")
    if not tried:
        print(f"  - warning: no candidates provided for {dest.name}")
    return None


# ---------------------------------------------------------------------------
# File rename / extract helpers
# ---------------------------------------------------------------------------


def _safe_rename(path: Path, new_path: Path) -> Path:
    if new_path == path:
        return path
    if not new_path.exists():
        path.rename(new_path)
        return new_path
    stem = new_path.stem
    suffix = new_path.suffix
    parent = new_path.parent
    for i in range(2, 10_000):
        candidate = parent / f"{stem}__{i}{suffix}"
        if not candidate.exists():
            path.rename(candidate)
            return candidate
    raise RuntimeError(f"Could not find non-colliding name for {new_path}")


def _sanitize_extracted_tree(root: Path) -> None:
    """
    Walk the extraction root and rename every file/dir:
      - spaces -> underscores
      - .xlsx / .xls files get _raw inserted before the extension (if not already present)
    """
    if not root.exists():
        return

    # Rename files first (deepest first so paths remain valid)
    for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if not p.exists() or not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix in {".xlsx", ".xls"}:
            stem = p.stem if p.stem.endswith("_raw") else f"{p.stem}_raw"
            name2 = (stem + suffix).replace(" ", "_")
        else:
            name2 = p.name.replace(" ", "_")
        _safe_rename(p, p.with_name(name2))

    # Then rename directories (deepest first)
    for d in sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda x: len(x.parts),
        reverse=True,
    ):
        if not d.exists():
            continue
        _safe_rename(d, d.with_name(d.name.replace(" ", "_")))


def _extract_zip(zip_path: Path, extract_dir: Path, *, force: bool) -> None:
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    extract_dir.mkdir(parents=True, exist_ok=True)

    marker = extract_dir / ".extracted.ok"
    if marker.exists() and not force:
        print(f"  - already extracted, skip: {extract_dir.name}/")
        return

    print(f"  - extracting to: {extract_dir.relative_to(extract_dir.parent.parent)}/")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)
    marker.write_text(f"ok {time.time()}\n", encoding="utf-8")
    _sanitize_extracted_tree(extract_dir)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _absolutize(base_url: str, href: str) -> str:
    return urllib.parse.urljoin(base_url, href)


def _norm(s: str) -> str:
    return " ".join(s.split()).strip().lower()


def _year_page_url(year: int) -> str:
    return f"https://www.nj.gov/education/guide/{year}tges.shtml"


def _iter_dedup(*lists: list[str]) -> Iterator[str]:
    seen: set[str] = set()
    for lst in lists:
        for u in lst:
            if u and u not in seen:
                seen.add(u)
                yield u


# ---------------------------------------------------------------------------
# BUNDLE years (2011-2023): single {year}_TGES.zip from the guide index
# ---------------------------------------------------------------------------


def _bundle_year_candidates(year: int) -> list[str]:
    base = "https://www.nj.gov/education/guide/docs/"
    return [
        f"{base}{year}_TGES.zip",
    ]


def _download_bundle_year(
    year: int,
    year_dir: Path,
    timeout_s: float,
    *,
    force: bool,
    skip_missing: bool,
    retries: int,
    backoff_s: float,
) -> list[str]:
    zip_dest = year_dir / f"{year}_TGES_raw.zip"
    skipped: list[str] = []

    result = _download_first(
        _bundle_year_candidates(year),
        zip_dest,
        timeout_s,
        force=force,
        referer="https://www.nj.gov/education/guide/",
        retries=retries,
        backoff_s=backoff_s,
    )

    if result is None:
        msg = f"  - MISSING ({year}): {zip_dest.name}"
        if skip_missing:
            print(msg + " — skipping")
            skipped.append(zip_dest.name)
            return skipped
        else:
            raise RuntimeError(
                f"All download candidates failed for {zip_dest.name}. "
                "Use --skip-missing to continue past unavailable files."
            )

    extract_dir = year_dir / "extracted"
    _extract_zip(zip_dest, extract_dir, force=force)
    return skipped


# ---------------------------------------------------------------------------
# INDIVIDUAL years (2024+): scrape year page, download PDF + ZIP + XLSX
# ---------------------------------------------------------------------------


def _find_individual_links(year: int, anchors: list[Anchor]) -> dict[str, list[str]]:
    """
    Classify scraped anchors into pdf / zip / xlsx buckets using link TEXT
    to identify the specific files, not just URL pattern keywords.

    Target link labels on the year pages:
      PDF:  "{year} TGES Installation Instructions"
      ZIP:  "{year} TGES Zipped Excel files"
      XLSX: "State Averages/Medians"  (the statewide group averages file,
             NOT Vital Statistics which also appears on the page)
    """
    base = _year_page_url(year)
    pdfs: list[str] = []
    zips: list[str] = []
    xlsxs: list[str] = []

    for a in anchors:
        href = a.href.strip()
        if not href:
            continue
        abs_url = _absolutize(base, href)
        h = _norm(href)
        t = _norm(a.text)

        if ".pdf" in h:
            # Match: "{year} TGES Installation Instructions"
            if ("install" in t and "tges" in t) or ("install" in h and "tges" in h):
                pdfs.append(abs_url)

        if ".zip" in h:
            # Match: "{year} TGES Zipped Excel files"
            if ("zip" in t and "tges" in t) or ("zip" in h and "tges" in h):
                zips.append(abs_url)

        if ".xlsx" in h:
            # Match only "State Averages/Medians" — identified by link text.
            # Specifically exclude Vital Statistics (different file, different purpose).
            if ("state" in t and "average" in t) or ("state" in h and "group" in h and "average" in h):
                xlsxs.append(abs_url)

    def dedupe(urls: list[str]) -> list[str]:
        seen: set[str] = set()
        return [u for u in urls if not (u in seen or seen.add(u))]  # type: ignore[func-returns-value]

    return {"pdf": dedupe(pdfs), "zip": dedupe(zips), "xlsx": dedupe(xlsxs)}


def _individual_fallback_candidates(year: int) -> dict[str, list[str]]:
    base = f"https://www.nj.gov/education/guide/docs/{year}/"
    yy = str(year)[2:]

    pdf_candidates = [
        f"{base}{year}_TGES_Installation_Instructions.pdf",
        f"{base}TGES_Installation_Instructions.pdf",
        f"{base}TGES{year}_Installation_Instructions.pdf",
        f"{base}TGES{yy}_Installation_Instructions.pdf",
        f"{base}{year}%20TGES%20Installation%20Instructions.pdf",
        f"https://www.nj.gov/education/guide/{year}%20TGES%20Installation%20Instructions.pdf",
    ]

    zip_candidates = [
        # Confirmed: 2024 uses "TGES24_Zipped.zip" (2-digit year)
        #            2025 uses "TGES2025_Zipped.zip" (4-digit year)
        f"{base}TGES{yy}_Zipped.zip",
        f"{base}TGES{year}_Zipped.zip",
        f"{base}TGES{yy}_Zipped_Excel_Files.zip",
        f"{base}TGES{year}_Zipped_Excel_Files.zip",
        f"{base}TGES{yy}.zip",
        f"{base}TGES{year}.zip",
    ]

    xlsx_candidates = [
        # Confirmed patterns (2024: State_and_Group_Averages_2024.xlsx,
        #                     2025: State_and_Group_Averages_TGES2025.xlsx)
        f"{base}State_and_Group_Averages_TGES{year}.xlsx",
        f"{base}State_and_Group_Averages_{year}.xlsx",
        f"{base}State_and_Group_Averages_TGES{yy}.xlsx",
        f"{base}State_and_Group_Averages.xlsx",
    ]

    return {"pdf": pdf_candidates, "zip": zip_candidates, "xlsx": xlsx_candidates}


def _download_individual_year(
    year: int,
    year_dir: Path,
    timeout_s: float,
    *,
    force: bool,
    skip_missing: bool,
    retries: int,
    backoff_s: float,
) -> list[str]:
    page_url = _year_page_url(year)
    page_links: dict[str, list[str]] = {"pdf": [], "zip": [], "xlsx": []}
    try:
        html = _http_get_bytes(page_url, timeout_s=timeout_s, retries=retries, backoff_s=backoff_s)
        anchors = _AnchorParser()
        anchors.feed(html.decode("utf-8", errors="replace"))
        page_links = _find_individual_links(year, anchors.anchors)
    except Exception as e:
        print(f"  - warning: could not parse year page: {e}")

    fallback = _individual_fallback_candidates(year)

    pdf_dest = year_dir / f"{year}_TGES_Installation_Instructions_raw.pdf"
    zip_dest = year_dir / f"{year}_TGES_Zipped_Excel_files_raw.zip"
    xlsx_dest = year_dir / f"{year}_State_Averages_Medians_raw.xlsx"

    skipped: list[str] = []

    def _get(kind: str, dest: Path) -> bool:
        result = _download_first(
            _iter_dedup(page_links[kind], fallback[kind]),
            dest,
            timeout_s,
            force=force,
            referer=page_url,
            retries=retries,
            backoff_s=backoff_s,
        )
        if result is None:
            msg = f"  - MISSING ({year}): {dest.name}"
            if skip_missing:
                print(msg + " — skipping")
                skipped.append(dest.name)
                return False
            else:
                raise RuntimeError(
                    f"All download candidates failed for {dest.name}. "
                    "Use --skip-missing to continue past unavailable files."
                )
        return True

    _get("pdf", pdf_dest)
    zip_ok = _get("zip", zip_dest)
    _get("xlsx", xlsx_dest)

    if zip_ok and zip_dest.exists():
        _extract_zip(zip_dest, year_dir / "extracted", force=force)

    return skipped


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    # code/data/nj_boe_tges_download.py -> parents[2] == project root
    return Path(__file__).resolve().parents[2]


def _download_year(
    year: int,
    outdir: Path,
    timeout_s: float,
    *,
    force: bool,
    skip_missing: bool,
    retries: int,
    backoff_s: float,
    delay_s: float,
) -> list[str]:
    year_dir = outdir / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n== {year} ==")

    kwargs = dict(
        timeout_s=timeout_s,
        force=force,
        skip_missing=skip_missing,
        retries=retries,
        backoff_s=backoff_s,
    )

    if year < BUNDLE_YEAR_CUTOFF:
        skipped = _download_bundle_year(year, year_dir, **kwargs)
    else:
        skipped = _download_individual_year(year, year_dir, **kwargs)

    if delay_s > 0:
        time.sleep(delay_s)

    return skipped


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Download NJ BOE TGES files (2011-2025).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--start-year", type=int, default=2011)
    p.add_argument("--end-year", type=int, default=2025)
    p.add_argument(
        "--outdir",
        type=Path,
        default=_project_root() / "data" / "TGES",
        help="Root output directory",
    )
    p.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds")
    p.add_argument("--retries", type=int, default=5, help="Max retries per URL on transient errors")
    p.add_argument("--backoff", type=float, default=1.0, help="Exponential backoff base (seconds)")
    p.add_argument("--delay", type=float, default=0.25, help="Polite delay between years (seconds)")
    p.add_argument(
        "--skip-missing",
        action="store_true",
        default=True,
        help="Warn and continue when a file cannot be found (default: on)",
    )
    p.add_argument(
        "--strict",
        dest="skip_missing",
        action="store_false",
        help="Abort immediately if any file cannot be downloaded",
    )
    p.add_argument("--force", action="store_true", help="Re-download and re-extract even if files exist")
    args = p.parse_args(argv)

    if args.start_year > args.end_year:
        p.error("--start-year must be <= --end-year")

    print(f"Output directory: {args.outdir}")
    args.outdir.mkdir(parents=True, exist_ok=True)

    all_skipped: dict[int, list[str]] = {}
    for year in range(args.start_year, args.end_year + 1):
        skipped = _download_year(
            year,
            outdir=args.outdir,
            timeout_s=args.timeout,
            force=args.force,
            skip_missing=args.skip_missing,
            retries=max(1, args.retries),
            backoff_s=max(0.1, args.backoff),
            delay_s=max(0.0, args.delay),
        )
        if skipped:
            all_skipped[year] = skipped

    print("\nDone.")
    if all_skipped:
        print("\nFiles not found (may need manual download):")
        for yr, files in sorted(all_skipped.items()):
            for f in files:
                print(f"  {yr}: {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
