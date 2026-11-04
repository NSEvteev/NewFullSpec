export type CartItem = { name: string; price: number; qty: number };

const ORDERS = "/api/v1/orders";

export async function createOrder(customer: string, items: CartItem[]) {
  const resp = await fetch(ORDERS, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customer, items }),
  });
  if (!resp.ok) throw new Error(await resp.text());
  return resp.json();
}
