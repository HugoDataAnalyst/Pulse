from typing import Any, Dict
from loguru import logger
from utils.http_api import APIClient

async def delete_proxy(client: APIClient, proxy_id: int) -> Dict[str, Any]:
    """
    DELETE /proxies/{proxy_id}
    """
    res = await client.delete(f"/proxies/{proxy_id}")

    # Debug log
    logger.debug(f"[delete_proxy] Proxy ID: {proxy_id} | Response: {res}")

    return res
