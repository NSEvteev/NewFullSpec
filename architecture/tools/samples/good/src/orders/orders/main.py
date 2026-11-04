"""Приложение сервиса заказов: методы и работа при старте."""

from fastapi import FastAPI

from orders.api import router
from orders.startup import on_startup

app = FastAPI(on_startup=[on_startup])
app.include_router(router)
