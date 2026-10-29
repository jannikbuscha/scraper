import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The backend's same-origin check compares Origin with Host (docs/API.md §1.1),
// so the proxy must keep the browser's Host header: changeOrigin stays false.
const apiProxy = {
  '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
};

// Libraries change less often than the app: separate chunks stay cached
// (/assets is served as immutable, docs/API.md §6) and each stays below
// Vite's chunk size warning.
const vendorChunks = [
  { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 3 },
  { name: 'mantine', test: /node_modules[\\/](@mantine|@floating-ui)[\\/]/, priority: 2 },
  { name: 'tanstack', test: /node_modules[\\/]@tanstack[\\/]/, priority: 2 },
  { name: 'vendor', test: /node_modules[\\/]/, priority: 1 },
];

export default defineConfig({
  base: '/',
  plugins: [react()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rolldownOptions: { output: { codeSplitting: { groups: vendorChunks } } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
    unstubGlobals: true,
    unstubEnvs: true,
  },
});
