import { defineConfig } from "vite";

// Separate build keeps the dashboard's standalone HTML export free of imports.
export default defineConfig({
  root: "widget",
  base: "./",
  build: { outDir: "../dist/widget", emptyOutDir: true, target: "chrome100" },
});
