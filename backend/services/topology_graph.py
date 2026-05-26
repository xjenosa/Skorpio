"""
Transmission topology graph builder.

Takes a region and returns a `{nodes, edges}` graph the frontend renders
as a HUD overlay. Backed by the same ISO topology snapshots used by the
Placement Scoring engine.
"""
from typing import Optional

from backend.services.iso_lmp import iso_client
from backend.utils.logger import get_logger

logger = get_logger(__name__)


async def get_topology_graph(iso_code: str, zone: Optional[str] = None) -> Optional[dict]:
    """
    Build a {nodes, edges} graph for a region's transmission topology.
    Nodes: substations, generators, load zones.
    Edges: transmission lines (with voltage_kv labelled).
    """
    topology = await iso_client.get_topology(iso_code)
    if not topology:
        return None

    nodes = []
    seen = set()
    for sub in topology.get("substations", []):
        key = sub.get("name") or sub.get("id")
        if not key or key in seen:
            continue
        seen.add(key)
        nodes.append({
            "id": key,
            "label": key,
            "type": sub.get("type", "substation"),
            "voltage_kv": sub.get("voltage_kv"),
            "owner": sub.get("owner"),
        })

    edges = []
    for line in topology.get("transmission", []):
        src = line.get("from")
        dst = line.get("to")
        if not src or not dst:
            continue
        edges.append({
            "source": src,
            "target": dst,
            "voltage_kv": line.get("voltage_kv"),
            "owner": line.get("owner"),
            "thermal_rating_mva": line.get("thermal_rating_mva"),
        })

    if not nodes:
        return None

    return {"nodes": nodes, "edges": edges, "iso_code": iso_code, "zone": zone}
