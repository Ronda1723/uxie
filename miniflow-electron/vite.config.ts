import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  root: "src/renderer",
  base: "./",
  plugins: [react()],
  resolve: {
    alias: {
      "@shared": path.resolve(__dirname, "src/shared"),
    },
  },
  build: {
    outDir: path.resolve(__dirname, "build/renderer"),
    emptyOutDir: true,
    target: "es2022",
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, "src/renderer/index.html"),
        overlay: path.resolve(__dirname, "src/renderer/overlay.html"),
      },
    },
  },
  server: {
    port: 5174,
    strictPort: true,
  },
});
