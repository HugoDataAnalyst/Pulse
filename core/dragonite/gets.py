from typing import Any, Dict, List
from utils.http_api import APIClient

# -------- Status --------
async def get_status(client: APIClient) -> List[Dict[str, Any]]:
    """
    GET /status
    Returns list of areas with worker_managers/workers info.
    """
    return await client.get("/status")

# -------- Accounts --------
async def get_accounts_level_stats(client: APIClient) -> List[Dict[str, Any]]:
    """
    GET /accounts/level-stats
    Clean: keep 'level', 'total', and any non-zero/non-null keys.
    """
    raw = await client.get("/accounts/level-stats")
    cleaned: List[Dict[str, Any]] = []
    for row in raw or []:
        keep = {"level": row.get("level"), "total": row.get("total")}
        for k, v in row.items():
            if k in ("level", "total"):
                continue
            if v not in (0, 0.0, None):
                keep[k] = v
        cleaned.append(keep)
    return cleaned

async def get_account_by_name(client: APIClient, account_name: str) -> Dict[str, Any]:
    """
    GET /accounts/{account_name}
    """
    # API path shown as /accounts/account_name
    return await client.get(f"/accounts/{account_name}")

async def reload_accounts(client: APIClient) -> Dict[str, Any]:
    """
    GET /reload/accounts
    """
    return await client.get("/reload/accounts")

# -------- Proxies --------
async def get_proxies_stats(client: APIClient) -> List[Dict[str, Any]]:
    """
    GET /proxies/stats
    """
    return await client.get("/proxies/stats")

async def reload_proxies(client: APIClient) -> Dict[str, Any]:
    """
    GET /reload/proxy
    """
    return await client.get("/reload/proxy")

# -------- Quests control --------
async def quest_start_area(client: APIClient, area_id: int) -> Dict[str, Any]:
    return await client.get(f"/quest/{area_id}/start")

async def quest_stop_area(client: APIClient, area_id: int) -> Dict[str, Any]:
    return await client.get(f"/quest/{area_id}/stop")

async def quest_start_all(client: APIClient) -> Dict[str, Any]:
    return await client.get("/quest/all/start")

async def quest_stop_all(client: APIClient) -> Dict[str, Any]:
    return await client.get("/quest/all/stop")

async def quest_area_status(client: APIClient, area_id: int) -> Dict[str, Any]:
    return await client.get(f"/status/quest-area/{area_id}")

# -------- Routes / Recalculate --------
async def recalc_quest(client: APIClient, area_id: int) -> Dict[str, Any]:
    return await client.get(f"/recalculate/{area_id}/quest")

async def recalc_fort(client: APIClient, area_id: int) -> Dict[str, Any]:
    return await client.get(f"/recalculate/{area_id}/fort")

async def recalc_pokemon(client: APIClient, area_id: int) -> Dict[str, Any]:
    return await client.get(f"/recalculate/{area_id}/pokemon")

# --------- Areas Control --------
async def start_area(client: APIClient, area_id: int) -> Dict[str, Any]:
    return await client.get(f"/areas/{area_id}/enable")

async def stop_area(client: APIClient, area_id: int) -> Dict[str, Any]:
    return await client.get(f"/areas/{area_id}/disable")

async def info_area(client: APIClient, area_id: int) -> Dict[str, Any]:
    return await client.get(f"/areas/{area_id}")
