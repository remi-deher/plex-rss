import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  base: "/vue/",
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./frontend/src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/login": "http://127.0.0.1:8000",
      "/logout": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "app/static/vue",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    include: ["frontend/src/**/*.{test,spec}.js"],
    globals: false,
  },
});
