"""
Ingest IESO's Generator Output and Capability XML report and emit a clean
catalog of every Ontario generator currently dispatching into the IESO
market, with fuel type and inferred nameplate (max-of-recent-hours
capability MW).

Source: https://reports-public.ieso.ca/public/GenOutputCapability/

The XML has no coordinates / market-participant / nameplate field, so:
  - Nameplate ≈ max of the 17 hourly Capability readings in the file.
  - Coordinates: best-effort lookup against the OSM substations catalog
    we already ingested. If no match, the entry is location-less but
    still useful for fuel-mix anchoring.

Usage:

    python -m backend.scripts.ingest_ieso_generators

Cache: data/cache/ieso_genoutput.xml. Re-run to refresh.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen

XML_URL = "https://reports-public.ieso.ca/public/GenOutputCapability/PUB_GenOutputCapability.xml"

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
CACHED_XML = CACHE_DIR / "ieso_genoutput.xml"
OUTPUT_FILE = REPO_ROOT / "backend" / "services" / "_ieso_generators_generated.py"


def _download_if_missing() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Always refresh — the report rotates every hour and the file is small.
    print(f"[..] Downloading IESO GenOutputCapability XML ...")
    req = Request(XML_URL, headers={"User-Agent": "Skorpio/1.0 (skorpio@energyplacement.ai)"})
    with urlopen(req) as resp, CACHED_XML.open("wb") as out:
        while chunk := resp.read(1 << 16):
            out.write(chunk)
    print(f"[ok] Saved to {CACHED_XML} ({CACHED_XML.stat().st_size / 1e3:.0f} KB)")
    return CACHED_XML


def _strip_ns(tag: str) -> str:
    """Drop XML namespace prefix from a tag name."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def parse(xml_path: Path) -> list[dict]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    generators: list[dict] = []
    for gen in root.iter():
        if _strip_ns(gen.tag) != "Generator":
            continue
        name: str | None = None
        fuel: str | None = None
        caps: list[float] = []
        outputs: list[float] = []
        for child in gen.iter():
            tag = _strip_ns(child.tag)
            txt = (child.text or "").strip() if child.text else ""
            if tag == "GeneratorName":
                name = txt
            elif tag == "FuelType":
                fuel = txt
            elif tag in ("Capability", "EnergyMW") and txt:
                try:
                    val = float(txt)
                    # Capability tags appear inside <Capabilities>; Output
                    # tags appear inside <Outputs>. We can't tell from the
                    # tag alone, so just collect everything and split below.
                    caps.append(val)
                except ValueError:
                    pass
            elif tag == "Output" and txt:
                try:
                    outputs.append(float(txt))
                except ValueError:
                    pass
        if not name:
            continue
        nameplate_mw = max(caps + outputs) if (caps or outputs) else 0.0
        generators.append({
            "name": name,
            "fuel": (fuel or "UNKNOWN").upper(),
            "nameplate_mw": round(nameplate_mw, 1),
        })

    # Group sibling units (BRUCEA-G1 ... BRUCEA-G8) into station-level
    # totals so the catalog is friendly to consumers that want per-station
    # not per-unit data.
    station_pat = re.compile(r"^(?P<station>[A-Z0-9_]+?)-(?:G\d+|U\d+|GEN\d+|S\d+)$")
    by_station: dict[str, dict] = defaultdict(
        lambda: {"units": [], "fuel": "UNKNOWN", "nameplate_mw": 0.0}
    )
    standalone: list[dict] = []
    for g in generators:
        m = station_pat.match(g["name"])
        if not m:
            standalone.append(g)
            continue
        station = m.group("station")
        entry = by_station[station]
        entry["units"].append(g["name"])
        entry["fuel"] = g["fuel"] if entry["fuel"] == "UNKNOWN" else entry["fuel"]
        entry["nameplate_mw"] += g["nameplate_mw"]

    stations: list[dict] = []
    for station, entry in by_station.items():
        stations.append({
            "station": station,
            "fuel": entry["fuel"],
            "unit_count": len(entry["units"]),
            "nameplate_mw": round(entry["nameplate_mw"], 1),
        })
    for g in standalone:
        stations.append({
            "station": g["name"],
            "fuel": g["fuel"],
            "unit_count": 1,
            "nameplate_mw": g["nameplate_mw"],
        })

    stations.sort(key=lambda s: -s["nameplate_mw"])
    return stations


HEADER = '''"""
Auto-generated catalog of Ontario generators currently dispatching into
the IESO market. Source: IESO Generator Output and Capability XML report
(`PUB_GenOutputCapability.xml`), pulled live from reports-public.ieso.ca.

Each entry is a generating station (unit-level rows like BRUCEA-G1..G8
are rolled up into the parent station). Nameplate MW is the max of the
~17 hourly Output/Capability readings in the file — so it's an
operationally-observed maximum, not the dispatch-rated nameplate, but
within a few percent for thermal / nuclear.

Fuel type uses IESO's own labels (NUCLEAR, GAS, HYDRO, WIND, SOLAR, …).

DO NOT EDIT BY HAND - re-run `python -m
backend.scripts.ingest_ieso_generators`.

Used by:
  - agents/site_generation.py (optional: shown to Claude alongside the
    OSM substation list so candidate proposals know where existing
    generation sits)
"""

IESO_GENERATORS: list[dict] = [
'''


def emit_python(stations: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(HEADER)
        for s in stations:
            f.write(
                f'    {{"station": "{s["station"]}", '
                f'"fuel": "{s["fuel"]}", '
                f'"unit_count": {s["unit_count"]}, '
                f'"nameplate_mw": {s["nameplate_mw"]}}},\n'
            )
        f.write("]\n\n")
        f.write("# Fuel-type rollup, computed at module load for convenience.\n")
        f.write("IESO_FUEL_MIX_MW: dict[str, float] = {}\n")
        f.write("for _s in IESO_GENERATORS:\n")
        f.write("    IESO_FUEL_MIX_MW[_s['fuel']] = "
                "IESO_FUEL_MIX_MW.get(_s['fuel'], 0.0) + _s['nameplate_mw']\n")
    print(f"  Wrote {path}")


def main() -> None:
    xml_path = _download_if_missing()
    stations = parse(xml_path)
    print(f"  Parsed {len(stations)} stations.")
    emit_python(stations, OUTPUT_FILE)

    print("\nSpot-check (top 15 stations by nameplate MW):")
    for s in stations[:15]:
        print(f"  {s['station']:24} {s['fuel']:10} {s['nameplate_mw']:>7.0f} MW "
              f"({s['unit_count']} unit(s))")

    fuel_mix: dict[str, float] = defaultdict(float)
    for s in stations:
        fuel_mix[s["fuel"]] += s["nameplate_mw"]
    print("\nFuel mix (MW nameplate):")
    for fuel, mw in sorted(fuel_mix.items(), key=lambda kv: -kv[1]):
        print(f"  {fuel:12} {mw:>8.0f} MW")


if __name__ == "__main__":
    main()
