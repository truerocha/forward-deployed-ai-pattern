import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
  server: {
    hmr: process.env.DISABLE_HMR !== 'true',
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          // Cloudscape core (shared across all views)
          'cloudscape-core': [
            '@cloudscape-design/components/app-layout',
            '@cloudscape-design/components/top-navigation',
            '@cloudscape-design/components/side-navigation',
            '@cloudscape-design/components/container',
            '@cloudscape-design/components/header',
            '@cloudscape-design/components/box',
            '@cloudscape-design/components/button',
            '@cloudscape-design/components/badge',
            '@cloudscape-design/components/breadcrumb-group',
            '@cloudscape-design/components/space-between',
            '@cloudscape-design/components/status-indicator',
            '@cloudscape-design/components/tabs',
            '@cloudscape-design/components/grid',
            '@cloudscape-design/components/i18n',
          ],
          // Cloudscape data components (table, cards, etc.)
          'cloudscape-data': [
            '@cloudscape-design/components/table',
            '@cloudscape-design/components/cards',
            '@cloudscape-design/components/key-value-pairs',
            '@cloudscape-design/components/column-layout',
            '@cloudscape-design/components/progress-bar',
            '@cloudscape-design/components/expandable-section',
            '@cloudscape-design/components/segmented-control',
            '@cloudscape-design/components/link',
          ],
          // Vendor: react ecosystem
          'vendor-react': ['react', 'react-dom', 'react-i18next', 'i18next'],
        },
      },
    },
  },
});
