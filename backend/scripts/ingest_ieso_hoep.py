"""
Ingest IESO Hourly Ontario Energy Price (HOEP). Each ingest writes the
per-hour values for the most recent full year so the rest of the
pipeline has a real per-hour Ontario spot price instead of a jittered
estimate.

Source: IESO Public Reports
  https://reports-public.ieso.ca/public/PriceHOEPPredispOR/PUB_PriceHOEPPredispOR_YYYY.csv

Usage:

    python -m backend.scripts.ingest_ieso_hoep

Cache: data/cache/ieso_hoep_YYYY.csv. Re-run to refresh.

Emits: backend/services/_ieso_hoep_generated.py with hourly + summary
stats (mean / median / p10 / p90, in $/MWh CAD).
"""

from __future__ import annotations

import csv
import io
import statistics
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

YEAR = datetime.utcnow().year - 1     # default: most recent full year
URL_TPL = (
    "https://reports-public.ieso.ca/public/PriceHOEPPredispOR/"
    "PUB_PriceHOEPPredispOR_{year}.csv"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHED_CSV = CACHE_DIR / f"ieso_hoep_{YEAR}.csv"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_ieso_hoep_generated.py"


def _download_if_missing(year: int) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / f"ieso_hoep_{year}.csv"
    if target.exists() and target.stat().st_size > 10_000:
        print(f"[ok] Using cached CSV at {target} ({target.stat().st_size / 1e3:.0f} KB)")
        return target
    url = URL_TPL.format(year=year)
    print(f"[..] Downloading IESO HOEP for {year} from {url} ...")
    req = Request(url, headers={"User-Agent": "Skorpio/1.0 (skorpio@energyplacement.ai)"})
    with urlopen(req) as resp, target.open("wb") as out:
        while chunk := resp.read(1 << 16):
            out.write(chunk)
    print(f"[ok] Saved to {target} ({target.stat().st_size / 1e3:.0f} KB)")
    return target


def parse(csv_path: Path) -> list[float]:
    """Return a flat list of HOEP values in $/MWh CAD, one per hour."""
    values: list[float] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        # IESO file has a multi-line header above the actual CSV header
        # row. Scan until we find a header line containing "HOEP".
        raw_lines = f.readlines()
    header_idx = -1
    for i, line in enumerate(raw_lines):
        # IESO files have `\\Yearly...` / `\\Created...` / `\\For YYYY` preamble
        # lines that also contain "HOEP" and commas. Skip anything that doesn't
        # start with the literal "Date" column header.
        stripped = line.lstrip()
        if stripped.startswith("Date") and "HOEP" in line.upper():
            header_idx = i
            break
    if header_idx < 0:
        raise SystemExit(f"Could not find HOEP header row in {csv_path}")
    reader = csv.DictReader(io.StringIO("".join(raw_lines[header_idx:])))
    cols = reader.fieldnames or []
    hoep_col = next((c for c in cols if "HOEP" in c.upper()), None)
    if not hoep_col:
        raise SystemExit(f"No HOEP column in {cols}")
    for row in reader:
        try:
            values.append(float(row[hoep_col]))
        except (ValueError, TypeError, KeyError):
            continue
    return values


HEADER_TPL = '''"""
Auto-generated hourly Ontario spot electricity price (HOEP) for the
most recent full year published by IESO. Source: IESO Public Reports
PUB_PriceHOEPPredispOR_{year}.csv. Currency: CAD per MWh.

The original IESO file is ~8760 rows (one per hour). We keep three
representations:

  - HOURLY_HOEP_CAD_PER_MWH : flat list, one entry per hour, in file order
  - HOEP_SUMMARY            : mean / median / p10 / p90 / min / max
  - HOEP_YEAR               : the data year

DO NOT EDIT BY HAND - re-run `python -m backend.scripts.ingest_ieso_hoep`.

Used by:
  - grid/generator.py (Siting) — replaces the jittered
    `spot_lmp_usd_mwh` for Ontario candidates with the real median HOEP
"""

HOEP_YEAR: int = {year}

HOURLY_HOEP_CAD_PER_MWH: list[float] = ['''


def emit_python(year: int, values: list[float], path: Path) -> None:
    if not values:
        raise SystemExit("No HOEP rows parsed; refusing to emit empty file.")
    summary = {
        "count": len(values),
        "mean": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "p10": round(sorted(values)[len(values) // 10], 2),
        "p90": round(sorted(values)[(len(values) * 9) // 10], 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER_TPL.format(year=year))
        # 24 values per line keeps the file scannable.
        line = []
        for i, v in enumerate(values):
            line.append(f"{v:.2f}")
            if len(line) == 24:
                f.write("\n    " + ", ".join(line) + ",")
                line = []
        if line:
            f.write("\n    " + ", ".join(line) + ",")
        f.write("\n]\n\n")
        f.write("HOEP_SUMMARY: dict = {\n")
        for k, v in summary.items():
            f.write(f'    "{k}": {v},\n')
        f.write("}\n")
    print(f"  Wrote {path}")
    print(f"  Summary: median={summary['median']} mean={summary['mean']} "
          f"p10={summary['p10']} p90={summary['p90']} CAD/MWh")


def main() -> None:
    # Try the targeted year, fall back one year if the file isn't published yet.
    for candidate_year in (YEAR, YEAR - 1):
        try:
            csv_path = _download_if_missing(candidate_year)
            values = parse(csv_path)
            if values:
                emit_python(candidate_year, values, OUTPUT_FILE)
                return
        except Exception as e:
            print(f"  [warn] {candidate_year}: {e}")
    raise SystemExit("No HOEP year could be ingested.")


if __name__ == "__main__":
    main()
