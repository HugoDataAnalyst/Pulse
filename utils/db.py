from __future__ import annotations # This is only relevant for lower versions than python3.11
import aiomysql
from contextlib import asynccontextmanager
from typing import Any, Type, TypeVar, Optional
from pydantic import BaseModel, TypeAdapter
from loguru import logger

# ── Pool registry (multi-DB)
_pools: dict[str, aiomysql.Pool] = {}

async def ensure_pool(
    key: str,
    *,
    host: str,
    user: str,
    password: str,
    db: str,
    port: int = 3306,
    minsize: int = 1,
    maxsize: int = 10,
    autocommit: bool = True,
    charset: str = "utf8mb4",
) -> None:
    """Create or reuse a pool identified by `key`."""
    if key in _pools and not _pools[key].closed:
        logger.debug(f"[db] Pool '{key}' already active")
        return
    _pools[key] = await aiomysql.create_pool(
        host=host,
        port=port,
        user=user,
        password=password,
        db=db,
        minsize=minsize,
        maxsize=maxsize,
        autocommit=autocommit,
        charset=charset,
        cursorclass=aiomysql.DictCursor,
    )
    logger.success(f"[db] Pool '{key}' connected to {user}@{host}:{port}/{db}")

async def close_pool(key: str) -> None:
    pool = _pools.pop(key, None)
    if pool:
        pool.close()
        await pool.wait_closed()
        logger.info(f"[db] Pool '{key}' closed")

async def close_all_pools() -> None:
    for key, pool in list(_pools.items()):
        pool.close()
        await pool.wait_closed()
        _pools.pop(key, None)

@asynccontextmanager
async def _conn_cursor(key: str):
    pool = _pools.get(key)
    assert pool is not None, f"DB pool '{key}' not initialized"
    conn = await pool.acquire()
    try:
        try:
            await conn.ping(reconnect=True)
        except Exception:
            await conn.ensure_closed()
            conn = await pool.acquire()
        cur = await conn.cursor()  # DictCursor from pool default
        try:
            yield conn, cur
        finally:
            await cur.close()
    finally:
        pool.release(conn)

T = TypeVar("T", bound=BaseModel)

async def fetch_all_as(key: str, model: Type[T], sql: str, params: tuple[Any, ...] = ()) -> list[T]:
    async with _conn_cursor(key) as (_, cur):
        await cur.execute(sql, params)
        rows = await cur.fetchall()
        return TypeAdapter(list[model]).validate_python(rows)

async def fetch_one_as(key: str, model: Type[T], sql: str, params: tuple[Any, ...] = ()) -> Optional[T]:
    async with _conn_cursor(key) as (_, cur):
        await cur.execute(sql, params)
        row = await cur.fetchone()
        return model.model_validate(row) if row else None

async def exec_sql(key: str, sql: str, params: tuple[Any, ...] = ()) -> int:
    async with _conn_cursor(key) as (_, cur):
        await cur.execute(sql, params)
        return cur.rowcount  # autocommit is True

@asynccontextmanager
async def transaction(key: str):
    """Multi-statement atomic transaction on a specific DB."""
    pool = _pools.get(key)
    assert pool is not None, f"DB pool '{key}' not initialized"
    conn = await pool.acquire()
    try:
        await conn.begin()
        cur = await conn.cursor(aiomysql.DictCursor)
        try:
            yield cur
            await conn.commit()
        except:
            await conn.rollback()
            raise
        finally:
            await cur.close()
    finally:
        pool.release(conn)
