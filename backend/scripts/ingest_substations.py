"""
Ingest electrical-substation locations from OpenStreetMap via the Overpass
API for all of Canada, and emit a per-utility list with real coordinates,
voltage, and names. Replaces the synthesised asset coordinates in
utility_assets.py for the utilities OSM has good coverage of (Hydro One,
Toronto Hydro, BC Hydro, Hydro-Québec) with the real ones.

OSM coverage caveats:
  - Asset AGE and REPLACEMENT COST are NOT public anywhere; those stay
    estimated. We only refine lat/lon/voltage/name/operator.
  - Some smaller substations have incomplete tags. We keep what's filled
    in and skip the rest.

Source: https://www.openstreetmap.org/ (ODbL licence; attribute on use)
Query: power=substation, country=Canada, voltage >= 25 kV.

Usage:

    python -m backend.scripts.ingest_substations

Cache: data/cache/osm_substations_ca.json (~few MB). Re-run to refresh.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHED_JSON = CACHE_DIR / "osm_substations_ca.json"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_substations_generated.py"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "Skorpio/1.0 (skorpio@energyplacement.ai)"

# Voltage threshold — OSM tags often include both substation transformer and
# tiny distribution kiosks. 25 kV catches HV transmission + sub-transmission
# while excluding the smallest service equipment.
MIN_VOLTAGE_V = 25_000

# Canonicalize free-text "operator" values to the keys we use in
# utility_assets._REGISTRY. Anything not in this map gets a normalised
# slug as its key so the output stays grep-friendly.
OPERATOR_CANONICAL: dict[str, str] = {
    "hydro one": "hydro one",
    "hydro one networks": "hydro one",
    "hydro one networks inc.": "hydro one",
    "toronto hydro": "toronto hydro",
    "toronto hydro-electric system": "toronto hydro",
    "toronto hydro-electric system limited": "toronto hydro",
    "alectra": "alectra",
    "alectra utilities": "alectra",
    "alectra utilities corporation": "alectra",
    "hydro ottawa": "hydro ottawa",
    "hydro ottawa limited": "hydro ottawa",
    "epcor": "epcor",
    "epcor distribution": "epcor",
    "hydro-québec": "hydro-québec",
    "hydro-quebec": "hydro-québec",
    "hydroquebec": "hydro-québec",
    "hydro québec": "hydro-québec",
    "bc hydro": "bc hydro",
    "british columbia hydro and power authority": "bc hydro",
    "manitoba hydro": "manitoba hydro",
    "saskpower": "saskpower",
    "nb power": "nb power",
    "ns power": "ns power",
    "nova scotia power": "ns power",
    "newfoundland and labrador hydro": "nl hydro",
    "nl hydro": "nl hydro",
    "yec": "yec",
    "yukon energy": "yec",
}

OVERPASS_QUERY = """
[out:json][timeout:240];
area["ISO3166-1"="CA"][admin_level=2]->.canada;
(
  node["power"="substation"](area.canada);
  way["power"="substation"](area.canada);
);
out center tags;
""".strip()


# ── Download ────────────────────────────────────────────────────────────── #

def _download_if_missing() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHED_JSON.exists() and CACHED_JSON.stat().st_size > 50_000:
        print(f"[ok] Using cached {CACHED_JSON.name} ({CACHED_JSON.stat().st_size / 1e6:.1f} MB)")
        return CACHED_JSON
    print("[..] Querying OSM Overpass API for Canadian substations (1-3 min)...")
    body = f"data={OVERPASS_QUERY}".encode("utf-8")
    req = Request(OVERPASS_URL, data=body, headers={
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with urlopen(req, timeout=300) as resp, CACHED_JSON.open("wb") as out:
        while chunk := resp.read(1 << 16):
            out.write(chunk)
    print(f"[ok] Saved to {CACHED_JSON} ({CACHED_JSON.stat().st_size / 1e6:.1f} MB)")
    return CACHED_JSON


# ── Parse ───────────────────────────────────────────────────────────────── #

def _max_voltage_v(voltage_tag: str | None) -> int:
    """OSM 'voltage' can be a single value or a semicolon-separated list
    (e.g. '230000;115000'). Return the largest, in volts."""
    if not voltage_tag:
        return 0
    best = 0
    for token in re.split(r"[;,/ ]+", voltage_tag):
        token = token.strip()
        if not token:
            continue
        try:
            v = int(float(token))
        except ValueError:
            continue
        if v > best:
            best = v
    return best


def _canon_operator(raw: str | None) -> str:
    if not raw:
        return ""
    key = re.sub(r"\s+", " ", raw.strip().lower())
    return OPERATOR_CANONICAL.get(key, key)


def parse(path: Path) -> dict[str, list[dict]]:
    """Returns {canonical_operator: [substation_dict, ...]} for substations
    above MIN_VOLTAGE_V. Substations with no operator tag are grouped under
    "unknown" (we still keep them for province-level coverage stats)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    by_op: dict[str, list[dict]] = defaultdict(list)

    for elem in data.get("elements", []):
        tags = elem.get("tags") or {}
        voltage = _max_voltage_v(tags.get("voltage"))
        if voltage < MIN_VOLTAGE_V:
            continue
        lat = elem.get("lat") or (elem.get("center") or {}).get("lat")
        lon = elem.get("lon") or (elem.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        operator = _canon_operator(tags.get("operator"))
        by_op[operator or "unknown"].append({
            "osm_id": f"{elem['type']}/{elem['id']}",
            "name": tags.get("name") or "",
            "lat": round(float(lat), 6),
            "lon": round(float(lon), 6),
            "voltage_v": voltage,
            "substation_kind": tags.get("substation") or "",
            "raw_operator": tags.get("operator") or "",
        })

    # Sort each operator's list by descending voltage so the largest are first.
    for op in by_op:
        by_op[op].sort(key=lambda s: -s["voltage_v"])
    return dict(by_op)


# ── Emit ────────────────────────────────────────────────────────────────── #

HEADER = '''"""
Auto-generated electrical-substation catalog for Canadian utilities,
sourced from OpenStreetMap via the Overpass API (power=substation,
country=CA, voltage>=25kV).

OSM has good coverage of major transmission substations. Field meanings:
  osm_id           — OSM element id ("node/123" or "way/456"); audit-able
                     at https://www.openstreetmap.org/<osm_id>
  name             — operator-published substation name (often blank)
  lat, lon         — WGS84 coordinates
  voltage_v        — primary operating voltage in volts (max of multi-tag)
  substation_kind  — OSM 'substation' tag (transmission/distribution/etc.)
  raw_operator     — original 'operator' tag before canonicalisation

DO NOT EDIT BY HAND - re-run `python -m backend.scripts.ingest_substations`.

Attribution: data © OpenStreetMap contributors, ODbL.
"""

SUBSTATIONS_BY_OPERATOR: dict[str, list[dict]] = {
'''


def emit_python(by_op: dict[str, list[dict]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for op in sorted(by_op):
            sites = by_op[op]
            f.write(f'    {op!r}: [\n')
            for s in sites:
                f.write('        {\n')
                f.write(f'            "osm_id": {s["osm_id"]!r},\n')
                f.write(f'            "name": {s["name"]!r},\n')
                f.write(f'            "lat": {s["lat"]}, "lon": {s["lon"]},\n')
                f.write(f'            "voltage_v": {s["voltage_v"]},\n')
                f.write(f'            "substation_kind": {s["substation_kind"]!r},\n')
                f.write(f'            "raw_operator": {s["raw_operator"]!r},\n')
                f.write('        },\n')
            f.write('    ],\n')
        f.write("}\n")
    print(f"  Wrote {path}")


def main() -> None:
    path = _download_if_missing()
    by_op = parse(path)
    total = sum(len(v) for v in by_op.values())
    print(f"  Parsed {total:,} substations across {len(by_op):,} operators.")
    emit_python(by_op, OUTPUT_FILE)

    print("\nSpot-check (top operators by substation count):")
    ranked = sorted(by_op.items(), key=lambda kv: -len(kv[1]))[:8]
    for op, sites in ranked:
        sample = sites[0] if sites else {}
        print(f"  {op:30s} {len(sites):>4} subs  "
              f"(top: {sample.get('voltage_v', 0)//1000} kV at "
              f"{sample.get('lat')}, {sample.get('lon')})")


if __name__ == "__main__":
    main()
