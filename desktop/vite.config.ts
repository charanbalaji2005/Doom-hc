import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';


export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': new URL('./src', import.meta.url).pathname } },
  clearScreen: false,
  server: { port: 5173, strictPort: true },
  test: { environment: 'node' },
} as never);
