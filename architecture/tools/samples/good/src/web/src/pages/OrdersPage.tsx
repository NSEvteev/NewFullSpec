// @ts-nocheck — код проверочной карты: его не собирают и не запускают, на его строки ведут ссылки «Код:»
import { useState } from "react";
import { CartItem, createOrder } from "../api";

const CART_KEY = "cart";

export default function OrdersPage() {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState("");
  const cart: CartItem[] = JSON.parse(localStorage.getItem(CART_KEY) ?? "[]");

  async function submit() {
    try {
      const order = await createOrder(email, cart);
      localStorage.removeItem(CART_KEY);
      setResult(`Заказ ${order.id}: ${order.status}`);
    } catch (e) {
      setResult(String(e));
    }
  }

  return (
    <div>
      <ul>{cart.map((i) => <li key={i.name}>{i.name} × {i.qty}</li>)}</ul>
      <input placeholder="почта" value={email} onChange={(e) => setEmail(e.target.value)} />
      <button onClick={submit}>Оформить</button>
      <p>{result}</p>
    </div>
  );
}
