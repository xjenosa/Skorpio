"""
Ingest the public EV charging-station catalog from the US DOE Alternative
Fuels Data Center, filtered to Canada. AFDC is the authoritative aggregator
that NRCan's Charging Stations Locator pulls from, and it exposes a clean
CSV API keyed by the existing NREL_API_KEY (already wired into the project's
.env). No scraping, no Quebec-only fallback.

Output: backend/services/_ev_chargers_generated.py with a dict keyed by FSA
(`{"M5V": {"station_count": 18, "level2_ports": 32, "dcfc_ports": 4,
"per_1000_households": 4.7}, ...}`) and a city-level rollup.

Usage:

    python -m backend.scripts.ingest_ev_chargers

Cache: data/cache/ev_chargers_ca.csv. Re-run to refresh.
"""

from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen

API_KEY = os.environ.get("NREL_API_KEY") or ""
if not API_KEY:
    # Fall back to reading .env directly so the script works outside docker.
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("NREL_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip()
                break

CSV_URL = (
    "https://developer.nrel.gov/api/alt-fuel-stations/v1.csv"
    f"?api_key={API_KEY}&country=CA&fuel_type=ELEC&status=E"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHED_CSV = CACHE_DIR / "ev_chargers_ca.csv"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_ev_chargers_generated.py"

# Pull the registry the FSA-aggregation script wrote, so we can normalise
# charger counts per 1,000 households per FSA. Loaded lazily inside main()
# to keep this script importable even when the generated file is missing.


# ── Download ────────────────────────────────────────────────────────────── #

def _download_if_missing() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHED_CSV.exists() and CACHED_CSV.stat().st_size > 50_000:
        print(f"[ok] Using cached EV CSV at {CACHED_CSV} ({CACHED_CSV.stat().st_size / 1e3:.0f} KB)")
        return CACHED_CSV
    if not API_KEY:
        raise SystemExit(
            "NREL_API_KEY not found in env or .env. Get a free key at "
            "https://developer.nrel.gov/signup/ and add it to .env."
        )
    print("[..] Downloading Canadian EV chargers from NREL AFDC API...")
    with urlopen(CSV_URL) as resp, CACHED_CSV.open("wb") as out:
        while chunk := resp.read(1 << 16):
            out.write(chunk)
    print(f"[ok] Saved to {CACHED_CSV} ({CACHED_CSV.stat().st_size / 1e3:.0f} KB)")
    return CACHED_CSV


# ── Aggregate ───────────────────────────────────────────────────────────── #

def _fsa_from_postal(zip_code: str) -> str:
    """Canadian postal codes are A0A 0A0; FSA is the first three chars."""
    if not zip_code:
        return ""
    code = zip_code.strip().upper().replace(" ", "")
    if len(code) >= 3 and code[0].isalpha() and code[1].isdigit() and code[2].isalpha():
        return code[:3]
    return ""


def _int(s: str) -> int:
    try:
        return int(s or 0)
    except ValueError:
        return 0


def aggregate(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Returns (per_fsa, per_city) summary dicts."""
    per_fsa: dict[str, dict] = defaultdict(lambda: {
        "station_count": 0, "level1_ports": 0, "level2_ports": 0, "dcfc_ports": 0,
        "province": "",
    })
    per_city: dict[str, dict] = defaultdict(lambda: {
        "station_count": 0, "level1_ports": 0, "level2_ports": 0, "dcfc_ports": 0,
        "province": "",
    })

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fsa = _fsa_from_postal(row.get("ZIP", ""))
            city = (row.get("City") or "").strip()
            prov = (row.get("State") or "").strip()
            l1 = _int(row.get("EV Level1 EVSE Num"))
            l2 = _int(row.get("EV Level2 EVSE Num"))
            dcfc = _int(row.get("EV DC Fast Count"))

            if fsa:
                bucket = per_fsa[fsa]
                bucket["station_count"] += 1
                bucket["level1_ports"] += l1
                bucket["level2_ports"] += l2
                bucket["dcfc_ports"] += dcfc
                if not bucket["province"]:
                    bucket["province"] = prov
            if city:
                key = f"{city}, {prov}"
                bucket = per_city[key]
                bucket["station_count"] += 1
                bucket["level1_ports"] += l1
                bucket["level2_ports"] += l2
                bucket["dcfc_ports"] += dcfc
                if not bucket["province"]:
                    bucket["province"] = prov

    return dict(per_fsa), dict(per_city)


# ── Normalise per 1k households (needs the FSA registry) ────────────────── #

def _per_1000_households(stations: int, households: int | None) -> float | None:
    if not households or households <= 0:
        return None
    return round(1000.0 * stations / households, 2)


# ── Emit ────────────────────────────────────────────────────────────────── #

HEADER = '''"""
Auto-generated EV charger counts per Forward Sortation Area (FSA) and per
city. Source: NREL Alternative Fuels Data Center (AFDC), country=CA,
fuel_type=ELEC, status=E (open / operational), via key NREL_API_KEY.

NRCan's Electric Charging and Alternative Fuelling Stations Locator pulls
from the same AFDC dataset — this is the authoritative national list.

DO NOT EDIT BY HAND - re-run `python -m backend.scripts.ingest_ev_chargers`.

Fields per FSA:
  station_count        — number of public AFDC-registered stations in that FSA
  level1_ports         — count of EV Level 1 (120V) ports
  level2_ports         — count of EV Level 2 (240V) ports
  dcfc_ports           — count of DC fast-charge ports
  per_1000_households  — station_count normalised by the FSA's household total
                          (None when the household number is unknown)
  province             — 2-letter province code
"""

EV_CHARGERS_BY_FSA: dict[str, dict] = {
'''


def emit_python(per_fsa: dict[str, dict], per_city: dict[str, dict], path: Path) -> None:
    # Best-effort join against the FSA household counts.
    try:
        from backend.services._fsa_data_generated import _FSA_REGISTRY
    except Exception:
        _FSA_REGISTRY = {}

    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for fsa in sorted(per_fsa):
            e = per_fsa[fsa]
            households = (_FSA_REGISTRY.get(fsa) or {}).get("households")
            per_1k = _per_1000_households(e["station_count"], households)
            f.write(f'    "{fsa}": {{\n')
            f.write(f'        "station_count": {e["station_count"]},\n')
            f.write(f'        "level1_ports": {e["level1_ports"]},\n')
            f.write(f'        "level2_ports": {e["level2_ports"]},\n')
            f.write(f'        "dcfc_ports": {e["dcfc_ports"]},\n')
            f.write(f'        "per_1000_households": {per_1k!r},\n')
            f.write(f'        "province": {e["province"]!r},\n')
            f.write(f'    }},\n')
        f.write("}\n\n")
        f.write("EV_CHARGERS_BY_CITY: dict[str, dict] = {\n")
        for key in sorted(per_city):
            e = per_city[key]
            f.write(f'    {key!r}: {{\n')
            f.write(f'        "station_count": {e["station_count"]},\n')
            f.write(f'        "level1_ports": {e["level1_ports"]},\n')
            f.write(f'        "level2_ports": {e["level2_ports"]},\n')
            f.write(f'        "dcfc_ports": {e["dcfc_ports"]},\n')
            f.write(f'        "province": {e["province"]!r},\n')
            f.write(f'    }},\n')
        f.write("}\n")
    print(f"  Wrote {path}")


def main() -> None:
    csv_path = _download_if_missing()
    per_fsa, per_city = aggregate(csv_path)
    print(f"  Aggregated {len(per_fsa):,} FSAs and {len(per_city):,} cities.")
    emit_python(per_fsa, per_city, OUTPUT_FILE)

    # Spot-check
    print("\nSpot-check (top 5 by station count):")
    for fsa, e in sorted(per_fsa.items(), key=lambda kv: -kv[1]["station_count"])[:5]:
        print(f"  {fsa} ({e['province']}): {e['station_count']} stations, "
              f"L2={e['level2_ports']}, DCFC={e['dcfc_ports']}")


if __name__ == "__main__":
    main()
