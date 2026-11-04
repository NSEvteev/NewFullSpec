"""Сессия своей базы для методов."""

from sqlalchemy.ext.asyncio import async_sessionmaker

from orders.db import engine

Session = async_sessionmaker(engine)


async def get_db():
    async with Session() as session:
        yield session
