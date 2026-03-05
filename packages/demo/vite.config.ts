import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
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
