"""
Stage 2 of Neighborhood Electrification Readiness: fetch demographic and
housing data per FSA. Combines live ArcGIS World Geocoding lookups (with
zippopotam.us fallback) and ArcGIS GeoEnrichment overlays on top of the
calibrated StatsCan FSA registry.
"""
import asyncio

from backend.agents.base_agent import BaseAgent
from backend.models.electrification import ElectrificationSpec, NeighborhoodProfile
from backend.services.statscan import get_profile


class NeighborhoodProfileAgent(BaseAgent):
    async def fetch_profiles(
        self,
        spec: ElectrificationSpec,
        progress_callback=None,
    ) -> list[NeighborhoodProfile]:
        if not spec.fsas:
            return []

        if progress_callback:
            await progress_callback(
                f"Fetching demographic + housing data for {len(spec.fsas)} FSA(s)...",
                18,
            )

        # Fan out the live geocode calls; profiles fall back to baked StatsCan
        # registry when the FSA is unknown.
        profiles = await asyncio.gather(*(get_profile(f) for f in spec.fsas))
        n_real = sum(1 for p in profiles if not p.is_synthesized)

        if progress_callback:
            await progress_callback(
                f"Loaded {len(profiles)} FSA profile(s) "
                f"({n_real} from live registry, {len(profiles) - n_real} synthesized)",
                25,
            )
        return list(profiles)
