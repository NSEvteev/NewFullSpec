// @ts-nocheck — код проверочной карты: его не собирают и не запускают, на его строки ведут ссылки «Код:»
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    server: {
      proxy: {
        "/api/v1/orders": { target: env.VITE_ORDERS_URL, changeOrigin: true },
      },
    },
  };
});
