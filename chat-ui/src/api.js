export async function login(userId, password) {
  const res = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, password }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error || 'Login failed')
  return data
}

// Reads an SSE stream and returns the first meaningful result:
//   { type: 'complete',      content: string }
//   { type: 'confirmation',  content: string, pendingTask: string }
//   null  — stream ended without a result
async function readSSEStream(response) {
  if (!response.ok) throw new Error('Request failed')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop()
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const raw = line.slice(6)
      if (raw === '[DONE]') return null
      try {
        const chunk = JSON.parse(raw)
        if (chunk.is_task_complete) {
          return { type: 'complete', content: chunk.content }
        }
        if (chunk.requires_confirmation) {
          return {
            type: 'confirmation',
            content: chunk.content,
            pendingTask: chunk.pending_task,
          }
        }
      } catch (_) {}
    }
  }
  return null
}

export async function sendMessage(userId, conversationId, message) {
  const res = await fetch('/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId,
    },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  })
  return readSSEStream(res)
}

export async function confirmAction(userId, conversationId, approved) {
  const res = await fetch('/chat/confirm', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId,
    },
    body: JSON.stringify({ conversation_id: conversationId, approved }),
  })
  return readSSEStream(res)
}
