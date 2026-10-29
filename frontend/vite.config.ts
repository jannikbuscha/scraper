import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// `make dev`: the Vite dev server forwards /api to the backend.
const apiProxy = { '/api': 'http://127.0.0.1:8000' };

// Libraries change less often than the app: separate chunks stay cached and
// each stays below Vite's chunk size warning.
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
