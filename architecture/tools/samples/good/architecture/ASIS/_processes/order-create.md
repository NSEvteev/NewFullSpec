# Создание заказа

Покупатель оформляет корзину на странице заказов; orders записывает заказ и списывает за него деньги через платёжный шлюз, покупатель видит заказ оплаченным.

Кто запускает: покупатель на странице `/orders`: «Оформить»
Чем кончается: заказ записан со статусом `paid`; покупатель видит номер заказа, корзина пуста
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
| charge | orders → external:payments | списать сумму заказа | [[external:payments: POST /v1/charges]] | внешний провайдер | orders#charge |
| paid | orders → orders | статус `paid` и время оплаты | [[orders: orders.status]] · [[orders: orders.paid_at]] | база | orders#charge |
| show | web → human | номер заказа и статус | [[web: /orders]] | человек | web#show |
