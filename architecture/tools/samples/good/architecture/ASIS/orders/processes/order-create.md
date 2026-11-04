orders принимает заказ, записывает его со статусом «новый», списывает деньги через платёжный шлюз и отмечает заказ оплаченным.

## Принимает заказ {#accept}

Проверяет, что позиций не больше [[MAX_ITEMS]], и считает сумму по ценам и количеству.
Справочник: обрабатывает [[POST /api/v1/orders]] · читает [[MAX_ITEMS]]
Код: `src/orders/orders/service.py:12` · `src/orders/orders/service.py:14`

## Записывает заказ {#row}

Записывает заказ со статусом `new` до оплаты: если шлюз не ответит, заказ не пропадёт.
Справочник: обрабатывает [[POST /api/v1/orders]] · пишет [[orders]]
Код: `src/orders/orders/service.py:16` · `src/orders/orders/service.py:17`

## Списывает деньги {#charge}

Просит шлюз списать сумму заказа и после ответа ставит заказу статус `paid` и время оплаты.
Справочник: обрабатывает [[POST /api/v1/orders]] · зовёт [[external:payments: POST /v1/charges]] · пишет [[orders.status]] · пишет [[orders.paid_at]]
Проблемы: [[p-no-retry]]
Код: `src/orders/orders/service.py:18` · `src/orders/orders/service.py:19` · `src/orders/orders/service.py:20`
