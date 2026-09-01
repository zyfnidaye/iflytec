import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,                // 监听所有网卡，允许非 localhost 访问
    port: 5173,
    // 允许内网穿透域名访问（Vite 默认只放行 localhost，域名会被拦成 Blocked request）
    allowedHosts: ['.natappfree.cc'],
    proxy: {
      // 把 /api 代理到后端，省去跨域烦恼
      '/api': {
        target: 'http://localhost:8123',
        changeOrigin: true,
      },
    },
  },
})
