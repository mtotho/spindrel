import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy all backend paths through Vite so the browser sees one
// origin (`localhost:5173`). This eliminates CORS preflights and consolidates
// the HTTP/1.1 6-conn-per-origin budget so long-lived SSE streams (channel
// events, session-plan events, unread events) don't starve regular fetches.
//
// Override the target with `VITE_API_TARGET=http://other-host:8000` if you
// point the dev server at a different backend.
const apiTarget = process.env.VITE_API_TARGET ?? "http://10.10.30.208:8000";

const proxyEntry = {
  target: apiTarget,
  changeOrigin: true,
  secure: false,
  ws: true,
};

export default defineConfig({
  plugins: [react()],
  resolve: {
    tsconfigPaths: true,
  },
  server: {
    port: 5173,
    fs: {
      allow: [".."],
    },
    proxy: {
      "/api": proxyEntry,
      "/auth": proxyEntry,
      "/chat": proxyEntry,
      "/health": proxyEntry,
      "/sessions": proxyEntry,
      "/export": proxyEntry,
      "/events": proxyEntry,
    },
  },
  build: {
    outDir: "dist",
  },
});
