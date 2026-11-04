"""Таблица заказов."""

from sqlalchemy import Column, DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID

from orders.db import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID, primary_key=True, server_default=func.gen_random_uuid())
    customer = Column(String, nullable=False, comment="Кто заказал: почта покупателя")
    amount = Column(Numeric(10, 2), nullable=False, comment="Сумма заказа")
    status = Column(String, nullable=False, default="new", comment="Статус заказа")
    paid_at = Column(DateTime(timezone=True), nullable=True, comment="Когда оплачен")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
