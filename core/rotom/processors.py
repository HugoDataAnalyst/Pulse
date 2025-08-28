from __future__ import annotations
import re
from typing import Dict, List, Tuple, Any
from loguru import logger

from utils.http_api import APIClient
from core.rotom.gets import get_metrics_text, get_status, get_job_list, get_public_ip_list


# --- Prometheus text parsing -------------------------------------------------

_METRIC_RE_LABELED = re.compile(
    r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$'
)
_METRIC_RE_SIMPLE = re.compile(
    r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$'
)
_LABEL_PAIR_RE = re.compile(r'\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*"(.*?)"\s*')


def _parse_labels(s: str) -> Dict[str, str]:
    """
    Parse `key="value",key2="value2"` into a dict.
    Handles basic escaping of \" inside values.
    """
    out: Dict[str, str] = {}
    i = 0
    while i < len(s):
        m = _LABEL_PAIR_RE.match(s, i)
        if not m:
            break
        key, val = m.group(1), m.group(2).replace(r'\"', '"')
        out[key] = val
        i = m.end()
        if i < len(s) and s[i] == ",":
            i += 1
    return out


def _to_num(v: str) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def parse_prometheus_text(text: str) -> Dict[str, List[Tuple[Dict[str, str], float]]]:
    """
    Parse Prometheus exposition text into:
      { metric_name: [ (labels_dict, value_float), ... ] }
    Comments (# HELP / # TYPE / # …) are ignored.
    """
    series: Dict[str, List[Tuple[Dict[str, str], float]]] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        m = _METRIC_RE_LABELED.match(line)
        if m:
            name, labels_blob, val_s = m.groups()
            labels = _parse_labels(labels_blob)
            val = _to_num(val_s)
            series.setdefault(name, []).append((labels, val))
            continue

        m = _METRIC_RE_SIMPLE.match(line)
        if m:
            name, val_s = m.groups()
            val = _to_num(val_s)
            series.setdefault(name, []).append(({}, val))
            continue

        # Unparsed line (harmless); keep a debug breadcrumb
        logger.debug("[rotom:parse] skipped line: {}", line[:120])

    return series


# --- High-level processors ---------------------------------------------------

def _sum_metric(series: Dict[str, List[Tuple[Dict[str, str], float]]], name: str) -> float:
    return sum(v for _, v in series.get(name, []) or [])


def _index_by_origin(series: Dict[str, List[Tuple[Dict[str, str], float]]], metric: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for labels, val in series.get(metric, []) or []:
        origin = labels.get("origin", "")
        if not origin:
            continue
        out[origin] = out.get(origin, 0.0) + float(val)
    return out


async def rotom_overview(api: APIClient) -> Dict[str, Any]:
    """
    Pull /metrics and return a compact summary:
    {
      "devices": {"total": int, "alive": int},
      "workers": {
          "total": int, "active": int,
          "by_origin": [{"origin": str, "total": int, "active": int}, ...]
      }
    }
    """
    txt = await get_metrics_text(api)
    series = parse_prometheus_text(txt)

    # Devices
    dev_total = int(round(_sum_metric(series, "rotom_devices_total")))
    dev_alive = int(round(_sum_metric(series, "rotom_devices_alive")))

    # Workers (per-origin)
    total_by_origin  = _index_by_origin(series, "rotom_workers_total")
    active_by_origin = _index_by_origin(series, "rotom_workers_active")

    # Normalize into ints and aligned rows
    origins = sorted(set(total_by_origin.keys()) | set(active_by_origin.keys()))
    by_origin: List[Dict[str, Any]] = []
    for o in origins:
        t = int(round(total_by_origin.get(o, 0.0)))
        a = int(round(active_by_origin.get(o, 0.0)))
        by_origin.append({"origin": o, "total": t, "active": a})

    workers_total  = sum(r["total"] for r in by_origin)
    workers_active = sum(r["active"] for r in by_origin)

    out = {
        "devices": {"total": dev_total, "alive": dev_alive},
        "workers": {"total": workers_total, "active": workers_active, "by_origin": by_origin},
    }

    logger.debug(
        "[rotom:overview] devices T/A = {}/{} • workers T/A = {}/{} • origins={}",
        dev_total, dev_alive, workers_total, workers_active, len(by_origin)
    )
    return out

# ---------- /api/status (devices last activity) ----------

def _pick_latest_ts(dev: Dict[str, Any]) -> Tuple[int, str]:
    """
    Return (ts, source) where source in {"recv","sent"} based on the larger of
    dateLastMessageReceived / dateLastMessageSent. If both missing -> (0,"").
    """
    r = int(dev.get("dateLastMessageReceived") or 0)
    s = int(dev.get("dateLastMessageSent") or 0)
    if r >= s:
        return (r, "recv") if r > 0 else (0, "")
    return (s, "sent") if s > 0 else (0, "")

async def status_devices_last_seen(api) -> List[Dict[str, Any]]:
    """
    Pull /api/status and return a compact per-device list:
      [ { "deviceId": str, "lastTs": int, "source": "recv"|"sent" }, ... ]
    If both timestamps are 0/missing, lastTs = 0 and source = "".
    """
    data = await get_status(api)
    devices = data.get("devices") or []
    out: List[Dict[str, Any]] = []

    for d in devices:
        did = str(d.get("deviceId") or "").strip()
        if not did:
            continue
        ts, src = _pick_latest_ts(d)
        out.append({"deviceId": did, "lastTs": ts, "source": src})

    # Keep a stable order (by deviceId)
    out.sort(key=lambda x: x["deviceId"])
    logger.debug("[rotom:status] devices last-seen entries={}", len(out))
    return out

# ---------- /api/getPublicIp (device ids only) ----------

async def public_device_ids(api) -> List[str]:
    """
    Pull /api/getPublicIp and return a sorted list of deviceIds (strings).
    """
    rows = await get_public_ip_list(api)
    ids = sorted({str(r.get("deviceId") or "").strip() for r in rows if r.get("deviceId")})
    logger.debug("[rotom:public] deviceIds={}", len(ids))
    return ids

# ---------- /api/job/list (jobs catalog) ----------

async def jobs_catalog(api) -> List[Dict[str, Any]]:
    """
    Pull /api/job/list and normalize into a list:
      [ { "id": str, "description": str, "exec": str }, ... ] sorted by id.
    """
    raw = await get_job_list(api)
    items: List[Dict[str, Any]] = []
    for jid, spec in (raw or {}).items():
        if not jid:
            continue
        spec = spec or {}
        items.append({
            "id": str(spec.get("id") or jid),
            "description": str(spec.get("description") or "").strip(),
            "exec": str(spec.get("exec") or "").strip(),
        })
    items.sort(key=lambda x: x["id"])
    logger.debug("[rotom:jobs] total={}", len(items))
    return items
