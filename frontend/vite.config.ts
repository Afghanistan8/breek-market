import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The price charts on the market page are display-only. They are fetched
// through this dev proxy purely to dodge CORS in local development; nothing the
// browser sees ever reaches the contract, which fetches its own prices.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/px/gate": {
        target: "https://api.gateio.ws",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/px\/gate/, ""),
      },
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
