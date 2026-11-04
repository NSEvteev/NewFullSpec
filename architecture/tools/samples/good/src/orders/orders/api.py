"""Методы сервиса заказов."""

from fastapi import APIRouter, Depends, HTTPException

from orders.deps import get_db
from orders.payments import PaymentError
from orders.service import create_order, get_order

router = APIRouter(prefix="/api/v1")


@router.post("/orders", status_code=201)
async def post_order(body: dict, db=Depends(get_db)):
    try:
        return await create_order(db, body["customer"], body["items"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    except PaymentError:
        raise HTTPException(502, "PAYMENT_FAILED")


@router.get("/orders/{order_id}")
async def read_order(order_id: str, db=Depends(get_db)):
    order = await get_order(db, order_id)
    if order is None:
        raise HTTPException(404, "ORDER_NOT_FOUND")
    return order


@router.get("/health")
async def health():
    return {"status": "ok"}
