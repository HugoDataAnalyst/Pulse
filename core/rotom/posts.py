from __future__ import annotations
from typing import Any, Dict, Optional
from enum import Enum
from loguru import logger
from utils.http_api import APIClient
import json

class DeviceAction(str, Enum):
    REBOOT     = "reboot"
    RESTART    = "restart"
    GET_LOGCAT = "getLogcat"
    DELETE     = "delete"

def _filename_from_cd(cd: str | None, fallback: str) -> str:
    """
    Extract filename from Content-Disposition; fallback if missing.
    """
    if not cd:
        return fallback
    # e.g. attachment; filename="logcat-<origin>.zip"
    for part in cd.split(";"):
        part = part.strip()
        if part.lower().startswith("filename="):
            val = part.split("=", 1)[1].strip().strip('"')
            return val or fallback
    return fallback

async def device_action(api: APIClient, device_id: str | int, action: DeviceAction) -> Dict[str, Any]:
    """
    POST /api/device/{deviceId}/action/{action}
    - reboot/restart/delete -> JSON response
    - getLogcat            -> binary response (zip)
    Returns:
      - For getLogcat: {"file_bytes": bytes, "filename": str, "content_type": str, "status": int}
      - Others:        {"ok": True, "raw": <json>}
    """
    path = f"/api/device/{device_id}/action/{action.value}"
    logger.debug(f"[rotom] device_action path={path}")

    try:
        if action == DeviceAction.GET_LOGCAT:
            body, headers, status = await api.post_bytes(path)
            ct = headers.get("Content-Type", "application/octet-stream")
            cd = headers.get("Content-Disposition")

            if ct.startswith("application/json"):
                try:

                    err = json.loads(body.decode("utf-8", errors="ignore"))
                    logger.warning(f"[rotom] getLogcat returned JSON: {err!r}")
                    return {"ok": False, "json": err, "status": status}
                except Exception:
                    pass
            fname = _filename_from_cd(cd, f"logcat-{device_id}.zip")
            logger.debug(f"[rotom] getLogcat -> {len(body)} bytes, ct={ct}, fn={fname}, status={status}")
            return {
                "file_bytes": body,
                "filename": fname,
                "content_type": ct,
                "status": status,
            }

        res = await api.post_json(path, json={})
        logger.debug(f"[rotom] device_action -> {res!r}")
        return {"ok": True, "raw": res or {}}

    except Exception as e:
        logger.exception(f"[rotom] device_action failed (device={device_id}, action={action}): {e}")
        raise


async def execute_job(api: APIClient, job_id: str | int, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    POST /api/job/execute/{jobId}
    Rotom accept an optional JSON payload; pass `payload` if needed.
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
