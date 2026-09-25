import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// No dev proxy. Both display feeds (gate.io and coingecko) send permissive CORS
// headers and are called straight from the browser -- verified against both
// endpoints from a browser origin. A proxy would only exist in development and
// would therefore hide a production failure rather than prevent one.
//
// Those display prices never reach the contract; it fetches its own inside the
// equivalence block. See src/lib/prices.ts.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: { outDir: "dist", sourcemap: true },
});
