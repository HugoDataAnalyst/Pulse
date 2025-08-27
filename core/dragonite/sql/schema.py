from __future__ import annotations
from typing import Optional, Any, List, Dict
from datetime import datetime
import json
from pydantic import BaseModel, Field, ConfigDict, field_validator

# ---------- Helpers ----------
def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    try:
        return bool(int(v))
    except Exception:
        return bool(v)

def _json_or_none(v: Any) -> Optional[Any]:
    if v is None or v == "":
        return None
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return None

def _as_dt(v: Any) -> Optional[datetime]:
    if v in (None, 0, "0", "", "null"):
        return None
    if isinstance(v, datetime):
        return v
    # table stores some unix timestamps as INT
    try:
        return datetime.utcfromtimestamp(int(v))
    except Exception:
        return None

# ---------- Tables ----------

class Account(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    password: str
    email: Optional[str] = None
    provider: str = "ptc"
    level: int = 0

    warn: bool = Field(default=False)
    warn_expiration: Optional[int] = None

    suspended: bool = Field(default=False)
    banned: bool = Field(default=False)
    invalid: bool = Field(default=False)
    auth_banned: int = 0

    ar_ban_state: Optional[int] = None
    ar_ban_last_checked: Optional[int] = None

    last_selected: Optional[int] = None
    last_released: Optional[int] = None
    last_disabled: Optional[int] = None
    last_banned: Optional[int] = None
    last_suspended: Optional[int] = None
    consecutive_disable_count: int = 0

    refresh_token: str = ""
    last_refreshed: Optional[int] = None
    next_available_time: Optional[int] = None

    # convenience read-only datetime views (computed)
    last_selected_dt: Optional[datetime] = None
    last_released_dt: Optional[datetime] = None
    last_disabled_dt: Optional[datetime] = None
    last_banned_dt: Optional[datetime] = None
    last_suspended_dt: Optional[datetime] = None
    last_refreshed_dt: Optional[datetime] = None
    next_available_dt: Optional[datetime] = None

    @field_validator("warn", "suspended", "banned", "invalid", mode="before")
    @classmethod
    def _boolflags(cls, v): return _as_bool(v)

    @field_validator(
        "last_selected_dt", "last_released_dt", "last_disabled_dt",
        "last_banned_dt", "last_suspended_dt", "last_refreshed_dt",
        "next_available_dt", mode="before"
    )
    @classmethod
    def _compute_datetimes(cls, v, info):
        # map corresponding *_int field if present in data
        data = info.data
        name = info.field_name
        mapping = {
            "last_selected_dt": "last_selected",
            "last_released_dt": "last_released",
            "last_disabled_dt": "last_disabled",
            "last_banned_dt": "last_banned",
            "last_suspended_dt": "last_suspended",
            "last_refreshed_dt": "last_refreshed",
            "next_available_dt": "next_available_time",
        }
        src = mapping.get(name)
        if src is None:
            return v
        return _as_dt(data.get(src))

class Area(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    enabled: bool = False

    # pokemon mode
    pokemon_mode_workers: int = 0
    pokemon_mode_route: Optional[Any] = None
    pokemon_mode_invasion: bool = True

    # fort mode
    fort_mode_workers: int = 0
    fort_mode_prio_raid: bool = False
    fort_mode_showcase: bool = False
    fort_mode_invasion: bool = False
    fort_mode_full_route: Optional[Any] = None
    fort_mode_route: Optional[Any] = None

    # quest mode
    quest_mode_workers: int = 0
    quest_mode_hours: Optional[Any] = None
    quest_mode_max_login_queue: Optional[int] = None
    quest_mode_route: Optional[Any] = None

    # misc
    geofence: Optional[Any] = None
    enable_quests: bool = False
    enable_scout: bool = False

    @field_validator(
        "enabled", "pokemon_mode_invasion", "fort_mode_prio_raid",
        "fort_mode_showcase", "fort_mode_invasion", "enable_quests",
        "enable_scout", mode="before"
    )
    @classmethod
    def _bools(cls, v): return _as_bool(v)

    @field_validator(
        "pokemon_mode_route", "fort_mode_full_route", "fort_mode_route",
        "quest_mode_route", "geofence", "quest_mode_hours", mode="before"
    )
    @classmethod
    def _parse_json_fields(cls, v): return _json_or_none(v)

class Proxy(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: Optional[str] = None
    url: str
    enabled: bool = True

    @field_validator("enabled", mode="before")
    @classmethod
    def _bool_enabled(cls, v): return _as_bool(v)

class QuestCheck(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    area_id: int
    lat: float
    lon: float
    pokestops: str  # JSON text; parse on demand

class InvasionMode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: Optional[str] = None
    workers: int = 0

class LevelMode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workers: int = 0
    route: Optional[Any] = None
    name: Optional[str] = None

    @field_validator("route", mode="before")
    @classmethod
    def _parse_route(cls, v): return _json_or_none(v)

class ScoutMode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: Optional[str] = None
    workers: int = 0

class StatsAccounts(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    mode: str
    worker_name: str
    device_id: str
    previous_release: datetime
    session_start: datetime
    session_end: datetime
    duration_ms: int
    reason_for_session_end: str
    used_refresh_token: bool = False
    counts: str
    selection_start: Optional[datetime] = None
    selection_end: Optional[datetime] = None
    released: Optional[datetime] = None
    auth_queued: Optional[datetime] = None
    auth_success: Optional[datetime] = None
    rotom_start: Optional[datetime] = None
    login_start: Optional[datetime] = None
    worker_start: Optional[datetime] = None
    mitm: str = ""

    @field_validator("used_refresh_token", mode="before")
    @classmethod
    def _bool_used(cls, v): return _as_bool(v)

class StatsWorkers(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    datetime: datetime
    drago_worker: str
    mode: str
    api_worker: Optional[str] = None
    loc_avg: Optional[float] = None
    loc_count: Optional[int] = None
    loc_success: Optional[int] = None
    mons_seen: Optional[int] = None
    mons_enc: Optional[int] = None
    stops: Optional[int] = None
    quests: Optional[int] = None
    distance: float = 0.0
    retries: int = 0
    timeElapsed: float = 0.0
    locationDelay: int = 0
    gmos: int = 0
    gmoInitialSuccess: int = 0
    gmo0fail: int = 0
    gmo1fail: int = 0
    gmo2fail: int = 0
    gmo3fail: int = 0
    gmo4fail: int = 0
    gmo5fail: int = 0
    gmo6fail: int = 0
    gmo7fail: int = 0
    gmo8fail: int = 0
    gmoNoCell: int = 0
    gmoGivingUp: int = 0
    gmoDelay: int = 0

class SchemaMigration(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    dirty: bool

    @field_validator("dirty", mode="before")
    @classmethod
    def _bool_dirty(cls, v): return _as_bool(v)
