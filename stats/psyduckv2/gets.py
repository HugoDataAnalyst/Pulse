from typing import Any, Dict, List, Optional
from utils.http_api import APIClient

# Small helper to drop None values so we don't send empty params
def _params(**kwargs) -> Dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}

# ----------------------- Cached: Pokestops / Geofences -----------------------

async def get_cached_pokestops(
    client: APIClient,
    *,
    area: Optional[str] = "global",
    response_format: str = "json",
) -> Any:
    """GET /api/redis/get_cached_pokestops"""
    return await client.get(
        "/api/redis/get_cached_pokestops",
        **_params(area=area, response_format=response_format),
    )

async def get_cached_geofences(
    client: APIClient,
    *,
    response_format: str = "json",
) -> Any:
    """GET /api/redis/get_cached_geofences"""
    return await client.get(
        "/api/redis/get_cached_geofences",
        **_params(response_format=response_format),
    )

# ----------------------------- Redis: Counter Series --------------------------

async def get_pokemon_counterseries(
    client: APIClient,
    *,
    counter_type: str,
    interval: str,
    start_time: str,
    end_time: str,
    mode: str = "sum",
    response_format: str = "json",
    area: str = "global",
    metric: str = "all",
    pokemon_id: str = "all",  # only for totals
    form: str = "all",        # only for totals
) -> Any:
    """GET /api/redis/get_pokemon_counterseries"""
    return await client.get(
        "/api/redis/get_pokemon_counterseries",
        **_params(
            counter_type=counter_type,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            mode=mode,
            response_format=response_format,
            area=area,
            metric=metric,
            pokemon_id=pokemon_id,
            form=form,
        ),
    )

async def get_raids_counterseries(
    client: APIClient,
    *,
    interval: str,
    start_time: str,
    end_time: str,
    counter_type: str = "totals",
    mode: str = "sum",
    response_format: str = "json",
    area: str = "global",
    raid_pokemon: str = "all",
    raid_form: str = "all",
    raid_level: str = "all",
    raid_costume: str = "all",
    raid_is_exclusive: str = "all",
    raid_ex_eligible: str = "all",
) -> Any:
    """GET /api/redis/get_raids_counterseries"""
    return await client.get(
        "/api/redis/get_raids_counterseries",
        **_params(
            counter_type=counter_type,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            mode=mode,
            response_format=response_format,
            area=area,
            raid_pokemon=raid_pokemon,
            raid_form=raid_form,
            raid_level=raid_level,
            raid_costume=raid_costume,
            raid_is_exclusive=raid_is_exclusive,
            raid_ex_eligible=raid_ex_eligible,
        ),
    )

async def get_invasions_counterseries(
    client: APIClient,
    *,
    interval: str,
    start_time: str,
    end_time: str,
    counter_type: str = "totals",
    mode: str = "sum",
    response_format: str = "json",
    area: str = "global",
    display_type: str = "all",
    character: str = "all",
    grunt: str = "all",
    confirmed: str = "all",
) -> Any:
    """GET /api/redis/get_invasions_counterseries"""
    return await client.get(
        "/api/redis/get_invasions_counterseries",
        **_params(
            counter_type=counter_type,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            mode=mode,
            response_format=response_format,
            area=area,
            display_type=display_type,
            character=character,
            grunt=grunt,
            confirmed=confirmed,
        ),
    )

async def get_quest_counterseries(
    client: APIClient,
    *,
    interval: str,
    start_time: str,
    end_time: str,
    counter_type: str = "totals",
    mode: str = "sum",
    response_format: str = "json",
    area: str = "global",
    with_ar: str = "all",
    ar_type: str = "all",
    reward_ar_type: str = "all",
    reward_ar_item_id: str = "all",
    reward_ar_item_amount: str = "all",
    reward_ar_poke_id: str = "all",
    reward_ar_poke_form: str = "all",
    normal_type: str = "all",
    reward_normal_type: str = "all",
    reward_normal_item_id: str = "all",
    reward_normal_item_amount: str = "all",
    reward_normal_poke_id: str = "all",
    reward_normal_poke_form: str = "all",
) -> Any:
    """GET /api/redis/get_quest_counterseries"""
    return await client.get(
        "/api/redis/get_quest_counterseries",
        **_params(
            counter_type=counter_type,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            mode=mode,
            response_format=response_format,
            area=area,
            with_ar=with_ar,
            ar_type=ar_type,
            reward_ar_type=reward_ar_type,
            reward_ar_item_id=reward_ar_item_id,
            reward_ar_item_amount=reward_ar_item_amount,
            reward_ar_poke_id=reward_ar_poke_id,
            reward_ar_poke_form=reward_ar_poke_form,
            normal_type=normal_type,
            reward_normal_type=reward_normal_type,
            reward_normal_item_id=reward_normal_item_id,
            reward_normal_item_amount=reward_normal_item_amount,
            reward_normal_poke_id=reward_normal_poke_id,
            reward_normal_poke_form=reward_normal_poke_form,
        ),
    )

# ------------------------------- Redis: TimeSeries ----------------------------

async def get_pokemon_timeseries(
    client: APIClient,
    *,
    start_time: str,
    end_time: str,
    mode: str = "sum",
    response_format: str = "json",
    area: str = "global",
    pokemon_id: str = "all",
    form: str = "all",
) -> Any:
    """GET /api/redis/get_pokemon_timeseries"""
    return await client.get(
        "/api/redis/get_pokemon_timeseries",
        **_params(
            start_time=start_time,
            end_time=end_time,
            mode=mode,
            response_format=response_format,
            area=area,
            pokemon_id=pokemon_id,
            form=form,
        ),
    )

async def get_pokemon_tth_timeseries(
    client: APIClient,
    *,
    start_time: str,
    end_time: str,
    mode: str = "sum",
    response_format: str = "json",
    area: str = "global",
    tth_bucket: str = "all",
) -> Any:
    """GET /api/redis/get_pokemon_tth_timeseries"""
    return await client.get(
        "/api/redis/get_pokemon_tth_timeseries",
        **_params(
            start_time=start_time,
            end_time=end_time,
            mode=mode,
            response_format=response_format,
            area=area,
            tth_bucket=tth_bucket,
        ),
    )

async def get_raid_timeseries(
    client: APIClient,
    *,
    start_time: str,
    end_time: str,
    mode: str = "sum",
    response_format: str = "json",
    area: str = "global",
    raid_pokemon: str = "all",
    raid_form: str = "all",
    raid_level: str = "all",
) -> Any:
    """GET /api/redis/get_raid_timeseries"""
    return await client.get(
        "/api/redis/get_raid_timeseries",
        **_params(
            start_time=start_time,
            end_time=end_time,
            mode=mode,
            response_format=response_format,
            area=area,
            raid_pokemon=raid_pokemon,
            raid_form=raid_form,
            raid_level=raid_level,
        ),
    )

async def get_invasion_timeseries(
    client: APIClient,
    *,
    start_time: str,
    end_time: str,
    mode: str = "sum",
    response_format: str = "json",
    area: str = "global",
    display: str = "all",
    grunt: str = "all",
    confirmed: str = "all",
) -> Any:
    """GET /api/redis/get_invasion_timeseries"""
    return await client.get(
        "/api/redis/get_invasion_timeseries",
        **_params(
            start_time=start_time,
            end_time=end_time,
            mode=mode,
            response_format=response_format,
            area=area,
            display=display,
            grunt=grunt,
            confirmed=confirmed,
        ),
    )

async def get_quest_timeseries(
    client: APIClient,
    *,
    start_time: str,
    end_time: str,
    mode: str = "sum",
    response_format: str = "json",
    area: str = "global",
    quest_mode: str = "all",
    quest_type: str = "all",
) -> Any:
    """GET /api/redis/get_quest_timeseries"""
    return await client.get(
        "/api/redis/get_quest_timeseries",
        **_params(
            start_time=start_time,
            end_time=end_time,
            mode=mode,
            response_format=response_format,
            area=area,
            quest_mode=quest_mode,
            quest_type=quest_type,
        ),
    )

# ----------------------------------- SQL: Data --------------------------------

async def get_pokemon_heatmap_data(
    client: APIClient,
    *,
    start_time: str,   # e.g. "202503"
    end_time: str,     # e.g. "202504"
    response_format: str = "json",
    area: str = "global",
    pokemon_id: str = "all",
    form: str = "all",
    iv_bucket: str = "all",
    limit: Optional[int] = 0,
) -> Any:
    """GET /api/sql/get_pokemon_heatmap_data"""
    return await client.get(
        "/api/sql/get_pokemon_heatmap_data",
        **_params(
            start_time=start_time,
            end_time=end_time,
            response_format=response_format,
            area=area,
            pokemon_id=pokemon_id,
            form=form,
            iv_bucket=iv_bucket,
            limit=limit,
        ),
    )

async def get_shiny_rate_data(
    client: APIClient,
    *,
    start_time: str,   # e.g. "202503"
    end_time: str,     # e.g. "202504"
    response_format: str = "json",
    area: str = "global",
    username: str = "all",
    pokemon_id: str = "all",
    form: str = "all",
    shiny: str = "all",
    limit: Optional[int] = 0,
) -> Any:
    """GET /api/sql/get_shiny_rate_data"""
    return await client.get(
        "/api/sql/get_shiny_rate_data",
        **_params(
            start_time=start_time,
            end_time=end_time,
            response_format=response_format,
            area=area,
            username=username,
            pokemon_id=pokemon_id,
            form=form,
            shiny=shiny,
            limit=limit,
        ),
    )

async def get_raid_data(
    client: APIClient,
    *,
    start_time: str,   # e.g. "202503"
    end_time: str,     # e.g. "202504"
    response_format: str = "json",
    area: str = "global",
    gym_id: str = "all",
    raid_pokemon: str = "all",
    raid_level: str = "all",
    raid_form: str = "all",
    raid_team: str = "all",
    raid_costume: str = "all",
    raid_is_exclusive: str = "all",
    raid_ex_raid_eligible: str = "all",
    limit: Optional[int] = 0,
) -> Any:
    """GET /api/sql/get_raid_data"""
    return await client.get(
        "/api/sql/get_raid_data",
        **_params(
            start_time=start_time,
            end_time=end_time,
            response_format=response_format,
            area=area,
            gym_id=gym_id,
            raid_pokemon=raid_pokemon,
            raid_level=raid_level,
            raid_form=raid_form,
            raid_team=raid_team,
            raid_costume=raid_costume,
            raid_is_exclusive=raid_is_exclusive,
            raid_ex_raid_eligible=raid_ex_raid_eligible,
            limit=limit,
        ),
    )

async def get_invasion_data(
    client: APIClient,
    *,
    start_time: str,   # e.g. "202503"
    end_time: str,     # e.g. "202504"
    response_format: str = "json",
    area: str = "global",
    pokestop_id: str = "all",
    display_type: str = "all",
    character: str = "all",
    grunt: str = "all",
    confirmed: str = "all",
    limit: Optional[int] = 0,
) -> Any:
    """GET /api/sql/get_invasion_data"""
    return await client.get(
        "/api/sql/get_invasion_data",
        **_params(
            start_time=start_time,
            end_time=end_time,
            response_format=response_format,
            area=area,
            pokestop_id=pokestop_id,
            display_type=display_type,
            character=character,
            grunt=grunt,
            confirmed=confirmed,
            limit=limit,
        ),
    )

async def get_quest_data(
    client: APIClient,
    *,
    start_time: str,   # e.g. "202503"
    end_time: str,     # e.g. "202504"
    response_format: str = "json",
    area: str = "global",
    pokestop_id: str = "all",
    ar_type: str = "all",
    normal_type: str = "all",
    reward_ar_type: str = "all",
    reward_normal_type: str = "all",
    reward_ar_item_id: str = "all",
    reward_normal_item_id: str = "all",
    reward_ar_poke_id: str = "all",
    reward_normal_poke_id: str = "all",
    limit: Optional[int] = 0,
) -> Any:
    """GET /api/sql/get_quest_data"""
    return await client.get(
        "/api/sql/get_quest_data",
        **_params(
            start_time=start_time,
            end_time=end_time,
            response_format=response_format,
            area=area,
            pokestop_id=pokestop_id,
            ar_type=ar_type,
            normal_type=normal_type,
            reward_ar_type=reward_ar_type,
            reward_normal_type=reward_normal_type,
            reward_ar_item_id=reward_ar_item_id,
            reward_normal_item_id=reward_normal_item_id,
            reward_ar_poke_id=reward_ar_poke_id,
            reward_normal_poke_id=reward_normal_poke_id,
            limit=limit,
        ),
    )
