// @ts-nocheck — код проверочной карты: его не собирают и не запускают, на его строки ведут ссылки «Код:»
import { createBrowserRouter } from "react-router-dom";
import OrdersPage from "./pages/OrdersPage";

export const router = createBrowserRouter([
  { path: "/orders", element: <OrdersPage /> },
]);
