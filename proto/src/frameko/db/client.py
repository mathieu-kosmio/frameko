from functools import lru_cache
from typing import AsyncGenerator

import psycopg
from psycopg_pool import AsyncConnectionPool
from supabase import AsyncClient, acreate_client

from frameko.config import settings

_pool: AsyncConnectionPool | None = None


@lru_cache(maxsize=1)
def _supabase_client() -> AsyncClient:
    # AsyncClient is created once and reused; acreate_client is awaited at startup
    raise RuntimeError("Call init_supabase() first")


async def init_supabase() -> AsyncClient:
    client = await acreate_client(settings.supabase_url, settings.supabase_secret_key)
    return client


async def init_pool() -> None:
    global _pool
    _pool = AsyncConnectionPool(settings.database_url, min_size=2, max_size=10, open=False)
    await _pool.open()


async def close_pool() -> None:
    if _pool:
        await _pool.close()


async def get_db() -> AsyncGenerator[psycopg.AsyncConnection, None]:
    if _pool is None:
        raise RuntimeError("Connection pool not initialised")
    async with _pool.connection() as conn:
        yield conn


# Supabase client stored at module level after startup
_supabase: AsyncClient | None = None


def get_supabase() -> AsyncClient:
    if _supabase is None:
        raise RuntimeError("Supabase client not initialised")
    return _supabase


def set_supabase(client: AsyncClient) -> None:
    global _supabase
    _supabase = client
