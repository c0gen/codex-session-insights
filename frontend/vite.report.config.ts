import { defineConfig } from 'vite';

// Reports are one offline HTML file; live desktop builds retain lazy chunks.
export default defineConfig({
  base: './',
  build: {
    target: ['chrome100', 'safari15'], outDir: 'dist/report',
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
