import type { NextConfig } from 'next'

/**
 * 前端直接以浏览器身份调用后端接口：
 * 后端已通过 CORS 放行 localhost:3000，无需在 Next.js 侧做反向代理，
 * 这样 SSE 流式响应不会被中间层缓冲。
 *
 * output: 'standalone' 用于产出精简的容器镜像（只打包运行所需文件）。
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: 'standalone',
  async redirects() {
    return [
      // 工作台板块已移除，根路径统一落到对话页
      { source: '/', destination: '/chat', permanent: false },
    ]
  },
}

export default nextConfig
