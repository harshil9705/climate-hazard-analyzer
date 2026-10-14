import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // In dev, proxy API calls to the local FastAPI server so no CORS setup is needed.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
