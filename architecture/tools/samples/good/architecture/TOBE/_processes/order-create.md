# Создание заказа

Покупатель оформляет корзину на странице заказов; orders записывает заказ и списывает за него деньги через платёжный шлюз, покупатель видит заказ оплаченным.

Кто запускает: покупатель на странице `/orders`: «Оформить»
::: меняется c-oc-end · предложено
Чем кончается: заказ записан со статусом `paid`; покупатель видит номер заказа, корзина пуста. Шлюз не ответил ни на одну попытку — заказ `new`, orders доводит оплату фоном, покупатель видит «оплата проверяется»
Почему: [[d-retry]] · [[d-poll]]
:::
Работает ли сейчас: да; проверено вживую 2026-10-01 — стрелки `submit`, `row`, `charge`
Участники: human · web · orders · external:payments
Группа: Заказы

## Оформить заказ {#checkout}

| id | кто → кому | что | как | вид | внутри |
|---|---|---|---|---|---|
| click | human → web | «Оформить» | [[web: /orders]], кнопка «Оформить» | человек | web#submit |
| submit | web → orders | почта покупателя и позиции | [[orders: POST /api/v1/orders]] | запрос | web#submit · orders#accept |
| row | orders → orders | заказ со статусом `new` | [[orders: orders]] | база | orders#row |

## Оплатить {#pay}

| id | кто → кому | что | как | вид | внутри |
|---|---|---|---|---|---|
::: меняется c-oc-charge · решено владельцем
| charge | orders → external:payments | списать сумму заказа с ключом повтора; до трёх попыток | [[external:payments: POST /v1/charges]] | внешний провайдер | orders#charge |
Почему: [[d-retry]]
:::
| paid | orders → orders | статус `paid` и время оплаты | [[orders: orders.status]] · [[orders: orders.paid_at]] | база | orders#charge |
::: уходит c-oc-show · предложено
| show | web → human | номер заказа и статус | [[web: /orders]] | человек | web#show |
Почему: [[d-poll]]
:::

::: новое c-oc-wait · предложено
## Дождаться оплаты {#wait}

| id | кто → кому | что | как | вид | внутри |
|---|---|---|---|---|---|
| poll | web → orders | номер заказа | [[orders: GET /api/v1/orders/{order_id}]] | запрос | web#poll · [[orders: GET /api/v1/orders/{order_id}]] |
| status | web → human | номер заказа и статус оплаты | [[web: /orders]] | человек | web#poll |
Почему: [[d-poll]]
:::
