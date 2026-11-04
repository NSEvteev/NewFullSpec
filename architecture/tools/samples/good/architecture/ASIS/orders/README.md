Сервис заказов. Принимает заказ, хранит его и списывает за него деньги через платёжный шлюз. Заказ записывается до оплаты, поэтому при сбое шлюза он остаётся «новым», а не пропадает. Покупателей и каталог товаров не ведёт.

## Как устроен

FastAPI и своя база Postgres, миграции — alembic.
Код: `src/orders/orders/api.py:9` · `src/orders/orders/db.py:8`

## Связи

### → external:payments
Подпись: оплата
Адрес: [[PAYMENTS_URL]]
Вход: ключ [[PAYMENTS_API_KEY]] в заголовке `Authorization`
Ожидание: ждёт ответа до [[_PAYMENTS_TIMEOUT]]; повторов нет
При отказе: метод отвечает 502 `PAYMENT_FAILED`; заказ остаётся «новым» — [[p-no-retry]]
Ключ шлюза есть только у orders: другие сервисы магазина к шлюзу не ходят.
Код: `src/orders/orders/payments.py:18` · `src/orders/orders/payments.py:19` · `src/orders/orders/payments.py:16` · `src/orders/orders/api.py:19`

#### POST /v1/charges
Код: `src/orders/orders/payments.py:18`
