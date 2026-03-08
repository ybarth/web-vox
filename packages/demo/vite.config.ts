import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  server: {
    port: 5196,
    strictPort: true,
  },
  preview: {
    port: 5196,
    strictPort: true,
  },
  resolve: {
    alias: {
      '@web-vox/core': resolve(__dirname, '../core/src/index.ts'),
    },
  },
  optimizeDeps: {
    exclude: ['web-vox-native-bridge'],
  },
  build: {
    rollupOptions: {
      external: ['web-vox-native-bridge'],
    },
  },
});
