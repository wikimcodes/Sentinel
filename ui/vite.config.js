import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy /api to the Sentinel backend (the live agent). fs.allow lets the
// initial patient list import the sibling data file if the backend is down.
export default defineConfig({
  plugins: [react()],
  server: {
    fs: { allow: [".."] },
    proxy: { "/api": "http://localhost:8787" },
  },
});
