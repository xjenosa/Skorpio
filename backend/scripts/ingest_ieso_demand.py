"""
Ingest IESO hourly Ontario demand and derive a real 24-hour winter-weekday
load shape. Replaces the eyeballed time-of-day pattern in
electrification_modeling._BASE_LOAD_KW_HOUR with the actual hour-of-day
pattern observed in IESO's published demand history.

Source: IESO Public Reports
  https://reports-public.ieso.ca/public/Demand/PUB_Demand_YYYY.csv

Approach:
  - Pull the most recent full year of hourly Ontario demand
  - Filter to Dec/Jan/Feb weekdays only
  - Average each hour-of-day across all matching days → 24-value shape
  - Normalize so mean = 1.0 (a pure shape)
  - Downstream callers multiply this shape by their existing per-household
    baseline magnitude, so calibration stays anchored while the pattern
    becomes real

Usage:

    python -m backend.scripts.ingest_ieso_demand

Cache: data/cache/ieso_demand_YYYY.csv. Re-run to refresh.

Emits: backend/services/_ieso_demand_shape_generated.py
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

URL_TPL = (
    "https://reports-public.ieso.ca/public/Demand/"
    "PUB_Demand_{year}.csv"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_ieso_demand_shape_generated.py"


def _download_if_missing(year: int) -> Path | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / f"ieso_demand_{year}.csv"
    if target.exists() and target.stat().st_size > 10_000:
        print(f"[ok] {year}: cached ({target.stat().st_size / 1e3:.0f} KB)")
        return target
    url = URL_TPL.format(year=year)
    try:
        req = Request(url, headers={"User-Agent": "Skorpio/1.0 (skorpio@energyplacement.ai)"})
        with urlopen(req, timeout=60) as resp, target.open("wb") as out:
            while chunk := resp.read(1 << 16):
                out.write(chunk)
        size = target.stat().st_size
        if size < 10_000:
            target.unlink(missing_ok=True)
            print(f"  [warn] {year}: response too small ({size} bytes)")
            return None
        print(f"[ok] {year}: downloaded ({size / 1e3:.0f} KB)")
        return target
    except Exception as e:
        print(f"  [warn] {year}: {e}")
        return None


def parse(csv_path: Path) -> list[tuple[int, int, int, float]]:
    """Return [(month, weekday_0_to_6, hour_0_to_23, demand_mw)] for every
    hourly row in the file."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        lines = f.readlines()
    header_idx = -1
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("Date") and "demand" in line.lower():
            header_idx = i
            break
    if header_idx < 0:
        raise SystemExit(f"Could not find demand header row in {csv_path}")
    reader = csv.DictReader(io.StringIO("".join(lines[header_idx:])))
    cols = reader.fieldnames or []
    demand_col = next((c for c in cols if "demand" in c.lower()
                                          and "ontario" in c.lower()), None)
    if not demand_col:
        demand_col = next((c for c in cols if c.lower() == "market demand"
                                              or "market_demand" in c.lower()), None)
    if not demand_col:
        demand_col = next((c for c in cols if "demand" in c.lower()), None)
    date_col = next((c for c in cols if "date" in c.lower()), None)
    hour_col = next((c for c in cols if c.lower().strip() == "hour"), None)
    if not (demand_col and date_col and hour_col):
        raise SystemExit(
            f"Required columns missing. Saw: {cols}\n"
            f"Got demand={demand_col!r} date={date_col!r} hour={hour_col!r}"
        )

    rows: list[tuple[int, int, int, float]] = []
    for row in reader:
        try:
            ds = (row[date_col] or "").strip()
            hour_raw = int(row[hour_col])  # IESO hours are 1..24
            mw = float(row[demand_col])
        except (ValueError, TypeError, KeyError):
            continue
        # IESO hour 1 = 00:00–01:00; hour 24 = 23:00–00:00.
        hour = (hour_raw - 1) % 24
        # Parse date — IESO uses YYYY-MM-DD.
        try:
            dt = datetime.strptime(ds, "%Y-%m-%d")
        except ValueError:
            continue
        rows.append((dt.month, dt.weekday(), hour, mw))
    return rows


def derive_winter_weekday_shape(rows: list[tuple[int, int, int, float]]) -> list[float]:
    """Average hourly demand across Dec/Jan/Feb weekdays. Returns a
    24-value list normalized so mean = 1.0 (pure shape)."""
    by_hour: dict[int, list[float]] = defaultdict(list)
    for month, weekday, hour, mw in rows:
        if month not in (12, 1, 2):
            continue
        if weekday > 4:                      # 0=Mon ... 4=Fri
            continue
        by_hour[hour].append(mw)
    if any(len(by_hour[h]) < 10 for h in range(24)):
        missing = [h for h in range(24) if len(by_hour[h]) < 10]
        raise SystemExit(f"Insufficient winter-weekday rows in hours: {missing}")
    means = [sum(by_hour[h]) / len(by_hour[h]) for h in range(24)]
    overall = sum(means) / 24.0
    return [round(m / overall, 4) for m in means]


HEADER = '''"""
Auto-generated 24-hour shape of Ontario system demand on winter weekdays
(Dec / Jan / Feb, Mon-Fri). Source: IESO Public Reports
PUB_Demand_{year}.csv.

The shape is normalized so the 24 values average to 1.0. Downstream
callers multiply this shape by their own per-household baseline magnitude
to get an absolute hourly load. This is the real *timing pattern* of
Ontario demand even though IESO publishes system-wide totals, not
residential-only — the time-of-day signal is dominated by residential and
small-commercial behavior since heavy industry runs roughly flat.

Hours are 0..23 in IESO local time (EST, no DST). Index 0 = midnight
to 1 am.

DO NOT EDIT BY HAND - re-run `python -m backend.scripts.ingest_ieso_demand`.

Used by:
  - grid/electrification_modeling.py — overlays the real shape onto the
    eyeballed `_BASE_LOAD_KW_HOUR` array (preserves the original mean
    magnitude, applies the real time-of-day pattern)
"""

IESO_DEMAND_SHAPE_YEAR: int = {year}

# 24 values, mean = 1.0. Multiply by your own per-household mean kW to
# get an absolute hourly load.
IESO_WINTER_WEEKDAY_SHAPE: list[float] = {shape!r}
'''


def emit_python(year: int, shape: list[float], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER.format(year=year, shape=shape))
    print(f"  Wrote {path}")


def main() -> None:
    for candidate_year in (datetime.now().year - 1, datetime.now().year - 2):
        path = _download_if_missing(candidate_year)
        if not path:
            continue
        rows = parse(path)
        if not rows:
            continue
        shape = derive_winter_weekday_shape(rows)
        emit_python(candidate_year, shape, OUTPUT_FILE)

        print(f"\nSpot-check (hour : multiplier for {candidate_year} winter weekday):")
        labels = [f"{h:02d}:00" for h in range(24)]
        for h in range(24):
            bar = "#" * max(1, int(shape[h] * 30))
            print(f"  {labels[h]} {shape[h]:.3f}  {bar}")
        return
    raise SystemExit("No IESO demand year could be ingested.")


if __name__ == "__main__":
    main()
