Своя база Postgres; миграции — alembic.

## orders

Заказы: кто заказал, сумма, статус и когда оплачен. Номер заказа — `id`: его даёт база при записи, он же уникальный ключ.
Единицы:
- `amount` — доллары
Код: `src/orders/orders/models.py:10` · `src/orders/orders/models.py:12`

### orders.paid_at
Хранится: момент в UTC
Означает: когда шлюз подтвердил списание; пусто — заказ не оплачен
Пример: оплачен в 15:00 по Москве — 12:00 UTC
Код: `src/orders/orders/service.py:20`

### orders.status
Не просто «оплачен или нет». `new` — записан, деньги ещё не списаны; `paid` — списаны; `failed` — заказ брошен: к старту сервиса он был «новым» дольше часа.
Код: `src/orders/orders/service.py:19` · `src/orders/orders/startup.py:7`
