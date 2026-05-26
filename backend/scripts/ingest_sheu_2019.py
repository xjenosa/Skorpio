"""
Ingest the NRCan Survey of Household Energy Use 2019 (SHEU-2019). Replaces
the eyeballed PROVINCE_DEFAULTS heating_mix dict in statscan.py with values
sourced from the actual survey workbook.

Source: NRCan Office of Energy Efficiency. Free download:
  https://oee.nrcan.gc.ca/corporate/statistics/neud/dpa/data_e/downloads/sheu/zip/SH2019e.zip

The bundle ships as a single legacy .xls workbook (`SH2019e.xls`) — one
sheet per published table. We read every sheet, find ones that have both
a regional column header AND a heating-equipment row label, and roll the
rows into a per-region heating-mix breakdown.

Usage:

    python -m backend.scripts.ingest_sheu_2019

Cache: data/cache/sheu2019.zip. Re-run to refresh.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from urllib.request import urlopen

try:
    import xlrd  # supports legacy .xls
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "xlrd is required for SHEU 2019 ingest. Install with: pip install xlrd==2.0.1"
    ) from e


DOWNLOAD_URLS = [
    "https://oee.nrcan.gc.ca/corporate/statistics/neud/dpa/data_e/downloads/sheu/zip/SH2019e.zip",
    "https://oee.nrcan.gc.ca/corporate/statistics/neud/dpa/menus/sheu/2019/downloads/SH2019e.zip",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHED_ZIP = CACHE_DIR / "sheu2019.zip"
EXTRACTED_XLS = CACHE_DIR / "SH2019e.xls"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_sheu_heating_mix_generated.py"


REGION_TO_PROVINCES: dict[str, list[str]] = {
    "atlantic": ["NL", "PE", "NS", "NB"],
    "quebec": ["QC"],
    "ontario": ["ON"],
    "manitoba_saskatchewan": ["MB", "SK"],
    "alberta": ["AB"],
    "british columbia": ["BC"],
}

EQUIPMENT_TO_CATEGORY: dict[str, str] = {
    "natural gas furnace": "natural_gas",
    "natural gas boiler": "natural_gas",
    "natural gas combi": "natural_gas",
    "natural gas": "natural_gas",
    "electric forced-air furnace": "electric_forced_air",
    "electric forced air furnace": "electric_forced_air",
    "electric furnace": "electric_forced_air",
    "electric boiler": "electric_forced_air",
    "electric baseboard": "electric_baseboard",
    "baseboards": "electric_baseboard",
    "baseboard": "electric_baseboard",
    "heat pump": "heat_pump",
    "heating oil": "oil",
    "oil furnace": "oil",
    "oil boiler": "oil",
    "wood stove": "wood",
    "wood": "wood",
    "propane": "other",
    "dual energy": "other",
}


def _download_if_missing() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if EXTRACTED_XLS.exists() and EXTRACTED_XLS.stat().st_size > 50_000:
        print(f"[ok] Using cached .xls at {EXTRACTED_XLS} "
              f"({EXTRACTED_XLS.stat().st_size / 1e3:.0f} KB)")
        return EXTRACTED_XLS
    if not CACHED_ZIP.exists() or CACHED_ZIP.stat().st_size < 50_000:
        last_err: Exception | None = None
        for url in DOWNLOAD_URLS:
            try:
                print(f"[..] Downloading SHEU 2019 bundle from {url} ...")
                with urlopen(url) as resp, CACHED_ZIP.open("wb") as out:
                    while chunk := resp.read(1 << 16):
                        out.write(chunk)
                if CACHED_ZIP.stat().st_size > 50_000:
                    print(f"[ok] Saved to {CACHED_ZIP} "
                          f"({CACHED_ZIP.stat().st_size / 1e3:.0f} KB)")
                    break
            except Exception as e:
                print(f"  [warn] {e}")
                last_err = e
        else:
            raise SystemExit(f"All SHEU download URLs failed. Last: {last_err}")
    # Extract the .xls so xlrd can open it.
    with zipfile.ZipFile(CACHED_ZIP) as zf:
        for n in zf.namelist():
            if n.lower().endswith(".xls"):
                zf.extract(n, CACHE_DIR)
                src = CACHE_DIR / n
                src.rename(EXTRACTED_XLS)
                print(f"[ok] Extracted {EXTRACTED_XLS} "
                      f"({EXTRACTED_XLS.stat().st_size / 1e3:.0f} KB)")
                return EXTRACTED_XLS
    raise SystemExit(f"No .xls file inside {CACHED_ZIP}")


def _norm(s) -> str:
    if s is None:
        return ""
    s = str(s).strip().lower().replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s)


def _as_float(cell) -> float | None:
    if cell is None or cell == "":
        return None
    try:
        v = float(cell)
        return v if v >= 0 else None
    except (ValueError, TypeError):
        return None


def _classify_equipment(label: str) -> str | None:
    n = _norm(label)
    if not n:
        return None
    for key, cat in EQUIPMENT_TO_CATEGORY.items():
        if key in n:
            return cat
    return None


def aggregate(xls_path: Path) -> dict[str, dict[str, float]]:
    book = xlrd.open_workbook(str(xls_path), formatting_info=False)
    region_tokens = ("atlantic", "quebec", "ontario", "manitoba",
                     "saskatchewan", "alberta", "british columbia",
                     "prairies", "b.c.")

    # region label → category → cumulative share value
    region_buckets: dict[str, dict[str, float]] = {}
    candidate_sheets: list[str] = []

    # SHEU Section 6 = "Space heating". Table 6.1 (in any variant: 6.1, 6.1a,
    # 6.1b, T61a, etc.) is the canonical *main heating equipment* breakdown by
    # region — that's the only table we want. The other Section 6 tables
    # (energy use by source, fuel costs, etc.) would double-count categories
    # if we mixed them in.
    canonical_pattern = re.compile(r"(^|[^0-9])6[._]?1[a-z]?($|[^0-9])", re.I)

    for sheet_name in book.sheet_names():
        if not canonical_pattern.search(sheet_name):
            continue
        sheet = book.sheet_by_name(sheet_name)
        # Read the first ~25 rows as plain strings to detect a region-header row.
        header_idx: int | None = None
        for r in range(min(25, sheet.nrows)):
            row_vals = [_norm(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
            hits = sum(1 for cell in row_vals
                       if any(t in cell for t in region_tokens))
            if hits >= 3:
                header_idx = r
                break
        if header_idx is None:
            continue

        # Map header columns → region key.
        col_to_region: dict[int, str] = {}
        for c in range(sheet.ncols):
            cell = _norm(sheet.cell_value(header_idx, c))
            if not cell:
                continue
            for region_key in REGION_TO_PROVINCES:
                pretty = region_key.replace("_", "/")
                if region_key in cell or pretty in cell:
                    col_to_region[c] = region_key
                    break
            if "manitoba" in cell and "saskatchewan" in cell:
                col_to_region[c] = "manitoba_saskatchewan"
            if "british columbia" in cell or cell == "b.c.":
                col_to_region[c] = "british columbia"
        if not col_to_region:
            continue

        # Look for at least one row that classifies as a heating category.
        # Sheets that match are SHEU heating-equipment tables.
        sheet_hits = 0
        for r in range(header_idx + 1, min(sheet.nrows, header_idx + 60)):
            label = sheet.cell_value(r, 0)
            category = _classify_equipment(label)
            if not category:
                continue
            sheet_hits += 1
            for c, region_key in col_to_region.items():
                v = _as_float(sheet.cell_value(r, c))
                if v is None:
                    continue
                bucket = region_buckets.setdefault(region_key, {})
                bucket[category] = bucket.get(category, 0.0) + v
        if sheet_hits:
            candidate_sheets.append(f"{sheet_name} ({sheet_hits} rows)")

    if candidate_sheets:
        print(f"  Matched {len(candidate_sheets)} heating-equipment sheet(s):")
        for s in candidate_sheets[:12]:
            print(f"    - {s}")
    if not region_buckets:
        raise SystemExit(
            "Parsed 0 region heating mixes. Workbook schema may have shifted; "
            "open SH2019e.xls and check which sheet has the heating-equipment table."
        )

    # Normalize and ensure all categories are present.
    for region_key, cats in region_buckets.items():
        total = sum(cats.values())
        if total > 0:
            for k in list(cats):
                cats[k] = cats[k] / total
        for required in ("natural_gas", "electric_baseboard",
                         "electric_forced_air", "heat_pump", "oil",
                         "wood", "other"):
            cats.setdefault(required, 0.0)

    out: dict[str, dict[str, float]] = {}
    for region_key, cats in region_buckets.items():
        for prov in REGION_TO_PROVINCES.get(region_key, []):
            out[prov] = {k: round(v, 4) for k, v in cats.items()}
    return out


HEADER = '''"""
Auto-generated per-province residential heating-system mix shares. Source:
NRCan Survey of Household Energy Use 2019 (SHEU-2019), main
heating-equipment table from the published `SH2019e.xls` workbook.
Atlantic + Prairie regional buckets are stamped onto each constituent
province (NL/PE/NS/NB; MB/SK).

Shares sum to 1.0 within each province. Categories match the Skorpio
HeatingMix model: natural_gas, electric_baseboard, electric_forced_air,
heat_pump, oil, wood, other.

DO NOT EDIT BY HAND - re-run `python -m backend.scripts.ingest_sheu_2019`.

Used by:
  - services/statscan.py PROVINCE_DEFAULTS heating_mix (overlay)
"""

SHEU_HEATING_MIX_BY_PROVINCE: dict[str, dict[str, float]] = {
'''


def emit_python(per_prov: dict[str, dict[str, float]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for prov in sorted(per_prov):
            cats = per_prov[prov]
            f.write(f'    "{prov}": {{\n')
            for k in ("natural_gas", "electric_baseboard", "electric_forced_air",
                      "heat_pump", "oil", "wood", "other"):
                f.write(f'        "{k}": {cats.get(k, 0.0)},\n')
            f.write(f'    }},\n')
        f.write("}\n")
    print(f"  Wrote {path}")


def main() -> None:
    xls_path = _download_if_missing()
    per_prov = aggregate(xls_path)
    print(f"  Aggregated {len(per_prov)} provinces.")
    emit_python(per_prov, OUTPUT_FILE)

    print("\nSpot-check (heating mix by province):")
    for prov in sorted(per_prov):
        cats = per_prov[prov]
        top = sorted(cats.items(), key=lambda kv: -kv[1])[:3]
        s = ", ".join(f"{k}={v:.0%}" for k, v in top)
        print(f"  {prov}: {s}")


if __name__ == "__main__":
    main()
