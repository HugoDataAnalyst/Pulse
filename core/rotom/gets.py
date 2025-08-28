from __future__ import annotations
from typing import Any, Dict, List, Optional
from loguru import logger
from utils.http_api import APIClient


async def get_status(api: APIClient) -> Dict[str, Any]:
    """GET /api/status"""
    try:
        res = await api.get_json("/api/status")
        #logger.debug(f"[rotom] get_status -> {res!r}")
        return res or {}
    except Exception as e:
        logger.exception(f"[rotom] get_status failed: {e}")
        raise


async def get_job_list(api: APIClient) -> Dict[str, Dict[str, Any]]:
    """GET /api/job/list"""
    try:
        res = await api.get("/api/job/list")
        logger.debug("[rotom:gets] /api/job/list ok ({} jobs)", len(res or {}))
        return res or {}
    except Exception as e:
        logger.exception(f"[rotom] get_job_list failed: {e}")
        raise


async def job_status_all(api: APIClient) -> List[Dict[str, Any]]:
    """
    GET /api/job/status
    Return the status of all jobs here.
    """
    try:
        res = await api.get_json("/api/job/status")
        logger.debug(f"[rotom] job_status_all -> {len(res or [])} entries")
        return list(res or [])
    except Exception as e:
        logger.exception(f"[rotom] job_status_all failed: {e}")
        raise


async def get_public_ip_list(api: APIClient) -> List[Dict[str, str]]:
    """
    GET /api/getPublicIp
    List of all deviceIds.
    """
    try:
        res = await api.get("/api/getPublicIp")
        logger.debug("[rotom:gets] /api/getPublicIp ok ({} entries)", len(res or []))
        return res or []
    except Exception as e:
        logger.exception(f"[rotom] get_public_ip_list failed: {e}")
        raise


async def get_metrics_text(api: APIClient) -> str:
    """GET /metrics — returns raw Prometheus text."""
    try:
        txt = await api.get_text("/metrics")
        logger.debug(f"[rotom] get_metrics_text -> {len(txt or '')} chars")
        return txt or ""
    except Exception as e:
        logger.exception(f"[rotom] get_metrics_text failed: {e}")
        raise
