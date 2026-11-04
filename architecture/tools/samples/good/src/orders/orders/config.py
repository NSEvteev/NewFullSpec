"""Настройки сервиса заказов: читаются из окружения при старте."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    PAYMENTS_URL: str = "https://pay.example.com"
    PAYMENTS_API_KEY: str


settings = Settings()
