from typing import Any, Dict, List
from loguru import logger
from utils.timing import log_timing
from utils.http_api import APIClient
from core.dragonite.gets import (
    get_status,
    get_proxies_stats,
)

# ---------------------------
# STATUS PROCESSORS
# ---------------------------
def _normalize_areas(payload: Any) -> List[Dict[str, Any]]:
    """
    Accepts either:
      - list[area]
      - {"areas": list[area]}
    Returns list[area]; empty list on anything else.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("areas"), list):
        return payload["areas"]
    logger.debug(f"[Dragonite] Unexpected /status payload shape: {type(payload)}")
    return []

def _iter_all_collections(payload: Any) -> List[List[Dict[str, Any]]]:
    """
    Returns all top-level list-of-dicts collections (e.g., 'areas', 'unbounds', etc.).
    """
    if isinstance(payload, list) and all(isinstance(x, dict) for x in payload):
        return [payload]
    cols: List[List[Dict[str, Any]]] = []
    if isinstance(payload, dict):
        for v in payload.values():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                cols.append(v)
    return cols

@log_timing("status_overview")
async def status_overview(client: APIClient) -> Dict[str, Any]:
    """
    From GET /status:
      - areas: unique/enabled/disabled (from 'areas' only)
      - modes: { <current_mode>: { workers: count } }  (from ALL collections)
      - totals: { expected_workers, active_workers }   (worker-level counts across ALL collections)
      - Ignores LevelMode everywhere
    """
    raw = await get_status(client)

    # Area counts from 'areas'
    areas = _normalize_areas(raw)
    unique = len(areas)
    enabled = sum(1 for a in areas if isinstance(a, dict) and a.get("enabled") is True)
    disabled = unique - enabled

    # Aggregate from all collections (areas, unbounds, etc.), worker-level
    modes: Dict[str, Dict[str, int]] = {}
    total_expected_workers = 0  # number of workers listed (excluding LevelMode)
    total_active_workers = 0    # number of those workers that are active

    def _is_active(worker: Dict[str, Any]) -> bool:
        conn = (worker.get("connection_status") or "").strip().lower()
        last_data = worker.get("last_data") or 0
        return (last_data > 0) and (conn not in ("", "disconnected", "no connection", "offline"))

    for coll in _iter_all_collections(raw):
        for node in coll:
            if not isinstance(node, dict):
                continue

            # Shape A: manager-based (areas)
            managers = node.get("worker_managers")
            if isinstance(managers, list):
                for mgr in managers:
                    workers = mgr.get("workers") or []
                    if isinstance(workers, list):
                        for w in workers:
                            if not isinstance(w, dict):
                                continue
                            mode = w.get("current_mode") or "Unknown"
                            if mode == "LevelMode":
                                continue
                            total_expected_workers += 1
                            if _is_active(w):
                                total_active_workers += 1
                            modes.setdefault(mode, {"workers": 0})["workers"] += 1
                continue  # handled this node

            # Shape B: direct workers (unbounds, etc.)
            workers = node.get("workers")
            if isinstance(workers, list):
                for w in workers:
                    if not isinstance(w, dict):
                        continue
                    mode = w.get("current_mode") or "Unknown"
                    if mode == "LevelMode":
                        continue
                    total_expected_workers += 1
                    if _is_active(w):
                        total_active_workers += 1
                    modes.setdefault(mode, {"workers": 0})["workers"] += 1

    return {
        "areas": {"unique": unique, "enabled": enabled, "disabled": disabled},
        "modes": modes,  # per-mode worker counts (excluding LevelMode)
        "totals": {"expected_workers": total_expected_workers, "active_workers": total_active_workers},
    }

@log_timing("status_area_map")
async def status_area_map(client: APIClient) -> List[Dict[str, Any]]:
    """
    From GET /status: return simple list of {id, name}
    """
    raw = await get_status(client)
    areas = _normalize_areas(raw)
    simple = []
    for a in areas:
        if isinstance(a, dict):
            simple.append({"id": a.get("id"), "name": a.get("name")})
    return simple


# ---------------------------
# PROXIES PROCESSORS
# ---------------------------

@log_timing("proxies_provider_summary")
async def proxies_provider_summary(client: APIClient) -> Dict[str, Any]:
    """
    From GET /proxies/stats:
      - total proxies
      - good/bad counts per provider
    """
    data = await get_proxies_stats(client)

    providers: Dict[str, Dict[str, int]] = {}
    total_proxies = 0

    for proxy in data or []:
        total_proxies += 1
        statuses = proxy.get("provider_status") or []
        if not statuses:
            p_entry = providers.setdefault("unknown", {"total": 0, "good": 0, "bad": 0})
            p_entry["total"] += 1
            p_entry["bad"] += 1
            continue

        for st in statuses:
            prov = (st.get("provider") or "unknown").lower()
            good = bool(st.get("good"))
            p_entry = providers.setdefault(prov, {"total": 0, "good": 0, "bad": 0})
            p_entry["total"] += 1
            if good:
                p_entry["good"] += 1
            else:
                p_entry["bad"] += 1

    return {"providers": providers, "totals": {"proxies": total_proxies}}

@log_timing("proxies_bad_list")
async def proxies_bad_list(client: APIClient) -> List[Dict[str, Any]]:
    """
    From GET /proxies/stats:
      - list proxies where any provider_status.good == False
      - return [{id,name,url,provider,last_status,last_success}, ...]
    """
    data = await get_proxies_stats(client)

    bad: List[Dict[str, Any]] = []
    for proxy in data or []:
        pid = proxy.get("id")
        name = proxy.get("name")
        url = proxy.get("url")
        for st in (proxy.get("provider_status") or []):
            if not st.get("good"):
                bad.append({
                    "id": pid,
                    "name": name,
                    "url": url,
                    "provider": (st.get("provider") or "unknown").lower(),
                    "last_status": st.get("last_status"),
                    "last_success": st.get("last_success"),
                })

    return bad

# ---------------------------
# AREAS PROCESSORS
# ---------------------------
@log_timing("summarize_area_info")
def summarize_area_info(area: dict) -> dict:
    """
    Input: payload from GET /areas/{area_id}
    Output: compact summary for UI.
    """
    if not isinstance(area, dict):
        return {}

    def _route_len(x):
        r = (x or {}).get("route") if isinstance(x, dict) else None
        return len(r) if isinstance(r, list) else 0

    pokemon = area.get("pokemon_mode") or {}
    quest   = area.get("quest_mode") or {}
    fort    = area.get("fort_mode") or {}

    return {
        "name": area.get("name"),
        "enabled": bool(area.get("enabled")),
        "modes": {
            "pokemon": {
                "workers": int(pokemon.get("workers") or 0),
                "route_points": _route_len(pokemon),
                "enable_scout": bool(pokemon.get("enable_scout") or False),
                "invasion": bool(pokemon.get("invasion") or False),
            },
            "quest": {
                "workers": int(quest.get("workers") or 0),
                "route_points": _route_len(quest),
                "hours": list(quest.get("hours") or []),
                "max_login_queue": int(quest.get("max_login_queue") or 0),
            },
            "fort": {
                "workers": int(fort.get("workers") or 0),
                "route_points": _route_len(fort),
                "prio_raid": bool(fort.get("prio_raid") or False),
                "showcase": bool(fort.get("showcase") or False),
                "invasion": bool(fort.get("invasion") or False),
            }
        },
        "enable_quests": bool(area.get("enable_quests") or False),
        "geofence_points": len(area.get("geofence") or []),
        "id": area.get("id"),
    }
