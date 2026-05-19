import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/chat': 'http://localhost:10001',
      '/auth': 'http://localhost:10001',
    },
    // Note: '/chat/confirm' is covered by the '/chat' prefix above
  },
})
