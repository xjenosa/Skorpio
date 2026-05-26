"""
Verified coordinates for major Canadian cities + a small parser for
"near <city>" / "in <city>" / "around <city>" proximity hints in user
prompts. Used by the Siting agent to anchor Claude-designed parcels
inside a named geographic area instead of letting the model invent
coordinates from training data.

All coordinates here are sourced from OpenStreetMap Nominatim geocoding
of the city name + province (verified at ingest time). The dict is
small on purpose — adding a city means geocoding it via Nominatim and
pasting the verified pair here; do not type from memory (§0).
"""

from __future__ import annotations

import re
from typing import Optional


# City centre lat/lon — sourced from OSM Nominatim with the query pattern
# "{city} {province} Canada". Each entry's coords are reproducible from
# `https://nominatim.openstreetmap.org/search?q=<city>%20<prov>%20Canada`.
CANADIAN_CITY_COORDS: dict[str, tuple[float, float]] = {
    # Ontario
    "toronto":           (43.6532, -79.3832),
    "mississauga":       (43.5890, -79.6441),
    "vaughan":           (43.8361, -79.4983),
    "markham":           (43.8561, -79.3370),
    "brampton":          (43.7315, -79.7624),
    "ottawa":            (45.4215, -75.6972),
    "hamilton":          (43.2561, -79.8729),
    "burlington":        (43.3249, -79.7967),
    "oshawa":            (43.8976, -78.8635),
    "kitchener":         (43.4513, -80.4928),
    "waterloo":          (43.4653, -80.5223),
    "london":            (42.9837, -81.2496),
    "windsor":           (42.2859, -82.9781),
    "barrie":            (44.3893, -79.6901),
    "sudbury":           (46.4927, -80.9912),
    "thunder bay":       (48.4064, -89.2598),
    "kingston":          (44.2312, -76.4860),
    "cambridge":         (43.3616, -80.3144),

    # Quebec
    "montréal":          (45.5017, -73.5673),
    "montreal":          (45.5017, -73.5673),
    "quebec city":       (46.8139, -71.2080),
    "québec":            (46.8139, -71.2080),
    "gatineau":          (45.4278, -75.7110),
    "sherbrooke":        (45.4033, -71.8890),
    "trois-rivières":    (46.3432, -72.5428),
    "trois-rivieres":    (46.3432, -72.5428),

    # Alberta
    "calgary":           (51.0488, -114.0708),
    "edmonton":          (53.5461, -113.4938),
    "red deer":          (52.2681, -113.8112),
    "lethbridge":        (49.6946, -112.8331),
    "medicine hat":      (50.0430, -110.6790),

    # BC
    "vancouver":         (49.2827, -123.1207),
    "victoria":          (48.4283, -123.3650),
    "kelowna":           (49.8879, -119.4959),
    "surrey":            (49.1044, -122.8011),
    "kamloops":          (50.6745, -120.3273),

    # Manitoba
    "winnipeg":          (49.8951, -97.1384),
    "brandon":           (49.8479, -99.9531),

    # Saskatchewan
    "saskatoon":         (52.1332, -106.6700),
    "regina":            (50.4452, -104.6189),

    # Atlantic
    "halifax":           (44.6488, -63.5752),
    "saint john":        (45.2733, -66.0633),
    "moncton":           (46.0878, -64.7782),
    "fredericton":       (45.9636, -66.6431),
    "charlottetown":     (46.2382, -63.1311),
    "st. john's":        (47.5615, -52.7126),
    "st johns":          (47.5615, -52.7126),
}


# Prepositions we accept before a city name. Order matters: longer phrases
# first so "around" doesn't get swallowed by "in".
_PROXIMITY_PREPOSITIONS = ("near ", "around ", "close to ", "in ", "at ", "for ")


def parse_proximity_hint(text: str) -> Optional[dict]:
    """Look for a proximity preposition followed by a known Canadian city
    in the prompt text. Returns {city, lat, lon} for the longest match,
    or None if no known city is mentioned.

    Matching is case-insensitive and tolerates trailing punctuation. We
    deliberately do NOT call out to a live geocoder for unknown cities —
    that would let Claude/training data leak coords into the pipeline.
    Add new cities to CANADIAN_CITY_COORDS via verified Nominatim queries.
    """
    if not text:
        return None
    lower = text.lower()
    # Sort cities by length descending so "thunder bay" beats "bay" if
    # someone ever adds "bay" to the dict.
    candidates = sorted(CANADIAN_CITY_COORDS.keys(), key=len, reverse=True)
    for city in candidates:
        # Look for the city preceded by one of the proximity prepositions,
        # OR appearing on its own as the only geographic noun. The simpler
        # heuristic: word-boundary match preceded by any proximity
        # preposition within 5 characters.
        pattern = re.compile(
            r"\b(?:" + "|".join(re.escape(p.strip()) for p in _PROXIMITY_PREPOSITIONS)
            + r")\s+" + re.escape(city) + r"\b",
            re.IGNORECASE,
        )
        if pattern.search(lower):
            lat, lon = CANADIAN_CITY_COORDS[city]
            return {"city": city.title(), "lat": lat, "lon": lon}
    return None
