from __future__ import annotations
from typing import Any, Dict, Optional
from enum import Enum
from loguru import logger
from utils.http_api import APIClient


class DeviceAction(str, Enum):
    REBOOT     = "reboot"
    RESTART    = "restart"
    GET_LOGCAT = "getLogcat"
    DELETE     = "delete"


async def device_action(api: APIClient, device_id: str | int, action: DeviceAction) -> Dict[str, Any]:
    """
    POST /api/device/{deviceId}/action/{action}
    Action = one of: reboot, restart, getLogcat, delete
    """
    path = f"/api/device/{device_id}/action/{action.value}"
    logger.debug(f"[rotom] device_action path={path}")
    try:
        res = await api.post_json(path, json=None)
        logger.debug(f"[rotom] device_action -> {res!r}")
        return res or {}
    except Exception as e:
        logger.exception(f"[rotom] device_action failed (device={device_id}, action={action}): {e}")
        raise


async def execute_job(api: APIClient, job_id: str | int, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    POST /api/job/execute/{jobId}
    Some Rotom installs accept an optional JSON payload; pass `payload` if needed.
    """
    path = f"/api/job/execute/{job_id}"
    logger.debug(f"[rotom] execute_job path={path} payload_keys={list(payload.keys()) if payload else []}")
    try:
        res = await api.post_json(path, json=payload or {})
        logger.debug(f"[rotom] execute_job -> {res!r}")
        return res or {}
    except Exception as e:
        logger.exception(f"[rotom] execute_job failed (job_id={job_id}): {e}")
        raise
