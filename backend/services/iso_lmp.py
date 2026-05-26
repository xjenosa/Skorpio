"""
ISO LMP & transmission constraint client. A structured-data source the
Grid Intelligence agent queries to enrich a candidate region with
operational specifics (LMP zones, transmission constraints, queue
position).

Supports PJM Data Miner 2, ERCOT MIS API, CAISO OASIS, MISO and SPP.
All ISO surfaces share a common (region, zone, lmp, congestion, loss) shape
once normalised through this client.
"""
from typing import Optional

import httpx

from backend.config import settings
from backend.utils.cache import grid_cache
from backend.utils.logger import get_logger

logger = get_logger(__name__)

NORMALISED_FIELDS = (
    "iso,zone,timestamp,lmp_usd_mwh,energy_usd_mwh,"
    "congestion_usd_mwh,loss_usd_mwh,interface,"
)


class ISOClient:
    def __init__(self):
        self.pjm_base = settings.pjm_base_url
        self.pjm_key = settings.pjm_api_key
        self.ercot_base = settings.ercot_base_url
        self.ercot_key = settings.ercot_api_key
        self.caiso_base = settings.caiso_oasis_base_url
        self.miso_base = settings.miso_base_url
        self.spp_base = settings.spp_base_url

    async def get_zone_lmp(
        self,
        iso_code: str,
        zone: str,
        reviewed_only: bool = True,
    ) -> list[dict]:
        """Fetch the latest hour of LMP for a (iso, zone) tuple."""
        cache_key = f"zone_lmp:{iso_code}:{zone}:{reviewed_only}"
        cached = await grid_cache.aget(cache_key)
        if cached:
            return cached

        iso_root = iso_code.split("-")[0].upper()
        try:
            if iso_root == "PJM":
                rows = await self._pjm_lmp(zone)
            elif iso_root == "ERCOT":
                rows = await self._ercot_lmp(zone)
            elif iso_root == "CAISO":
                rows = await self._caiso_lmp(zone)
            elif iso_root == "MISO":
                rows = await self._miso_lmp(zone)
            elif iso_root == "SPP":
                rows = await self._spp_lmp(zone)
            else:
                rows = []
        except Exception as e:
            logger.warning(f"ISO LMP fetch failed for {iso_code}/{zone}: {e}")
            rows = []

        await grid_cache.aset(cache_key, rows)
        return rows

    async def get_topology(self, iso_code: str) -> Optional[dict]:
        """Return a transmission-topology snapshot for `iso_code`."""
        cache_key = f"topology:{iso_code}"
        cached = await grid_cache.aget(cache_key)
        if cached:
            return cached

        # Real implementations should pull from each ISO's open data portal.
        # Here we record the structure so the rest of the pipeline can rely on it.
        topology: dict = {"iso_code": iso_code, "substations": [], "transmission": []}
        await grid_cache.aset(cache_key, topology)
        return topology

    # ────────────────────────────────────────────────────────────────────
    # ISO-specific endpoints
    # ────────────────────────────────────────────────────────────────────

    async def _pjm_lmp(self, zone: str) -> list[dict]:
        if not self.pjm_key:
            return []
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{self.pjm_base}/rt_lmps",
                params={"pricingnode": zone, "rowCount": 1},
                headers={"Ocp-Apim-Subscription-Key": self.pjm_key},
            )
            if r.status_code != 200:
                return []
            return _normalise_pjm(r.json())

    async def _ercot_lmp(self, zone: str) -> list[dict]:
        if not self.ercot_key:
            return []
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{self.ercot_base}/np6-905-cd/spp_node_zone_hub",
                params={"settlementPoint": zone, "size": 1},
                headers={"Ocp-Apim-Subscription-Key": self.ercot_key},
            )
            if r.status_code != 200:
                return []
            return _normalise_ercot(r.json())

    async def _caiso_lmp(self, zone: str) -> list[dict]:
        # CAISO OASIS uses a SingleZip CSV; here we return the empty list and
        # let the orchestrator fall back to EIA aggregate prices if absent.
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{self.caiso_base}/SingleZip",
                params={
                    "queryname": "PRC_LMP",
                    "version": "1",
                    "market_run_id": "RTM",
                    "node": zone,
                    "resultformat": "6",
                },
            )
            if r.status_code != 200:
                return []
            return _normalise_caiso(r.text)

    async def _miso_lmp(self, zone: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{self.miso_base}/MISORTWDDataBroker/DataBrokerServices.asmx/getLMPMonth",
                params={"node": zone},
            )
            if r.status_code != 200:
                return []
            return _normalise_generic(r.json(), "MISO", zone)

    async def _spp_lmp(self, zone: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{self.spp_base}/download",
                params={"path": "%2FFinal-Prices%2FDay-Ahead%2F" + zone},
            )
            if r.status_code != 200:
                return []
            return _normalise_generic(r.json(), "SPP", zone)

    # ────────────────────────────────────────────────────────────────────
    # Field extraction helpers (mirror UniProt's extract_*)
    # ────────────────────────────────────────────────────────────────────

    def extract_zones(self, topology: dict) -> list[str]:
        """Pull zone IDs out of a topology snapshot."""
        return [s.get("zone", "") for s in topology.get("substations", []) if s.get("zone")]

    def extract_load_zone(self, topology: dict) -> str:
        """Pick a representative load zone for the region."""
        zones = self.extract_zones(topology)
        return zones[0] if zones else ""

    def extract_authorities(self, topology: dict) -> list[dict]:
        """Return the list of balancing authorities operating on the topology."""
        out: list[dict] = []
        for s in topology.get("substations", []):
            owner = s.get("owner")
            if owner:
                out.append({"name": owner, "operator": owner})
        return out


def _normalise_pjm(payload: dict) -> list[dict]:
    items = payload.get("items", payload if isinstance(payload, list) else [])
    rows = []
    for item in items:
        rows.append({
            "iso": "PJM",
            "zone": item.get("pricingnode", ""),
            "timestamp": item.get("datetime_beginning_ept", ""),
            "lmp_usd_mwh": _safe(item.get("total_lmp_rt")),
            "energy_usd_mwh": _safe(item.get("system_energy_price_rt")),
            "congestion_usd_mwh": _safe(item.get("congestion_price_rt")),
            "loss_usd_mwh": _safe(item.get("marginal_loss_price_rt")),
        })
    return rows


def _normalise_ercot(payload: dict) -> list[dict]:
    rows = []
    for item in payload.get("data", []):
        rows.append({
            "iso": "ERCOT",
            "zone": item.get("settlementPoint", ""),
            "timestamp": item.get("deliveryDate", ""),
            "lmp_usd_mwh": _safe(item.get("settlementPointPrice")),
            "energy_usd_mwh": _safe(item.get("settlementPointPrice")),
            "congestion_usd_mwh": 0.0,
            "loss_usd_mwh": 0.0,
        })
    return rows


def _normalise_caiso(csv_text: str) -> list[dict]:
    rows = []
    try:
        import io, csv
        reader = csv.DictReader(io.StringIO(csv_text))
        for r in reader:
            rows.append({
                "iso": "CAISO",
                "zone": r.get("NODE", ""),
                "timestamp": r.get("INTERVALSTARTTIME_GMT", ""),
                "lmp_usd_mwh": _safe(r.get("LMP_PRC")),
                "energy_usd_mwh": _safe(r.get("ENERGY_PRC")),
                "congestion_usd_mwh": _safe(r.get("CONGESTION_PRC")),
                "loss_usd_mwh": _safe(r.get("LOSS_PRC")),
            })
    except Exception as e:
        logger.warning(f"CAISO CSV parse error: {e}")
    return rows


def _normalise_generic(payload: dict, iso: str, zone: str) -> list[dict]:
    rows = []
    for item in payload.get("LMPData", payload.get("data", [])):
        rows.append({
            "iso": iso,
            "zone": item.get("node", zone),
            "timestamp": item.get("ts", ""),
            "lmp_usd_mwh": _safe(item.get("lmp")),
            "energy_usd_mwh": _safe(item.get("energy")),
            "congestion_usd_mwh": _safe(item.get("congestion")),
            "loss_usd_mwh": _safe(item.get("loss")),
        })
    return rows


def _safe(val) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


iso_client = ISOClient()
