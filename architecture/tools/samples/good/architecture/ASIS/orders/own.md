Что сервис заказов делает сам, вне процессов: при старте закрывает заказы, брошенные до оплаты.

## Закрывает брошенные заказы {#stale}

При каждом старте сервиса заказы со статусом `new` старше [[STALE]] получают статус `failed`: оплата по ним так и не прошла.
Справочник: читает [[STALE]] · читает [[orders.status]] · читает [[orders.created_at]] · пишет [[orders.status]]
Проблемы: [[p-no-retry]]
Код: `src/orders/orders/main.py:8` · `src/orders/orders/startup.py:7` · `src/orders/orders/startup.py:12`
