import { defineConfig } from 'vite';
export default defineConfig({ root: '.', server: { port: 1420, strictPort: true }, build: { outDir: 'dist-ui', emptyOutDir: true } });
