'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cx } from './ui'

/**
 * 渲染助手正文。
 *
 * 后端在「双轨输出」改造后直接下发生成的 markdown 原文（标题、列表、代码块、
 * 表格都可能出现），因此这里必须真正解析，而不是原样铺排——`remark-gfm`
 * 补上表格、删除线、任务列表这些 GitHub 扩展语法。
 *
 * 排版规则集中在 `globals.css` 的 `.answer-body` 下，组件只负责挂类名。
 */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cx('answer-body text-[14px] leading-[1.75] text-ink', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // 外部链接一律新窗口打开：简报里的核验入口是外站，留在当前页会打断学习流。
          a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}