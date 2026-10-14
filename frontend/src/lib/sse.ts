import { API_BASE, ApiError } from './api'
import type { StreamEvent } from './types'

/**
 * 以 POST 发起 SSE 请求并逐条回调事件。
 *
 * 没用 EventSource 的原因：EventSource 只支持 GET，无法携带对话请求体。
 * 这里用 fetch + ReadableStream 手工解析 `data:` 帧，行为等价且支持 POST。
 */
export async function streamChat(
  payload: {
    user_id: number
    message: string
    conversation_id?: number | null
    enable_review?: boolean
    enable_retrieval?: boolean
    /** 缺省由后端读取全局配置：计划落库前是否暂停等人工确认。 */
    confirm_commit?: boolean
  },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        conversation_id: null,
        enable_review: false,
        ...payload,
      }),
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }
    throw new ApiError(0, `无法连接后端 ${API_BASE}，请确认服务已启动`)
  }

  if (!response.ok || !response.body) {
    throw new ApiError(response.status, `流式请求失败（HTTP ${response.status}）`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }

    buffer += decoder.decode(value, { stream: true })

    // SSE 以空行分隔事件帧
    let separator = buffer.indexOf('\n\n')
    while (separator !== -1) {
      const frame = buffer.slice(0, separator)
      buffer = buffer.slice(separator + 2)
      emit(frame, onEvent)
      separator = buffer.indexOf('\n\n')
    }
  }

  if (buffer.trim()) {
    emit(buffer, onEvent)
  }
}

function emit(frame: string, onEvent: (event: StreamEvent) => void): void {
  const dataLines = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())

  if (dataLines.length === 0) {
    return
  }

  try {
    onEvent(JSON.parse(dataLines.join('\n')) as StreamEvent)
  } catch {
    // 单帧解析失败不应中断整个流
  }
}
