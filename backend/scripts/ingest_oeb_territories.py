"""
Ingest the Ontario Energy Board's Distributor Service Territories KMZ and
emit two artifacts:

  1. `data/oeb/all_ldcs.geojson` — a color-coded GeoJSON of every Ontario
     LDC's franchise polygon, used for visual verification (open in
     https://geojson.io). One feature per utility, polygons preserved as
     MultiPolygon. Properties carry simplestyle-spec fields (fill, stroke)
     so geojson.io renders distinct colors per utility automatically.

  2. (Checkpoint 4 — added in a follow-up edit)
     `backend/services/_oeb_territories_generated.py` — the same polygons
     packaged for runtime point-in-polygon checks. The siting pipeline's
     utility-territory filter calls into this instead of the 40 km
     substation-radius proxy.

Why this exists: the territory-routing fix for the Kingston bug uses a
40 km radius around real OSM substations as a proxy for LDC franchise
boundaries. That works for the demo but isn't the legal reality —
franchise areas follow street/township lines, not circles. The OEB
publishes the actual boundaries as open data. Per REPORTS_COHESION.md §0,
trading a documented heuristic for the real boundary is the right
upgrade path.

Source dataset:
  - https://www.oeb.ca/open-data/electricity-and-natural-gas-distributors-service-areas
  - File: open-data-electricity-map-20260225.zip (~2 MB, KMZ inside)
  - License: Open Government Licence – Ontario
  - Last updated: 2026-02-25

Usage:
    docker compose exec api python -m backend.scripts.ingest_oeb_territories

Idempotent. Reads `data/oeb/doc.kml` (extracted from the KMZ; commit the
KMZ to the repo, leave doc.kml extracted alongside for the script). Safe
to re-run.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

# Project layout — script lives in backend/scripts/, data sits at
# repo_root/data/oeb/. Resolve both relative to this file's location so
# the script works from any cwd.
HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parent.parent.parent           # …/Skorpio/
KML_PATH = REPO_ROOT / "data" / "oeb" / "doc.kml"
OUT_GEOJSON = REPO_ROOT / "data" / "oeb" / "all_ldcs.geojson"
OUT_RUNTIME = REPO_ROOT / "backend" / "services" / "_oeb_territories_generated.py"

NS = {"kml": "http://www.opengis.net/kml/2.2"}


def _parse_coord_block(text: str) -> list[list[float]]:
    """KML coords format: 'lon,lat[,alt] lon,lat[,alt] ...' whitespace-separated.
    GeoJSON wants [[lon, lat], ...] with no altitude."""
    out: list[list[float]] = []
    for tok in text.split():
        parts = tok.split(",")
        if len(parts) >= 2:
            try:
                lon = float(parts[0])
                lat = float(parts[1])
            except ValueError:
                continue
            out.append([lon, lat])
    return out


def _extract_polygons(placemark: ET.Element) -> list[list[list[list[float]]]]:
    """Return GeoJSON-shaped coordinates for one placemark's polygons.

    A KML <Polygon> has one <outerBoundaryIs><LinearRing><coordinates>
    plus zero or more <innerBoundaryIs> (holes — donut-shaped territories
    where a LDC carves out a sub-municipality served by a different LDC).
    Returns: list of polygons; each polygon is [outer_ring, hole_ring_1, ...]
    in GeoJSON Polygon format. Top-level list maps to GeoJSON MultiPolygon.
    """
    polys: list[list[list[list[float]]]] = []
    for poly in placemark.iter("{http://www.opengis.net/kml/2.2}Polygon"):
        rings: list[list[list[float]]] = []

        outer_el = poly.find("kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", NS)
        if outer_el is None or not (outer_el.text and outer_el.text.strip()):
            continue
        outer = _parse_coord_block(outer_el.text)
        if len(outer) < 4:
            continue
        rings.append(outer)

        for inner_el in poly.findall("kml:innerBoundaryIs/kml:LinearRing/kml:coordinates", NS):
            if not (inner_el.text and inner_el.text.strip()):
                continue
            inner = _parse_coord_block(inner_el.text)
            if len(inner) >= 4:
                rings.append(inner)

        polys.append(rings)
    return polys


def _color_for(name: str) -> str:
    """Deterministic hex color per utility name. Uses zlib.crc32 (§8c —
    NEVER hash(), which is per-process randomized) so the same utility
    always renders in the same color across runs and across processes."""
    hue = zlib.crc32(name.encode()) % 360
    # HSL → RGB at S=70%, L=50% gives vibrant, distinguishable colors.
    h = hue / 60.0
    c = 0.7
    x = c * (1 - abs((h % 2) - 1))
    if h < 1:   r, g, b = c, x, 0.0
    elif h < 2: r, g, b = x, c, 0.0
    elif h < 3: r, g, b = 0.0, c, x
    elif h < 4: r, g, b = 0.0, x, c
    elif h < 5: r, g, b = x, 0.0, c
    else:       r, g, b = c, 0.0, x
    m = 0.5 - c / 2
    R, G, B = int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)
    return f"#{R:02x}{G:02x}{B:02x}"


def _placemark_metadata(placemark: ET.Element) -> dict:
    """Pull the OEB licence number out of the <description> HTML if present.
    Best-effort — falls back to empty string when the description format
    drifts in a future refresh."""
    desc = placemark.find("kml:description", NS)
    out = {}
    if desc is not None and desc.text:
        text = desc.text
        # The KML description is HTML; the licence number sits between
        # "OEB License No." and the next "<" in the cell.
        marker = "OEB License No."
        idx = text.find(marker)
        if idx != -1:
            tail = text[idx + len(marker):]
            # Strip HTML tags and grab the first license-looking token.
            import re
            m = re.search(r"[A-Z]{2}-\d{4}-\d{4}", tail)
            if m:
                out["license"] = m.group(0)
    return out


def main() -> int:
    if not KML_PATH.exists():
        print(f"ERROR: KML not found at {KML_PATH}", file=sys.stderr)
        print(
            "Extract the OEB KMZ first: unzip the .kmz file into the same dir.",
            file=sys.stderr,
        )
        return 2

    tree = ET.parse(KML_PATH)
    root = tree.getroot()

    features = []
    per_utility_stats: list[tuple[str, int, int]] = []  # (name, patches, vertices)

    for placemark in root.iter("{http://www.opengis.net/kml/2.2}Placemark"):
        name_el = placemark.find("kml:name", NS)
        if name_el is None:
            continue
        name = (name_el.text or "").strip()
        if not name or name.startswith("Electric_"):
            # Skip the top-level container placemark that wraps the file.
            continue

        polys = _extract_polygons(placemark)
        if not polys:
            continue

        color = _color_for(name)
        metadata = _placemark_metadata(placemark)

        feature = {
            "type": "Feature",
            "properties": {
                "utility": name,
                "license": metadata.get("license", ""),
                "polygon_patches": len(polys),
                # simplestyle-spec: geojson.io reads these to color the polygon.
                "fill": color,
                "fill-opacity": 0.45,
                "stroke": color,
                "stroke-width": 1,
                "stroke-opacity": 0.9,
            },
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": polys,
            },
        }
        features.append(feature)

        vertex_count = sum(len(ring) for poly in polys for ring in poly)
        per_utility_stats.append((name, len(polys), vertex_count))

    if not features:
        print("ERROR: no utility features extracted", file=sys.stderr)
        return 1

    fc = {
        "type": "FeatureCollection",
        "properties": {
            "source": "OEB Open Data, Electric_260225.kmz",
            "source_url": "https://www.oeb.ca/open-data/electricity-and-natural-gas-distributors-service-areas",
            "source_updated": "2026-02-25",
            "license": "Open Government Licence – Ontario",
        },
        "features": features,
    }

    OUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(fc, f)

    # --- Emit the runtime Python module ----------------------------- #
    # Same polygon data but packaged for the territory filter:
    #   TERRITORIES["Alectra Utilities Corporation"] = {
    #       "license": "ED-2016-0360",
    #       "bbox": (min_lat, min_lon, max_lat, max_lon),
    #       "polygons": [
    #           [outer_ring, hole_ring_1, ...],   # one MultiPolygon patch
    #           ...
    #       ],
    #   }
    # Each ring: list of (lon, lat) tuples. (lon-first, matching GeoJSON.)
    # bbox is precomputed so the territory-filter can short-circuit when
    # a point is obviously outside before scanning ~12k vertices.
    runtime_entries: list[str] = []
    for feature in features:
        utility = feature["properties"]["utility"]
        license_no = feature["properties"]["license"]
        coords = feature["geometry"]["coordinates"]
        lons = [p[0] for poly in coords for ring in poly for p in ring]
        lats = [p[1] for poly in coords for ring in poly for p in ring]
        bbox = (min(lats), min(lons), max(lats), max(lons))

        # Polygons as tuples (immutable, smaller pickled memory footprint).
        # Use repr for compactness; the formatter is just whatever Python
        # gives us for nested tuples of floats — fine for a generated file.
        poly_repr = "[\n            " + ",\n            ".join(
            "[" + ", ".join(
                "[" + ", ".join(f"({lon:.6f}, {lat:.6f})" for lon, lat in ring) + "]"
                for ring in poly
            ) + "]"
            for poly in coords
        ) + ",\n        ]"

        runtime_entries.append(
            "    "
            + repr(utility)
            + ": {\n"
            + "        " + repr("license") + ": " + repr(license_no) + ",\n"
            + "        " + repr("bbox") + ": " + repr(bbox) + ",\n"
            + "        " + repr("polygons") + ": " + poly_repr + ",\n"
            + "    },"
        )

    OUT_RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_RUNTIME, "w", encoding="utf-8") as f:
        f.write(
            '"""\n'
            "AUTO-GENERATED by backend/scripts/ingest_oeb_territories.py.\n"
            "DO NOT EDIT BY HAND — re-run the ingest script after a refresh.\n\n"
            "Source: OEB Open Data — Electric_260225.kmz (2026-02-25)\n"
            "License: Open Government Licence – Ontario\n"
            "URL: https://www.oeb.ca/open-data/electricity-and-natural-gas-distributors-service-areas\n\n"
            "Used by backend/services/oeb_territory.py for point-in-polygon\n"
            "checks in the Siting territory filter.\n"
            '"""\n\n'
            "TERRITORIES: dict[str, dict] = {\n"
            + "\n".join(runtime_entries)
            + "\n}\n"
        )
    print(f"  Runtime module: {OUT_RUNTIME} ({OUT_RUNTIME.stat().st_size / 1024:.0f} KB)")

    # --- Verification summary ---------------------------------------- #
    total_vertices = sum(v for _, _, v in per_utility_stats)
    total_patches = sum(p for _, p, _ in per_utility_stats)
    print(f"Extracted {len(features)} utility polygons")
    print(f"  Total polygon patches: {total_patches:,}")
    print(f"  Total vertices: {total_vertices:,}")
    print(f"  Output: {OUT_GEOJSON} ({OUT_GEOJSON.stat().st_size / 1024:.0f} KB)")
    print()

    # Spot-check the utilities the territory filter actually cares about.
    SPOT_CHECK = [
        "Alectra Utilities Corporation",
        "Toronto Hydro-Electric System Limited",
        "Hydro Ottawa Limited",
        "Hydro One Networks Inc.",
        "Hydro One Networks Inc",
        "Hydro One Networks Inc. - Brampton",
    ]
    by_name = {name: (patches, verts) for name, patches, verts in per_utility_stats}
    print("Spot-check (utilities the routing logic depends on):")
    for needle in SPOT_CHECK:
        matches = [(n, p, v) for n, p, v in per_utility_stats if needle.lower() in n.lower()]
        for n, p, v in matches:
            print(f"  [ok] {n:<55} {p:>3} patches  {v:>6,} vertices")

    return 0


if __name__ == "__main__":
    sys.exit(main())
