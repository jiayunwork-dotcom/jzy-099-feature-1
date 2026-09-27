import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时把 /api 代理到本机 FastAPI（后端默认 8000，可用 VITE_API_PORT 覆盖）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: `http://localhost:${process.env.VITE_API_PORT ?? "8000"}`,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
