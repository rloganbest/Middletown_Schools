#!/usr/bin/env python3
"""
Download NJ BOE TGES files (2011-2025).

  BUNDLE (2011-2023): One ZIP from guide index → {year}/.
  INDIVIDUAL (2024+): Year page → PDF, ZIP, XLSX → {year}/, ZIP extracted flat.
"""

from __future__ import annotations

import argparse
import shutil
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
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
BUNDLE_YEAR_CUTOFF = 2024
GUIDE_URL = "https://www.nj.gov/education/guide/"
DOCS_URL = "https://www.nj.gov/education/guide/docs/"

# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Anchor:
    href: str
    text: str


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_a = False
        self._current_href: str | None = None
        self._text_parts: list[str] = []
        self.anchors: list[Anchor] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((v.strip() for k, v in attrs if k.lower() == "href" and v), None)
        if href:
            self._in_a = True
            self._current_href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_a and data.strip():
            self._text_parts.append(data.strip())

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
# HTTP
# ---------------------------------------------------------------------------


def _request_headers(referer: str | None = None) -> dict[str, str]:
    h = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    }
    if referer:
        h["Referer"] = referer
    return h


def _open_url(
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
            req = urllib.request.Request(url, headers=_request_headers(referer))
            return urllib.request.urlopen(req, timeout=timeout_s)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in RETRYABLE_HTTP_STATUS and attempt < retries:
                sleep_s = backoff_s * (2 ** (attempt - 1))
                print(f"    HTTP {e.code}; sleep {sleep_s:.1f}s retry ({attempt}/{retries})")
                time.sleep(sleep_s)
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            if attempt < retries:
                sleep_s = backoff_s * (2 ** (attempt - 1))
                print(f"    URL error; sleep {sleep_s:.1f}s retry ({attempt}/{retries}): {e.reason}")
                time.sleep(sleep_s)
                continue
            raise
    raise RuntimeError(f"Failed after {retries} retries: {url}") from last_err


def _download_to(path: Path, url: str, timeout_s: float, *, referer: str | None, retries: int, backoff_s: float, force: bool) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0 and not force:
        print(f"  - exists, skip: {path.name}")
        return True
    tmp = path.with_suffix(path.suffix + ".part")
    if tmp.exists():
        tmp.unlink()
    try:
        with _open_url(url, timeout_s, referer=referer, retries=retries, backoff_s=backoff_s) as resp:
            with tmp.open("wb") as f:
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
        raise RuntimeError(f"Empty file: {url}")
    tmp.replace(path)
    print(f"  - downloaded ({path.stat().st_size // 1024:,} KB): {path.name}")
    return True


def _download_first(urls: Iterable[str], dest: Path, timeout_s: float, *, force: bool, referer: str | None, retries: int, backoff_s: float) -> str | None:
    for url in urls:
        try:
            print(f"  - try: {url}")
            _download_to(dest, url, timeout_s, referer=referer, retries=retries, backoff_s=backoff_s, force=force)
            return url
        except urllib.error.HTTPError as e:
            print(f"    HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            print(f"    URL error: {e.reason}")
        except Exception as e:
            print(f"    error: {e}")
    return None


# ---------------------------------------------------------------------------
# Extract & sanitize
# ---------------------------------------------------------------------------


def _safe_rename(path: Path, new_path: Path) -> Path:
    if new_path == path:
        return path
    if not new_path.exists():
        path.rename(new_path)
        return new_path
    for i in range(2, 10_000):
        candidate = new_path.parent / f"{new_path.stem}__{i}{new_path.suffix}"
        if not candidate.exists():
            path.rename(candidate)
            return candidate
    raise RuntimeError(f"Cannot rename (collision): {new_path}")


def _flatten_single_subdir(root: Path) -> None:
    """If root has exactly one child directory, move its contents into root."""
    skip = {".extracted.ok", ".part"}
    children = [p for p in root.iterdir() if p.name not in skip and not p.name.endswith(".part")]
    if len(children) != 1 or not children[0].is_dir():
        return
    sub = children[0]
    for p in sub.iterdir():
        dest = root / p.name
        if not dest.exists():
            p.rename(dest)
    try:
        sub.rmdir()
    except OSError:
        pass


def _sanitize_name(path: Path, *, is_excel: bool = False) -> str:
    name = path.name.replace(" ", "_")
    if is_excel and not path.stem.endswith("_raw"):
        name = path.stem.replace(" ", "_") + "_raw" + path.suffix
    return name


def _sanitize_tree(root: Path) -> None:
    if not root.exists():
        return
    for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if not p.is_file():
            continue
        is_excel = p.suffix.lower() in (".xlsx", ".xls")
        new_name = _sanitize_name(p, is_excel=is_excel)
        if new_name != p.name:
            _safe_rename(p, p.with_name(new_name))
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda x: len(x.parts), reverse=True):
        if d.exists():
            new_name = d.name.replace(" ", "_")
            if new_name != d.name:
                _safe_rename(d, d.with_name(new_name))


def _run_postprocess(year_dir: Path) -> None:
    tges_pp = Path(__file__).resolve().parents[2] / "code" / "data" / "tges_postprocess.py"
    if not tges_pp.exists():
        return
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("tges_postprocess", tges_pp)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        n = mod.postprocess_extracted(year_dir)
        if n > 0:
            print(f"  - post-processed {n} CSV(s)")
    except Exception:
        pass


def _extract_zip(zip_path: Path, out_dir: Path, *, force: bool) -> None:
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    marker = out_dir / ".extracted.ok"
    if marker.exists() and not force:
        print(f"  - already extracted, skip: {out_dir.name}/")
        return
    print(f"  - extracting to: {out_dir.relative_to(out_dir.parent)}/")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(out_dir)
    _flatten_single_subdir(out_dir)
    marker.write_text(f"ok {time.time()}\n", encoding="utf-8")
    _sanitize_tree(out_dir)
    _run_postprocess(out_dir)


# ---------------------------------------------------------------------------
# URLs & link parsing
# ---------------------------------------------------------------------------


def _absolutize(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, href)


def _norm(s: str) -> str:
    return " ".join(s.split()).strip().lower()


def _year_page_url(year: int) -> str:
    return f"{GUIDE_URL}{year}tges.shtml"


def _dedupe(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    return [u for u in urls if u and (u not in seen and not seen.add(u))]  # type: ignore[func-returns-value]


def _iter_dedup(*lists: list[str]) -> Iterator[str]:
    seen: set[str] = set()
    for lst in lists:
        for u in lst:
            if u and u not in seen:
                seen.add(u)
                yield u


# ---------------------------------------------------------------------------
# Bundle years (2011-2023)
# ---------------------------------------------------------------------------


def _bundle_zip_url(year: int) -> str:
    return f"{DOCS_URL}{year}_TGES.zip"


def _download_bundle_year(year: int, year_dir: Path, *, timeout_s: float, force: bool, skip_missing: bool, retries: int, backoff_s: float) -> list[str]:
    zip_dest = year_dir / f"{year}_TGES_raw.zip"
    url = _download_first(
        [_bundle_zip_url(year)],
        zip_dest,
        timeout_s,
        force=force,
        referer=GUIDE_URL,
        retries=retries,
        backoff_s=backoff_s,
    )
    if url is None:
        print(f"  - MISSING ({year}): {zip_dest.name} — skipping")
        if skip_missing:
            return [zip_dest.name]
        raise RuntimeError(f"All download candidates failed for {zip_dest.name}. Use --skip-missing to continue.")
    _extract_zip(zip_dest, year_dir, force=force)
    return []


# ---------------------------------------------------------------------------
# Individual years (2024+)
# ---------------------------------------------------------------------------


def _find_links(year: int, anchors: list[Anchor]) -> dict[str, list[str]]:
    base = _year_page_url(year)
    pdfs: list[str] = []
    zips: list[str] = []
    xlsxs: list[str] = []
    for a in anchors:
        href = a.href.strip()
        if not href:
            continue
        url = _absolutize(base, href)
        h, t = _norm(href), _norm(a.text)
        if ".pdf" in h and "install" in t and "tges" in t:
            pdfs.append(url)
        if ".zip" in h and "zip" in t and "tges" in t:
            zips.append(url)
        if ".xlsx" in h and ("state" in t and "average" in t or "state" in h and "group" in h and "average" in h):
            xlsxs.append(url)
    return {"pdf": _dedupe(pdfs), "zip": _dedupe(zips), "xlsx": _dedupe(xlsxs)}


def _fallback_urls(year: int) -> dict[str, list[str]]:
    base = f"{DOCS_URL}{year}/"
    yy = str(year)[2:]
    return {
        "pdf": [
            f"{base}{year}_TGES_Installation_Instructions.pdf",
            f"{base}TGES_Installation_Instructions.pdf",
            f"{base}TGES{year}_Installation_Instructions.pdf",
            f"{base}TGES{yy}_Installation_Instructions.pdf",
        ],
        "zip": [
            f"{base}TGES{yy}_Zipped.zip",
            f"{base}TGES{year}_Zipped.zip",
            f"{base}TGES{yy}_Zipped_Excel_Files.zip",
            f"{base}TGES{year}_Zipped_Excel_Files.zip",
        ],
        "xlsx": [
            f"{base}State_and_Group_Averages_TGES{year}.xlsx",
            f"{base}State_and_Group_Averages_{year}.xlsx",
            f"{base}State_and_Group_Averages_TGES{yy}.xlsx",
        ],
    }


def _download_asset(
    kind: str,
    dest: Path,
    page_url: str,
    page_links: dict[str, list[str]],
    fallback: dict[str, list[str]],
    *,
    timeout_s: float,
    force: bool,
    retries: int,
    backoff_s: float,
) -> bool:
    urls = _iter_dedup(page_links[kind], fallback[kind])
    url = _download_first(urls, dest, timeout_s, force=force, referer=page_url, retries=retries, backoff_s=backoff_s)
    return url is not None


def _download_individual_year(
    year: int,
    year_dir: Path,
    *,
    timeout_s: float,
    force: bool,
    skip_missing: bool,
    retries: int,
    backoff_s: float,
) -> list[str]:
    page_url = _year_page_url(year)
    page_links: dict[str, list[str]] = {"pdf": [], "zip": [], "xlsx": []}
    try:
        with _open_url(page_url, timeout_s, referer=None, retries=retries, backoff_s=backoff_s) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        parser = _AnchorParser()
        parser.feed(html)
        page_links = _find_links(year, parser.anchors)
    except Exception as e:
        print(f"  - warning: could not parse year page: {e}")
    fallback = _fallback_urls(year)

    pdf_dest = year_dir / f"{year}_TGES_Installation_Instructions_raw.pdf"
    zip_dest = year_dir / f"{year}_TGES_Zipped_Excel_files_raw.zip"
    xlsx_dest = year_dir / f"{year}_State_Averages_Medians_raw.xlsx"
    skipped: list[str] = []

    def get(kind: str, dest: Path) -> bool:
        ok = _download_asset(kind, dest, page_url, page_links, fallback, timeout_s=timeout_s, force=force, retries=retries, backoff_s=backoff_s)
        if not ok:
            print(f"  - MISSING ({year}): {dest.name} — skipping")
            skipped.append(dest.name)
            if not skip_missing:
                raise RuntimeError(f"All candidates failed for {dest.name}. Use --skip-missing to continue.")
        return ok

    get("pdf", pdf_dest)
    zip_ok = get("zip", zip_dest)
    xlsx_ok = get("xlsx", xlsx_dest)

    if zip_ok and zip_dest.exists():
        _extract_zip(zip_dest, year_dir, force=force)

    if xlsx_ok and xlsx_dest.exists():
        xlsx_in_year = year_dir / f"State_and_Group_Averages_TGES{year}.xlsx"
        year_dir.mkdir(parents=True, exist_ok=True)
        if force or not xlsx_in_year.exists():
            shutil.copy2(xlsx_dest, xlsx_in_year)
            print(f"  - copied: {xlsx_in_year.name}")
        _run_postprocess(year_dir)

    return skipped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _download_year(year: int, outdir: Path, *, timeout_s: float, force: bool, skip_missing: bool, retries: int, backoff_s: float, delay_s: float) -> list[str]:
    year_dir = outdir / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n== {year} ==")
    kwargs = dict(timeout_s=timeout_s, force=force, skip_missing=skip_missing, retries=retries, backoff_s=backoff_s)
    if year < BUNDLE_YEAR_CUTOFF:
        skipped = _download_bundle_year(year, year_dir, **kwargs)
    else:
        skipped = _download_individual_year(year, year_dir, **kwargs)
    if delay_s > 0:
        time.sleep(delay_s)
    return skipped


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download NJ BOE TGES files (2011-2025).", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--start-year", type=int, default=2011)
    p.add_argument("--end-year", type=int, default=2025)
    p.add_argument("--outdir", type=Path, default=_project_root() / "data" / "TGES", help="Output root")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--retries", type=int, default=5)
    p.add_argument("--backoff", type=float, default=1.0)
    p.add_argument("--delay", type=float, default=0.25)
    p.add_argument("--skip-missing", action="store_true", default=True, help="Continue when a file is missing")
    p.add_argument("--strict", dest="skip_missing", action="store_false", help="Abort on first missing file")
    p.add_argument("--force", action="store_true", help="Re-download and re-extract")
    args = p.parse_args(argv)

    if args.start_year > args.end_year:
        p.error("--start-year must be <= --end-year")

    outdir = args.outdir.resolve()
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {outdir}")

    all_skipped: dict[int, list[str]] = {}
    for year in range(args.start_year, args.end_year + 1):
        skipped = _download_year(
            year,
            outdir,
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
        print("Files not found (may need manual download):")
        for yr, files in sorted(all_skipped.items()):
            for f in files:
                print(f"  {yr}: {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
