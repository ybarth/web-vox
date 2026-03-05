import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        'background/service-worker': resolve(__dirname, 'src/background/service-worker.ts'),
        'content/bridge': resolve(__dirname, 'src/content/bridge.ts'),
      },
      output: {
        dir: 'dist',
        entryFileNames: '[name].js',
        format: 'es',
      },
    },
    outDir: 'dist',
    emptyOutDir: true,
  },
});
