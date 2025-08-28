from typing import TypedDict
from stats.psyduckv2.init import get_psyduck_client
from stats.psyduckv2.gets import (
    get_cached_geofences,
)

class GeofenceArea(TypedDict):
    id: int
    name: str

async def fetch_area_list_from_geofences() -> list[GeofenceArea]:
    # Returns [{"id": ..., "name": ...}, ...] — coordinates ignored for UI
    async with get_psyduck_client() as api:
        geos = await get_cached_geofences(api)
    # be defensive; only keep id+name
    areas = []
    for g in geos or []:
        nm = (g.get("name") or "").strip()
        if nm:
            areas.append({"id": g.get("id"), "name": nm})
    # sort by name asc for nicer UX
    areas.sort(key=lambda x: (x["name"] or "").lower())
    return areas
