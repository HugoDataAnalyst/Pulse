from __future__ import annotations
from typing import Optional, List, Sequence, Union, Dict, Tuple
from enum import Enum
from loguru import logger
from utils.db import fetch_all_as, fetch_one_as, exec_sql, transaction
from utils.timing import log_timing
from core.dragonite.sql.init import DB_KEY
from core.dragonite.sql.schema import Area, Account
import config as AppConfig

# ---------- Strict interval enum ----------
class IntervalUnit(str, Enum):
    MINUTE = "MINUTE"
    HOUR   = "HOUR"
    DAY    = "DAY"
    MONTH  = "MONTH"

_VALID_PROVIDERS = {"nk", "ptc"}

# ---------- Helpers ----------
_FLAG_RESET_PLAN: dict[str, Dict[str, object]] = {
    "banned":      {"banned": 0, "last_banned": None},
    "disabled":    {"disabled": 0, "last_disabled": None},
    "invalid":     {"invalid": 0},
    "suspended":   {"suspended": 0, "last_suspended": None},
    "warn":        {"warn": 0, "warn_expiration": 0},
    "auth_banned": {"auth_banned": 0},
}


def _interval_clause(value: int, unit: Union[str, IntervalUnit]) -> str:
    # value must be an int
    if not isinstance(value, int):
        raise ValueError("Wrong format for values: interval_value must be an integer.")
    if value < 0:
        raise ValueError("interval_value must be >= 0.")

    # unit must be a valid IntervalUnit
    u = unit.value if isinstance(unit, IntervalUnit) else str(unit).upper()
    try:
        u = IntervalUnit(u).value  # validate & normalize
    except Exception:
        raise ValueError("Wrong format for values: interval_unit must be one of "
                         f"{', '.join([e.value for e in IntervalUnit])}.")
    return f"NOW() - INTERVAL {value} {u}"

def _ensure_provider(p: str) -> str:
    p = p.lower()
    if p not in _VALID_PROVIDERS:
        raise ValueError(f"Invalid provider: {p} (allowed: {', '.join(sorted(_VALID_PROVIDERS))})")
    return p

# ---------- Areas ----------
@log_timing("update_area_quest_hours")
async def update_area_quest_hours(area_id: int, hours: Sequence[int]) -> int:
    """
    Update quest_mode_hours for an area (comma-separated list).
    Strictly enforces integers in [0, 23]; any invalid entry raises ValueError.
    """
    if not isinstance(area_id, int) or area_id <= 0:
        raise ValueError("Wrong format for values: area_id must be a positive integer.")

    # Validate every hour strictly
    validated: list[int] = []
    for h in hours:
        if not isinstance(h, int):
            raise ValueError("Wrong format for values: all hours must be integers (0–23).")
        if h < 0 or h > 23:
            raise ValueError("Wrong format for values: hours must be between 0 and 23.")
        validated.append(h)

    text_val = ",".join(str(h) for h in validated)
    sql = "UPDATE area SET quest_mode_hours=%s WHERE id=%s"
    return await exec_sql(DB_KEY, sql, (text_val, area_id))

# ---------- Stats Accounts ----------
@log_timing("count_sessions_by_end_reason")
async def count_sessions_by_end_reason(interval_value: int, interval_unit: Union[str, IntervalUnit]) -> list[dict]:
    """
    SELECT COUNT(*) AS total, reason_for_session_end
    FROM stats_accounts
    WHERE session_end >= NOW() - INTERVAL <interval_value> <interval_unit>
    GROUP BY reason_for_session_end

    Enforces `interval_value` as int and `interval_unit` as IntervalUnit.
    """
    clause = _interval_clause(interval_value, interval_unit)
    sql = f"""
        SELECT COUNT(*) AS total, reason_for_session_end
        FROM stats_accounts
        WHERE session_end >= {clause}
        GROUP BY reason_for_session_end
    """
    return await fetch_all_as(DB_KEY, dict, sql)

# ---------- Accounts ----------
def _plan_updates_from_account_info(acc: dict) -> Dict[str, object]:
    updates: Dict[str, object] = {}
    for flag, reset_map in _FLAG_RESET_PLAN.items():
        val = acc.get(flag)
        try:
            needs_reset = bool(int(val)) if isinstance(val, (int, str)) else bool(val)
        except Exception:
            needs_reset = bool(val)
        if needs_reset:
            updates.update(reset_map)
    return updates

@log_timing("delete_account")
async def delete_account(username: str) -> int:
    sql = "DELETE FROM `account` WHERE `username`=%s LIMIT 1"
    return await exec_sql(DB_KEY, sql, (username,))

@log_timing("reactivate_account_from_info")
async def reactivate_account_from_info(username: str, acc_info: dict) -> int:
    updates = _plan_updates_from_account_info(acc_info)
    if not updates:
        logger.debug(f"[reactivate_account_from_info] '{username}': nothing to reset.")
        return 0
    cols = sorted(updates.keys())
    set_clause = ", ".join(f"`{c}`=%s" for c in cols)
    sql = f"UPDATE `account` SET {set_clause} WHERE `username`=%s LIMIT 1"
    params = tuple(updates[c] for c in cols) + (username,)
    logger.debug(
        f"[reactivate_account_from_info] SQL: {sql} | params(no-username)={tuple(updates[c] for c in cols)}"
    )
    return await exec_sql(DB_KEY, sql, params)

@log_timing("reactivate_accounts")
async def reactivate_accounts(usernames: Optional[List[str]] = None) -> int:
    """
    Admin tool: reset ALL standard flags for the provided usernames.
    If usernames is None/empty, affect 0 rows (explicit list only for safety).
    """
    if not usernames:
        return 0
    # Merge all resets into a single map (full reset)
    full_reset: Dict[str, object] = {}
    for m in _FLAG_RESET_PLAN.values():
        full_reset.update(m)
    cols = sorted(full_reset.keys())
    set_clause = ", ".join(f"`{c}`=%s" for c in cols)
    placeholders = ",".join(["%s"] * len(usernames))
    sql = f"UPDATE `account` SET {set_clause} WHERE `username` IN ({placeholders})"
    params = tuple(full_reset[c] for c in cols) + tuple(usernames)
    return await exec_sql(DB_KEY, sql, params)

@log_timing("reset_banned_accounts")
async def reset_banned_accounts(usernames: Optional[List[str]] = None) -> int:
    if usernames:
        placeholders = ",".join(["%s"] * len(usernames))
        sql = f"UPDATE account SET last_banned=NULL, banned=0 WHERE username IN ({placeholders})"
        return await exec_sql(DB_KEY, sql, tuple(usernames))
    sql = "UPDATE account SET last_banned=NULL, banned=0"
    return await exec_sql(DB_KEY, sql)

@log_timing("banned_accounts")
async def banned_accounts(provider: str, interval_value: int, interval_unit: Union[str, IntervalUnit]) -> list[Account]:
    p = _ensure_provider(provider)
    clause = _interval_clause(interval_value, interval_unit)
    sql = f"""
        SELECT * FROM account
        WHERE provider=%s
          AND banned != 0
          AND FROM_UNIXTIME(last_banned) >= {clause}
    """
    return await fetch_all_as(DB_KEY, Account, sql, (p,))

@log_timing("banned_usernames")
async def banned_usernames(provider: str, interval_value: int, interval_unit: Union[str, IntervalUnit]) -> list[str]:
    p = _ensure_provider(provider)
    clause = _interval_clause(interval_value, interval_unit)
    sql = f"""
        SELECT username
        FROM account
        WHERE provider=%s
          AND banned != 0
          AND FROM_UNIXTIME(last_banned) >= {clause}
        ORDER BY username ASC
    """
    rows = await fetch_all_as(DB_KEY, dict, sql, (p,))
    return [str(r["username"]) for r in rows if r.get("username")]

# ---------- Session Queries ----------
@log_timing("err_limit_reached")
async def err_limit_reached(interval_value: int, interval_unit: Union[str, IntervalUnit]) -> list[dict]:
    clause = _interval_clause(interval_value, interval_unit)
    sql = f"""
        SELECT
            username,
            reason_for_session_end,
            CONCAT(
                FLOOR(TIMESTAMPDIFF(SECOND, session_start, session_end) / 3600), ' hours, ',
                FLOOR(MOD(TIMESTAMPDIFF(SECOND, session_start, session_end), 3600) / 60), ' minutes, ',
                MOD(TIMESTAMPDIFF(SECOND, session_start, session_end), 60), ' seconds'
            ) AS session_duration,
            COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(counts, '$.METHOD_ENCOUNTER')) AS UNSIGNED), 0) AS METHOD_ENCOUNTER,
            COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(counts, '$.METHOD_GET_MAP_OBJECTS')) AS UNSIGNED), 0) AS METHOD_GET_MAP_OBJECTS
        FROM stats_accounts
        WHERE reason_for_session_end = 'ErrLimitReached'
          AND session_end >= {clause}
          AND (
              COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(counts, '$.METHOD_ENCOUNTER')) AS UNSIGNED), 0) >= %s
              OR COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(counts, '$.METHOD_GET_MAP_OBJECTS')) AS UNSIGNED), 0) >= %s
          )
    """
    rows = await fetch_all_as(
        DB_KEY, dict, sql,
        (AppConfig.DRAGONITE_ENCOUNTER_LIMIT, AppConfig.DRAGONITE_GMO_LIMIT)
    )
    logger.debug(f"[sessions] err_limit_reached returned {len(rows)} rows")
    if rows:
        from pprint import pformat
        logger.debug("[sessions] Sample err_limit_reached row:\n{}", pformat(rows[0]))
    return rows


@log_timing("err_disabled")
async def err_disabled(interval_value: int, interval_unit: Union[str, IntervalUnit]) -> list[dict]:
    clause = _interval_clause(interval_value, interval_unit)
    sql = f"""
        SELECT
            username,
            reason_for_session_end,
            CONCAT(
                FLOOR(TIMESTAMPDIFF(SECOND, session_start, session_end) / 3600), ' hours, ',
                FLOOR(MOD(TIMESTAMPDIFF(SECOND, session_start, session_end), 3600) / 60), ' minutes, ',
                MOD(TIMESTAMPDIFF(SECOND, session_start, session_end), 60), ' seconds'
            ) AS session_duration,
            COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(counts, '$.METHOD_ENCOUNTER')) AS UNSIGNED), 0) AS METHOD_ENCOUNTER,
            COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(counts, '$.METHOD_GET_MAP_OBJECTS')) AS UNSIGNED), 0) AS METHOD_GET_MAP_OBJECTS
        FROM stats_accounts
        WHERE reason_for_session_end = 'ErrDisabled'
          AND session_end >= {clause}
          AND (
              COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(counts, '$.METHOD_ENCOUNTER')) AS UNSIGNED), 0) < %s
              AND COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(counts, '$.METHOD_GET_MAP_OBJECTS')) AS UNSIGNED), 0) < %s
          )
    """
    rows = await fetch_all_as(
        DB_KEY, dict, sql,
        (AppConfig.DRAGONITE_ENCOUNTER_LIMIT, AppConfig.DRAGONITE_GMO_LIMIT)
    )
    logger.debug(f"[sessions] err_disabled returned {len(rows)} rows")
    if rows:
        from pprint import pformat
        logger.debug("[sessions] Sample err_disabled row:\n{}", pformat(rows[0]))
    return rows

