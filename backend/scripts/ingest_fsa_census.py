"""
Ingest StatsCan 2021 Census Profile (Forward Sortation Areas, catalogue
98-401-X2021013) and emit a real `_FSA_REGISTRY` for the electrification
pipeline.

Why this exists: the hand-curated registry in `statscan.py` only covers 11
FSAs in 6 cities. This script downloads the ~65 MB official CSV from
StatsCan, extracts the variables the electrification agent actually needs
(household count, median income, average size, dwelling-type mix, primary
heating-fuel mix, derived avg dwelling age), and writes them into
`backend/services/_fsa_data_generated.py` for every Canadian FSA (~1,600).
`statscan.py` then imports that file instead of carrying the registry inline.

Usage (run once, locally or in the api container):

    docker compose exec api python -m backend.scripts.ingest_fsa_census

Caches the raw CSV under `data/cache/` so re-runs skip the download. Idempotent
— overwrites `_fsa_data_generated.py` each time. Safe to commit the output.

Fields the census DOES cover and we DO use:
  - households (private dwellings occupied by usual residents)
  - median total income of household
  - average household size
  - dwelling type mix (single-detached / semi / row / low- and high-rise apt / other)
  - primary heating fuel mix
  - derived avg dwelling age (weighted from period-of-construction buckets)

Fields the census does NOT cover (we keep the existing province-default
synthesis path for these — see `_PROVINCE_FALLBACK` in statscan.py):
  - vehicles_per_household  (Transport Canada data, not Census)
  - heating_degree_days_18c (ECCC Climate Normals, not Census)
"""

from __future__ import annotations

import csv
import io
import os
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterator
from urllib.request import urlopen

CSV_URL = (
    "https://www12.statcan.gc.ca/census-recensement/2021/dp-pd/prof/details/"
    "download-telecharger/comp/GetFile.cfm?Lang=E&FILETYPE=CSV&GEONO=013"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
# StatsCan ships the FSA Profile as a ZIP (~65 MB) wrapping a ~645 MB CSV.
# We stream-read the CSV directly from inside the ZIP to avoid writing
# the uncompressed file to disk.
CACHED_ZIP = CACHE_DIR / "fsa_census_2021.zip"
CSV_INSIDE_ZIP = "98-401-X2021013_English_CSV_data.csv"
# StatsCan public CSVs use Windows-1252 (cp1252), not UTF-8.
CSV_ENCODING = "cp1252"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_fsa_data_generated.py"

# Mapping from CHARACTERISTIC_NAME (lower-cased, normalised whitespace) to
# the registry field we want to populate. We match by NAME, not numeric ID,
# because IDs shift between census revisions and the names are the stable
# contract StatsCan publishes. Any name change between censuses will cause
# extraction to skip that field — visible in the validation report at the
# end of the run.

HOUSEHOLDS_NAME = "private dwellings occupied by usual residents"
MEDIAN_INCOME_NAME = "median total income of household in 2020 ($)"
AVG_HOUSEHOLD_SIZE_NAME = "average household size"

# Dwelling-type characteristic names (under "Structural type of dwelling").
DWELLING_NAMES = {
    "single_detached": "single-detached house",
    "semi_detached": "semi-detached house",
    "row": "row house",
    "apartment_low_rise": "apartment in a building that has fewer than five storeys",
    "apartment_high_rise": "apartment in a building that has five or more storeys",
    "other": "other single-attached house",
}

# StatsCan dropped primary-heating-fuel from the 2021 FSA Profile (it lives
# only at higher geographic levels for that census). We fill heating mix per
# FSA from PROVINCE_DEFAULTS below — sourced from NRCan's Comprehensive
# Energy Use Database 2021 by province. Not as precise as a real FSA-level
# split, but defensible against a published source.

# Province-level defaults for fields the FSA Profile doesn't carry.
# vehicles_per_household: Transport Canada / StatsCan Vehicle Registrations 2021.
# heating_degree_days_18c: ECCC Climate Normals 1981-2010 (capital city, rounded).
# heating_mix: NRCan Comprehensive Energy Use Database 2021, residential.
PROVINCE_DEFAULTS: dict[str, dict] = {
    "ON": {"vehicles_per_household": 1.4, "heating_degree_days_18c": 4050.0,
           "heating_mix": {"natural_gas": 0.62, "electric_baseboard": 0.12,
                           "electric_forced_air": 0.08, "heat_pump": 0.04,
                           "oil": 0.05, "wood": 0.04, "other": 0.05}},
    "QC": {"vehicles_per_household": 1.3, "heating_degree_days_18c": 4500.0,
           "heating_mix": {"natural_gas": 0.10, "electric_baseboard": 0.55,
                           "electric_forced_air": 0.12, "heat_pump": 0.10,
                           "oil": 0.05, "wood": 0.05, "other": 0.03}},
    "AB": {"vehicles_per_household": 1.7, "heating_degree_days_18c": 5100.0,
           "heating_mix": {"natural_gas": 0.85, "electric_baseboard": 0.05,
                           "electric_forced_air": 0.03, "heat_pump": 0.02,
                           "oil": 0.01, "wood": 0.02, "other": 0.02}},
    "BC": {"vehicles_per_household": 1.3, "heating_degree_days_18c": 2900.0,
           "heating_mix": {"natural_gas": 0.55, "electric_baseboard": 0.25,
                           "electric_forced_air": 0.06, "heat_pump": 0.08,
                           "oil": 0.02, "wood": 0.03, "other": 0.01}},
    "MB": {"vehicles_per_household": 1.5, "heating_degree_days_18c": 5800.0,
           "heating_mix": {"natural_gas": 0.65, "electric_baseboard": 0.20,
                           "electric_forced_air": 0.05, "heat_pump": 0.02,
                           "oil": 0.02, "wood": 0.04, "other": 0.02}},
    "SK": {"vehicles_per_household": 1.6, "heating_degree_days_18c": 5900.0,
           "heating_mix": {"natural_gas": 0.78, "electric_baseboard": 0.08,
                           "electric_forced_air": 0.05, "heat_pump": 0.02,
                           "oil": 0.02, "wood": 0.03, "other": 0.02}},
    "NB": {"vehicles_per_household": 1.5, "heating_degree_days_18c": 4700.0,
           "heating_mix": {"natural_gas": 0.05, "electric_baseboard": 0.45,
                           "electric_forced_air": 0.08, "heat_pump": 0.08,
                           "oil": 0.20, "wood": 0.12, "other": 0.02}},
    "NS": {"vehicles_per_household": 1.4, "heating_degree_days_18c": 4200.0,
           "heating_mix": {"natural_gas": 0.03, "electric_baseboard": 0.30,
                           "electric_forced_air": 0.07, "heat_pump": 0.12,
                           "oil": 0.35, "wood": 0.10, "other": 0.03}},
    "PE": {"vehicles_per_household": 1.4, "heating_degree_days_18c": 4400.0,
           "heating_mix": {"natural_gas": 0.01, "electric_baseboard": 0.30,
                           "electric_forced_air": 0.05, "heat_pump": 0.10,
                           "oil": 0.40, "wood": 0.12, "other": 0.02}},
    "NL": {"vehicles_per_household": 1.4, "heating_degree_days_18c": 4900.0,
           "heating_mix": {"natural_gas": 0.01, "electric_baseboard": 0.55,
                           "electric_forced_air": 0.10, "heat_pump": 0.06,
                           "oil": 0.18, "wood": 0.08, "other": 0.02}},
    "YT": {"vehicles_per_household": 1.5, "heating_degree_days_18c": 6800.0,
           "heating_mix": {"natural_gas": 0.02, "electric_baseboard": 0.20,
                           "electric_forced_air": 0.06, "heat_pump": 0.02,
                           "oil": 0.45, "wood": 0.20, "other": 0.05}},
    "NT": {"vehicles_per_household": 1.4, "heating_degree_days_18c": 7800.0,
           "heating_mix": {"natural_gas": 0.05, "electric_baseboard": 0.10,
                           "electric_forced_air": 0.04, "heat_pump": 0.01,
                           "oil": 0.60, "wood": 0.15, "other": 0.05}},
    "NU": {"vehicles_per_household": 1.0, "heating_degree_days_18c": 9200.0,
           "heating_mix": {"natural_gas": 0.0, "electric_baseboard": 0.05,
                           "electric_forced_air": 0.02, "heat_pump": 0.0,
                           "oil": 0.85, "wood": 0.03, "other": 0.05}},
}

# Period-of-construction buckets [..] midpoint year used to compute the area's
# average dwelling age (relative to 2021).
PERIOD_MIDPOINTS = {
    "1960 or before": 1950,
    "1961 to 1980": 1970,
    "1981 to 1990": 1985,
    "1991 to 2000": 1995,
    "2001 to 2005": 2003,
    "2006 to 2010": 2008,
    "2011 to 2015": 2013,
    "2016 to 2021": 2018,
}


# ── Download ────────────────────────────────────────────────────────────── #

def _download_if_missing() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Legacy cleanup: an earlier version of this script saved the download
    # as ".csv". Rename to ".zip" if found so the cache check below works.
    legacy = CACHE_DIR / "fsa_census_2021.csv"
    if legacy.exists() and not CACHED_ZIP.exists():
        legacy.rename(CACHED_ZIP)
    if CACHED_ZIP.exists() and CACHED_ZIP.stat().st_size > 10_000_000:
        print(f"[ok] Using cached ZIP at {CACHED_ZIP} ({CACHED_ZIP.stat().st_size / 1e6:.1f} MB)")
        return CACHED_ZIP
    print(f"[..] Downloading FSA Census ZIP from StatsCan (~65 MB)...")
    with urlopen(CSV_URL) as resp, CACHED_ZIP.open("wb") as out:
        bytes_read = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            bytes_read += len(chunk)
            sys.stdout.write(f"\r  ...{bytes_read / 1e6:.1f} MB")
            sys.stdout.flush()
    print(f"\n[ok] Saved to {CACHED_ZIP} ({CACHED_ZIP.stat().st_size / 1e6:.1f} MB)")
    return CACHED_ZIP


# ── Parsing ─────────────────────────────────────────────────────────────── #

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _read_rows(zip_path: Path) -> Iterator[dict]:
    """Stream the CSV directly out of the ZIP — file is 645 MB uncompressed,
    so we never write it to disk."""
    with zipfile.ZipFile(zip_path) as zf, zf.open(CSV_INSIDE_ZIP) as raw:
        text = io.TextIOWrapper(raw, encoding=CSV_ENCODING, newline="")
        reader = csv.DictReader(text)
        for row in reader:
            yield row


def _detect_columns(reader_sample: list[dict]) -> tuple[str, str, str, str, str]:
    """
    Returns (geo_code_col, geo_name_col, characteristic_name_col, value_col,
    province_code_col_or_empty). StatsCan CSV column names vary slightly
    between releases; we sniff them defensively from the first row.
    """
    if not reader_sample:
        raise SystemExit("CSV appears empty.")
    cols = list(reader_sample[0].keys())

    def find(*needles: str) -> str:
        for needle in needles:
            for c in cols:
                if needle.lower() in c.lower():
                    return c
        raise SystemExit(
            f"Could not find any of {needles!r} in CSV columns: {cols}"
        )

    geo_code = find("ALT_GEO_CODE", "ALT GEO CODE", "GEO_CODE")
    geo_name = find("GEO_NAME", "GEO NAME")
    char_name = find("CHARACTERISTIC_NAME", "CHARACTERISTIC NAME")
    value = find("C1_COUNT_TOTAL", "C1 COUNT TOTAL", "TOTAL - SEX")
    # Province code can sometimes be derived from DGUID; not always present.
    province = ""
    for c in cols:
        if c.upper() in {"PR_UID", "PRUID"} or "DGUID" in c.upper():
            province = c
            break

    print(f"  Columns: geo_code={geo_code!r}, geo_name={geo_name!r}, "
          f"char={char_name!r}, value={value!r}, province_hint={province!r}")
    return geo_code, geo_name, char_name, value, province


# Standard mapping from FSA first letter to province (Canada Post FSA scheme).
# Source: Canada Post Addressing Guidelines. This is the published spec, not an
# approximation — every valid Canadian FSA's first character determines its
# province uniquely (except for "X" which spans NT and NU; we tag those NT
# because Nunavut FSAs all start with X0A0 and we don't depend on the split).
FSA_PREFIX_TO_PROVINCE: dict[str, str] = {
    "A": "NL", "B": "NS", "C": "PE", "E": "NB",
    "G": "QC", "H": "QC", "J": "QC",
    "K": "ON", "L": "ON", "M": "ON", "N": "ON", "P": "ON",
    "R": "MB", "S": "SK", "T": "AB", "V": "BC",
    "X": "NT", "Y": "YT",
}


def _province_from_fsa(fsa: str) -> str:
    return FSA_PREFIX_TO_PROVINCE.get((fsa or "")[:1].upper(), "")


def _to_float(s: str) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if not s or s in {"..", "...", "F", "x", "0", "-"}:
        # StatsCan suppresses small / unreliable cells with "..", "F", "x";
        # treat "0" as missing for fields where a non-zero is expected so we
        # don't accidentally zero-out the dwelling/heating denominators.
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── Aggregation ─────────────────────────────────────────────────────────── #

def aggregate(csv_path: Path) -> dict[str, dict]:
    """
    Walk the CSV once, accumulating per-FSA characteristics into a dict.
    Returns {fsa_code: {raw_field: value, ...}} with the raw census numbers
    not yet shaped into the registry format.
    """
    # Peek at the first couple of rows to sniff column names.
    sample = []
    for i, row in enumerate(_read_rows(csv_path)):
        sample.append(row)
        if i >= 1:
            break
    geo_code_c, geo_name_c, char_name_c, value_c, _province_c = _detect_columns(sample)

    per_fsa: dict[str, dict] = defaultdict(dict)
    seen_chars: set[str] = set()
    n_rows = 0

    print(f"  Scanning CSV rows (this takes ~30-60s for the full file)...")
    for row in _read_rows(csv_path):
        n_rows += 1
        if n_rows % 500_000 == 0:
            sys.stdout.write(f"\r  ...{n_rows:,} rows")
            sys.stdout.flush()

        fsa = (row.get(geo_code_c) or "").strip()
        # FSA codes are exactly 3 chars: letter, digit, letter.
        if not re.fullmatch(r"[A-Z]\d[A-Z]", fsa):
            continue

        char = _norm(row.get(char_name_c, ""))
        if not char:
            continue
        seen_chars.add(char)
        val = _to_float(row.get(value_c, ""))

        bucket = per_fsa[fsa]
        if "province" not in bucket:
            bucket["province"] = _province_from_fsa(fsa)

        # Match characteristic names [..] registry fields. Match on equality after
        # normalisation, except for the dwelling/heating buckets which can have
        # mild phrasing drift.
        if char == HOUSEHOLDS_NAME:
            bucket["households"] = val
        elif char == MEDIAN_INCOME_NAME:
            bucket["median_household_income_cad"] = val
        elif char == AVG_HOUSEHOLD_SIZE_NAME:
            bucket["avg_household_size"] = val

        for key, name in DWELLING_NAMES.items():
            if char == name:
                bucket.setdefault("dwelling_raw", {})[key] = val or 0
        for period, midpoint in PERIOD_MIDPOINTS.items():
            if char == period:
                bucket.setdefault("period_raw", {})[midpoint] = val or 0

    print(f"\n  Done. {n_rows:,} rows total, {len(per_fsa):,} FSAs detected.")
    print(f"  {len(seen_chars):,} unique characteristic names seen.")
    return dict(per_fsa)


# ── Shape into registry ─────────────────────────────────────────────────── #

def _normalise_mix(raw: dict[str, float]) -> dict[str, float] | None:
    total = sum(v for v in raw.values() if v)
    if total <= 0:
        return None
    return {k: round(v / total, 4) for k, v in raw.items()}


def _avg_dwelling_age(period_raw: dict[int, float], census_year: int = 2021) -> float | None:
    total = sum(v for v in period_raw.values() if v)
    if total <= 0:
        return None
    weighted_mid = sum(year * v for year, v in period_raw.items() if v) / total
    return round(census_year - weighted_mid, 1)


CITY_FROM_FSA_PREFIX: dict[str, tuple[str, str]] = {
    # Bare-minimum city naming for the major metros — used as a friendly
    # label only. FSAs not in this table get the province as their city
    # name. Extend later if we need finer labels.
    "M": ("Toronto", "Toronto"),
    "L": ("Greater Toronto Area", "GTA"),
    "K": ("Eastern Ontario", "Eastern ON"),
    "N": ("Southwestern Ontario", "SW ON"),
    "P": ("Northern Ontario", "Northern ON"),
    "H": ("Montréal", "Montréal"),
    "J": ("Outer Québec", "Outer QC"),
    "G": ("Eastern Québec", "Eastern QC"),
    "T": ("Alberta", "Alberta"),
    "V": ("British Columbia", "BC"),
    "R": ("Manitoba", "Manitoba"),
    "S": ("Saskatchewan", "Saskatchewan"),
    "B": ("Nova Scotia", "Nova Scotia"),
    "E": ("New Brunswick", "New Brunswick"),
    "A": ("Newfoundland and Labrador", "NL"),
    "C": ("Prince Edward Island", "PEI"),
    "X": ("Northwest Territories / Nunavut", "NT/NU"),
    "Y": ("Yukon", "Yukon"),
}


def shape_registry(raw: dict[str, dict]) -> dict[str, dict]:
    """Convert raw census aggregates into the on-disk registry shape.

    Mixes Census-sourced fields (households, income, household size, dwelling
    mix, derived dwelling age) with PROVINCE_DEFAULTS for fields the FSA
    Profile doesn't carry (heating_mix, vehicles_per_household, HDD)."""
    out: dict[str, dict] = {}
    dropped_no_hh = 0
    dropped_no_dwelling = 0
    dropped_no_province = 0
    for fsa, bucket in sorted(raw.items()):
        households = bucket.get("households")
        if not households:
            dropped_no_hh += 1
            continue
        dwelling_mix = _normalise_mix(bucket.get("dwelling_raw", {}))
        if not dwelling_mix:
            dropped_no_dwelling += 1
            continue
        province = bucket.get("province", "")
        if province not in PROVINCE_DEFAULTS:
            dropped_no_province += 1
            continue
        prov_def = PROVINCE_DEFAULTS[province]
        city, _ = CITY_FROM_FSA_PREFIX.get(fsa[0], (province, "-"))
        out[fsa] = {
            "label": f"{city} · {fsa}",
            "city": city,
            "province": province,
            "households": int(households),
            "median_household_income_cad": bucket.get("median_household_income_cad"),
            "avg_household_size": bucket.get("avg_household_size"),
            "vehicles_per_household": prov_def["vehicles_per_household"],
            "avg_dwelling_age_years": _avg_dwelling_age(bucket.get("period_raw", {})),
            "heating_degree_days_18c": prov_def["heating_degree_days_18c"],
            "dwelling_mix": dwelling_mix,
            "heating_mix": prov_def["heating_mix"],
        }
    print(
        f"  Shaped {len(out):,} usable FSAs. "
        f"Dropped: {dropped_no_hh:,} (no households), "
        f"{dropped_no_dwelling:,} (no dwelling mix), "
        f"{dropped_no_province:,} (no province match)."
    )
    return out


# ── Emit Python source ──────────────────────────────────────────────────── #

HEADER = '''"""
Auto-generated FSA registry from StatsCan 2021 Census Profile (catalogue
98-401-X2021013). DO NOT EDIT BY HAND - re-run `python -m
backend.scripts.ingest_fsa_census` to regenerate.

Per-FSA Census-sourced fields (from the 2021 Profile):
  - households (Private dwellings occupied by usual residents)
  - median_household_income_cad
  - avg_household_size
  - avg_dwelling_age_years (derived from period-of-construction buckets)
  - dwelling_mix (structural type, 100% data)

Province-level fields (the 2021 Profile drops these at the FSA level, so
we fill from provincial averages):
  - heating_mix: NRCan Comprehensive Energy Use Database 2021 (residential)
  - vehicles_per_household: Transport Canada / StatsCan vehicle registrations 2021
  - heating_degree_days_18c: ECCC Climate Normals 1981-2010
"""
from backend.models.electrification import DwellingMix, HeatingMix

_FSA_REGISTRY: dict[str, dict] = {
'''

FOOTER = "}\n"


def emit_python(registry: dict[str, dict], path: Path) -> None:
    def fnum(v) -> str:
        if v is None:
            return "None"
        if isinstance(v, int):
            return str(v)
        return f"{float(v):.4f}".rstrip("0").rstrip(".") or "0"

    def dwelling_kwargs(mix: dict[str, float]) -> str:
        order = ["single_detached", "semi_detached", "row",
                 "apartment_low_rise", "apartment_high_rise", "other"]
        return ", ".join(f"{k}={fnum(mix.get(k, 0))}" for k in order)

    def heating_kwargs(mix: dict[str, float]) -> str:
        order = ["natural_gas", "electric_baseboard", "electric_forced_air",
                 "heat_pump", "oil", "wood", "other"]
        return ", ".join(f"{k}={fnum(mix.get(k, 0))}" for k in order)

    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for fsa, e in registry.items():
            f.write(f'    "{fsa}": {{\n')
            f.write(f'        "label": {e["label"]!r},\n')
            f.write(f'        "city": {e["city"]!r}, "province": {e["province"]!r},\n')
            f.write(f'        "households": {e["households"]},\n')
            f.write(f'        "median_household_income_cad": {fnum(e["median_household_income_cad"])},\n')
            f.write(f'        "avg_household_size": {fnum(e["avg_household_size"])},\n')
            f.write(f'        "vehicles_per_household": {fnum(e["vehicles_per_household"])},\n')
            f.write(f'        "avg_dwelling_age_years": {fnum(e["avg_dwelling_age_years"])},\n')
            f.write(f'        "heating_degree_days_18c": {fnum(e["heating_degree_days_18c"])},\n')
            f.write(f'        "dwelling_mix": DwellingMix({dwelling_kwargs(e["dwelling_mix"])}),\n')
            f.write(f'        "heating_mix": HeatingMix({heating_kwargs(e["heating_mix"])}),\n')
            f.write(f'    }},\n')
        f.write(FOOTER)
    print(f"  Wrote {path}")


# ── Main ────────────────────────────────────────────────────────────────── #

def main() -> None:
    csv_path = _download_if_missing()
    raw = aggregate(csv_path)
    registry = shape_registry(raw)
    emit_python(registry, OUTPUT_FILE)

    # Spot-check three FSAs that exist in both the old hand-curated registry
    # and the new generated one — eyeball the deltas so the user can sanity-
    # check the ingestion landed sane numbers before swapping the import.
    print("\nSpot-check vs hand-curated values:")
    for fsa in ("M5V", "K1S", "H2X"):
        e = registry.get(fsa)
        if not e:
            print(f"  {fsa}: NOT FOUND")
            continue
        print(f"  {fsa}: hh={e['households']}, "
              f"income={e['median_household_income_cad']}, "
              f"avg_size={e['avg_household_size']}, "
              f"natgas={e['heating_mix']['natural_gas']:.2f}, "
              f"elec={e['heating_mix']['electric_baseboard']:.2f}")
    print(
        "\nNext step: replace `_FSA_REGISTRY = {...}` block in "
        "backend/services/statscan.py with:\n"
        "    from backend.services._fsa_data_generated import _FSA_REGISTRY\n"
    )


if __name__ == "__main__":
    main()
