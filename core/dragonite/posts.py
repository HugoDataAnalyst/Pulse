from typing import Any, Dict
from loguru import logger
from utils.http_api import APIClient

# -------- Proxies --------
async def add_proxy(client: APIClient, *, proxy_id: int, name: str, url: str) -> Dict[str, Any]:
    """
    POST /proxies/
    Body:
    {
      "id": 0,
      "name": "string",
      "url": "http://example.com",
      "enabled": true
    }
    """
    payload = {
        "id": proxy_id,
        "name": name,
        "url": url,
        "enabled": True,
    }
    res = await client.post("/proxies/", json=payload)

    # Debug log
    #logger.debug(f"[add_proxy] Sent: {payload} | Response: {res}")
    logger.debug(f"[add_proxy] Proxy ID: {proxy_id} | Response: {res}")

    return res
