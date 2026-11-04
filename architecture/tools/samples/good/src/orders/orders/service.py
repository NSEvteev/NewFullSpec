"""Создание заказа: проверка, запись, оплата."""

from sqlalchemy import func, select

from orders import payments
from orders.models import Order

MAX_ITEMS = 50  # больше позиций в одном заказе шлюз не принимает


async def create_order(db, customer: str, items: list[dict]) -> Order:
    if len(items) > MAX_ITEMS:
        raise ValueError("TOO_MANY_ITEMS")
    amount = sum(i["price"] * i["qty"] for i in items)
    order = Order(customer=customer, amount=amount, status="new")
    db.add(order)
    await db.commit()
    await payments.charge(str(order.id), amount)
    order.status = "paid"
    order.paid_at = func.now()
    await db.commit()
    return order


async def get_order(db, order_id: str) -> Order | None:
    return (
        await db.execute(select(Order).where(Order.id == order_id))
    ).scalar_one_or_none()
