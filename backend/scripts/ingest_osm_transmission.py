"""
Ingest OpenStreetMap transmission lines (way[power=line]) for Canada via
Overpass API. Replaces the lack of any real transmission-line topology
in the pipeline.

For each high-voltage way (≥69 kV) we record:
  - start coordinate, end coordinate
  - voltage (V)
  - operator (if tagged)
  - estimated length (km, sum of segment haversines)

Source: OpenStreetMap Overpass API
  https://overpass-api.de/api/interpreter

Usage:

    python -m backend.scripts.ingest_osm_transmission

Cache: data/cache/osm_transmission.json. Re-run to refresh.
"""

from __future__ import annotations

import json
import re
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Nation-wide Canada queries time out at 120s on the public Overpass
# instance. We split the request into 13 per-province (ISO3166-2) queries
# and use `out tags center;` (one coordinate per way) instead of `geom`
# (full geometry) so the response stays small.
PROVINCE_CODES = [
    "CA-ON", "CA-QC", "CA-AB", "CA-BC", "CA-MB", "CA-SK",
    "CA-NB", "CA-NS", "CA-NL", "CA-PE", "CA-YT", "CA-NT", "CA-NU",
]

QUERY_TPL = """[out:json][timeout:90];
area["ISO3166-2"="{prov}"]->.p;
(
  way["power"="line"]["voltage"](area.p);
);
out tags center;
"""

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHED_JSON = CACHE_DIR / "osm_transmission.json"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_transmission_lines_generated.py"

MIN_VOLTAGE_V = 69_000


def _download_one_province(prov: str) -> Path | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / f"osm_transmission_{prov}.json"
    if target.exists() and target.stat().st_size > 5_000:
        print(f"  [ok] {prov}: cached ({target.stat().st_size / 1e3:.0f} KB)")
        return target
    print(f"  [..] {prov}: querying Overpass ...")
    data = urlencode({"data": QUERY_TPL.format(prov=prov)}).encode("utf-8")
    req = Request(OVERPASS_URL, data=data,
                  headers={"User-Agent": "Skorpio/1.0 (skorpio@energyplacement.ai)"})
    try:
        with urlopen(req, timeout=150) as resp, target.open("wb") as out:
            while chunk := resp.read(1 << 16):
                out.write(chunk)
        size = target.stat().st_size
        if size < 1000:
            print(f"  [warn] {prov}: response too small ({size} bytes), skipping")
            return None
        print(f"  [ok] {prov}: saved ({size / 1e3:.0f} KB)")
        return target
    except Exception as e:
        print(f"  [warn] {prov}: {e}")
        return None


def _download_if_missing() -> list[Path]:
    """Fetch one JSON per province; return list of paths that worked."""
    out: list[Path] = []
    for prov in PROVINCE_CODES:
        p = _download_one_province(prov)
        if p:
            out.append(p)
    return out


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _parse_voltage(s: str) -> int | None:
    """Voltage tags in OSM are messy: '230000', '230 kV', '230kV;115kV', etc.
    Take the max numeric value, interpret bare numbers as V and 'kV' as kV."""
    if not s:
        return None
    best = 0
    for piece in re.split(r"[;,/]", s):
        p = piece.strip().lower().replace(" ", "")
        m = re.match(r"(\d+(?:\.\d+)?)\s*(kv)?$", p)
        if not m:
            continue
        v = float(m.group(1))
        if m.group(2) == "kv":
            v *= 1000
        if v > best:
            best = int(v)
    return best or None


def parse_all(json_paths: list[Path]) -> list[dict]:
    """Parse a list of per-province JSON files into a flat line catalog.
    Each way contributes a single `center` point (lat, lon) and the
    operator tag if present. Length is unavailable from `out tags center;`
    queries — we keep an empty `length_km` field for forward compatibility."""
    lines: list[dict] = []
    for json_path in json_paths:
        try:
            with json_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            print(f"  [warn] failed to parse {json_path.name}: {e}")
            continue
        for el in payload.get("elements", []):
            if el.get("type") != "way":
                continue
            tags = el.get("tags", {}) or {}
            voltage = _parse_voltage(tags.get("voltage", ""))
            if not voltage or voltage < MIN_VOLTAGE_V:
                continue
            center = el.get("center") or {}
            lat = center.get("lat")
            lon = center.get("lon")
            if lat is None or lon is None:
                continue
            lines.append({
                "id": el.get("id"),
                "voltage_v": voltage,
                "operator": tags.get("operator", ""),
                "lat": round(lat, 5),
                "lon": round(lon, 5),
            })
    # De-dup by way id since a way that crosses a province boundary may
    # be returned by both province queries.
    seen: set = set()
    unique: list[dict] = []
    for l in lines:
        if l["id"] in seen:
            continue
        seen.add(l["id"])
        unique.append(l)
    unique.sort(key=lambda l: -l["voltage_v"])
    return unique


HEADER = '''"""
Auto-generated Canadian transmission-line catalog. Source: OpenStreetMap
Overpass API, filter `way[power=line][voltage]` inside each province,
≥69 kV only. Each entry is one way's center coordinate + tagged voltage
and operator.

Fields: id, voltage_v, operator (if tagged), lat, lon.

The center coordinate is the way's geometry midpoint (per Overpass
`out tags center;`) — not the same as line endpoints. For
distance-to-nearest-line calculations the midpoint is a reasonable
proxy; for precise routing use a richer query.

DO NOT EDIT BY HAND - re-run `python -m
backend.scripts.ingest_osm_transmission`.

Used by:
  - services/utility_assets.py — synthesized transmission-line catalog
    can now anchor on a real OSM line for the operator when one exists
  - grid/generator.py — `substation_distance_km` can be tightened by
    checking distance to nearest transmission line midpoint
"""

TRANSMISSION_LINES: list[dict] = [
'''


def emit_python(lines: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for l in lines:
            f.write(f'    {{"id": {l["id"]}, '
                    f'"voltage_v": {l["voltage_v"]}, '
                    f'"operator": {json.dumps(l["operator"])}, '
                    f'"lat": {l["lat"]}, '
                    f'"lon": {l["lon"]}}},\n')
        f.write("]\n\n")
        f.write("# Operator → list of lines (operator string as tagged in OSM, "
                "lowercased / collapsed whitespace).\n")
        f.write("import re as _re\n")
        f.write("def _norm_op(s): return _re.sub(r'\\s+', ' ', (s or '').strip().lower())\n")
        f.write("TRANSMISSION_LINES_BY_OPERATOR: dict[str, list[dict]] = {}\n")
        f.write("for _l in TRANSMISSION_LINES:\n")
        f.write("    _k = _norm_op(_l['operator'])\n")
        f.write("    if _k:\n")
        f.write("        TRANSMISSION_LINES_BY_OPERATOR.setdefault(_k, []).append(_l)\n")
    print(f"  Wrote {path}")


def main() -> None:
    json_paths = _download_if_missing()
    if not json_paths:
        raise SystemExit("No province queries returned data; aborting.")
    lines = parse_all(json_paths)
    print(f"  Parsed {len(lines)} transmission ways across {len(json_paths)} provinces.")
    emit_python(lines, OUTPUT_FILE)

    print("\nSpot-check: voltage distribution (top 6 by line count):")
    from collections import Counter
    voltages = Counter(l["voltage_v"] for l in lines)
    for v, c in voltages.most_common(6):
        print(f"  {v // 1000} kV: {c} lines")

    operators = Counter(l["operator"] for l in lines if l["operator"])
    print("\nTop 8 operators (by line count):")
    for op, c in operators.most_common(8):
        print(f"  {op}: {c} lines")


if __name__ == "__main__":
    main()
