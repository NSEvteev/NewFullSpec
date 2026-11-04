"""Клиент платёжного шлюза: просит списать деньги за заказ."""

import httpx

from orders.config import settings

_PAYMENTS_TIMEOUT = 10  # секунд: замер 2026-10-01 — шлюз отвечает за 2–4 с


class PaymentError(Exception):
    """Шлюз не ответил или отказал."""


async def charge(order_id: str, amount: float) -> str:
    try:
        async with httpx.AsyncClient(timeout=_PAYMENTS_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.PAYMENTS_URL}/v1/charges",
                headers={"Authorization": f"Bearer {settings.PAYMENTS_API_KEY}"},
                json={"order_id": order_id, "amount": amount},
            )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise PaymentError(str(e)) from e
    return resp.json()["charge_id"]
