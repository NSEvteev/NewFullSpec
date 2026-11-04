web отправляет корзину покупателя в orders и показывает итог: номер заказа и статус.

## Отправляет заказ {#submit}

По кнопке «Оформить» отправляет в orders почту покупателя и позиции корзины.
Справочник: обрабатывает [[/orders]] · читает [[cart]] · зовёт [[orders: POST /api/v1/orders]]
Код: `src/web/src/pages/OrdersPage.tsx:26` · `src/web/src/pages/OrdersPage.tsx:10` · `src/web/src/pages/OrdersPage.tsx:14` · `src/web/src/api.ts:6`

## Показывает итог {#show}

Показывает номер заказа и статус и очищает корзину.
Справочник: обрабатывает [[/orders]] · пишет [[cart]]
Код: `src/web/src/pages/OrdersPage.tsx:16` · `src/web/src/pages/OrdersPage.tsx:15`
