from __future__ import annotations
from typing import Optional
from utils.db import ensure_pool, close_pool
import config as AppConfig

DB_KEY = "dragonite"

async def ensure_dragonite_pool(
    key: str = DB_KEY,
    *,
    host: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    db: Optional[str] = None,
    port: Optional[int] = None,
):
    """
    Ensure the Dragonite MySQL pool exists.
    Values default to config envs:
      DRAGONITE_DB_HOST, DRAGONITE_DB_PORT, DRAGONITE_DB_USER, DRAGONITE_DB_PASSWORD, DRAGONITE_DB_NAME
    """
    await ensure_pool(
        key=key,
        host=host or AppConfig.DRAGONITE_DB_HOST,
        user=user or AppConfig.DRAGONITE_DB_USER,
        password=password or AppConfig.DRAGONITE_DB_PASSWORD,
        db=db or AppConfig.DRAGONITE_DB_NAME,
        port=port or int(AppConfig.DRAGONITE_DB_PORT),
        minsize=1,
        maxsize=10,
        autocommit=True,
    )

async def ensure_dragonite_pool_alive(
    key: str = DB_KEY,
    *,
    host: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    db: Optional[str] = None,
    port: Optional[int] = None,
):
    """
    Ensure the pool exists AND is usable. If the pool is missing/closed or
    a test ping fails, recreate it.
    """
    from utils.db import _pools  # internal registry used by ensure_pool/_conn_cursor

    pool = _pools.get(key)
    if pool is None or pool.closed:
        await ensure_dragonite_pool(key, host=host, user=user, password=password, db=db, port=port)
        return

    # Sanity check: try to acquire and ping; if that fails, recreate pool.
    conn = await pool.acquire()
    try:
        try:
            await conn.ping(reconnect=True)
        except Exception:
            # The pool object exists but connections are busted → recreate cleanly
            await close_pool(key)
            await ensure_dragonite_pool(key, host=host, user=user, password=password, db=db, port=port)
    finally:
        try:
            pool.release(conn)
        except Exception:
            pass
