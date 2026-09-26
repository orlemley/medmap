import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Python API (web/api/server.py) runs on port 8000. During `npm run dev`,
// Vite serves the React app on 5173 and forwards /api/* to it, so the browser
// sees one origin and no CORS setup is needed. In Docker the API is another
// container, so docker-compose.yml sets API_PROXY_TARGET=http://medmap:8000.
const API = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

// File-change events don't reach a container from a Windows/macOS host, so
// the Docker dev service turns on polling.
const watch = process.env.VITE_USE_POLLING ? { usePolling: true, interval: 300 } : undefined;

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": API }, watch },
  preview: { port: 4173, proxy: { "/api": API } },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // MapLibre alone is ~1 MB minified. It's only loaded on the map page.
    chunkSizeWarningLimit: 1200,
  },
});
