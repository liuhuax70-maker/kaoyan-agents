import type { Metadata } from 'next'
import type { ReactNode } from 'react'

import { AppShell } from '@/components/AppShell'
import { WorkspaceProvider } from '@/components/WorkspaceProvider'

import './globals.css'

export const metadata: Metadata = {
  title: '考研考证学习规划与督促系统',
  description: '基于多智能体的考研考证学习规划与督促系统工作台',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <WorkspaceProvider>
          <AppShell>{children}</AppShell>
        </WorkspaceProvider>
      </body>
    </html>
  )
}
