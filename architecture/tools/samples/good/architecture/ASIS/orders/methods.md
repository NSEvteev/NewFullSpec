## POST /api/v1/orders
Группа: Заказы
Что делает: создаёт заказ и сразу списывает за него деньги.
Ошибки:
- 422 `TOO_MANY_ITEMS` — позиций больше [[MAX_ITEMS]]
- 502 `PAYMENT_FAILED` — платёжный шлюз не ответил или отказал
Доступ: без входа
Код: `src/orders/orders/api.py:13` · `src/orders/orders/api.py:17` · `src/orders/orders/api.py:19`

## GET /api/v1/orders/{order_id}
Группа: Заказы
Что делает: отдаёт заказ по номеру — сумму, статус и когда оплачен.
Ошибки:
- 404 `ORDER_NOT_FOUND` — заказа с таким номером нет
Доступ: без входа
Вручную: человек командой `curl`, когда покупатель спрашивает о своём заказе
Справочник: читает [[orders]]
Код: `src/orders/orders/api.py:24` · `src/orders/orders/api.py:26`
