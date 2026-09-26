import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Python API (web/api/server.py) runs on port 8000. During `npm run dev`,
// Vite serves the React app on 5173 and forwards /api/* to it, so the browser
// sees one origin and no CORS setup is needed.
const API = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": API } },
  preview: { port: 4173, proxy: { "/api": API } },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // MapLibre alone is ~1 MB minified. It's only loaded on the map page.
    chunkSizeWarningLimit: 1200,
  },
});
