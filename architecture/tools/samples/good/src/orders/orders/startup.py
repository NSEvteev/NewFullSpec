"""Что сервис делает при старте."""

from sqlalchemy import text

from orders.db import engine

STALE = "UPDATE orders SET status = 'failed' WHERE status = 'new' AND created_at < now() - interval '1 hour'"


async def on_startup() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(STALE))
