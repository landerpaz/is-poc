import { useState, useRef, useEffect, useCallback } from 'react'
import { sendMessage, confirmAction } from './api'

function formatElapsed(ms) {
  const totalSec = Math.floor(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

// conversation_id format: conversation:<userId>:<uuid>
// Created once per ChatPage mount (i.e. each time user clicks "Go to Chat").
function createConversationId(userId) {
  return `conversation:${userId}:${crypto.randomUUID()}`
}

export default function ChatPage({ userId, onLogout }) {
  const [conversationId] = useState(() => createConversationId(userId))
  const [messages, setMessages] = useState([
    { role: 'agent', content: 'Hello! How can I help you today?' },
  ])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (!sending) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [sending])

  // Apply result from sendMessage / confirmAction to the message list.
  // Removes the thinking placeholder identified by thinkingKey, then
  // appends either an agent reply or an inline confirmation widget.
  function applyResult(result, thinkingKey) {
    if (!result) {
      setMessages(prev => prev.filter(m => m.key !== thinkingKey))
      return
    }
    if (result.type === 'complete') {
      setMessages(prev => [
        ...prev.filter(m => m.key !== thinkingKey),
        { role: 'agent', content: result.content },
      ])
    } else if (result.type === 'confirmation') {
      const confirmKey = `confirmation-${Date.now()}`
      setMessages(prev => [
        ...prev.filter(m => m.key !== thinkingKey),
        {
          role: 'confirmation',
          content: result.content,
          pendingTask: result.pendingTask,
          key: confirmKey,
        },
      ])
    }
  }

  // Appends a progress step to the thinking bubble identified by thinkingKey.
  function addProgressStep(thinkingKey, content) {
    setMessages(prev => prev.map(m =>
      m.key === thinkingKey
        ? { ...m, steps: [...(m.steps ?? []), { content, startedAt: Date.now() }] }
        : m
    ))
  }

  async function handleSend() {
    const text = input.trim()
    if (!text || sending) return

    setInput('')
    setSending(true)

    const thinkingKey = `thinking-${Date.now()}`
    setMessages(prev => [
      ...prev,
      { role: 'user', content: text },
      { role: 'thinking', content: 'Working…', steps: [], key: thinkingKey },
    ])

    try {
      const result = await sendMessage(
        userId,
        conversationId,
        text,
        content => addProgressStep(thinkingKey, content),
      )
      applyResult(result, thinkingKey)
    } catch (err) {
      setMessages(prev => [
        ...prev.filter(m => m.key !== thinkingKey),
        { role: 'error', content: `Error: ${err.message}` },
      ])
    } finally {
      setSending(false)
    }
  }

  async function handleConfirm(confirmKey, approved) {
    setMessages(prev => prev.filter(m => m.key !== confirmKey))
    setSending(true)

    const thinkingKey = `thinking-${Date.now()}`
    setMessages(prev => [
      ...prev,
      {
        role: 'thinking',
        content: approved ? 'Executing operation…' : 'Cancelling operation…',
        steps: [],
        key: thinkingKey,
      },
    ])

    try {
      const result = await confirmAction(
        userId,
        conversationId,
        approved,
        content => addProgressStep(thinkingKey, content),
      )
      applyResult(result, thinkingKey)
    } catch (err) {
      setMessages(prev => [
        ...prev.filter(m => m.key !== thinkingKey),
        { role: 'error', content: `Error: ${err.message}` },
      ])
    } finally {
      setSending(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-container">
      <header className="chat-header">
        <span className="brand">Agentic</span>
        <span className="user-info">
          Logged in as <strong>{userId}</strong>
        </span>
        <button className="logout-btn" onClick={onLogout}>
          Logout
        </button>
      </header>

      <div className="messages">
        {messages.map((msg, i) => (
          <div key={msg.key ?? i} className={`msg msg-${msg.role}`}>
            {msg.role === 'user' && <div className="msg-label">You</div>}
            {msg.role === 'agent' && <div className="msg-label">Host Agent</div>}
            {msg.role === 'confirmation' && <div className="msg-label">Confirmation required</div>}
            {msg.role === 'thinking' && <div className="msg-label">Working</div>}

            {msg.role === 'thinking' && msg.steps?.length > 0 ? (
              <div className="thinking-log">
                {msg.steps.map((step, si) => {
                  const isLast = si === msg.steps.length - 1
                  const elapsed = isLast
                    ? now - step.startedAt
                    : msg.steps[si + 1].startedAt - step.startedAt
                  return (
                    <div key={si} className={`thinking-step ${isLast ? 'thinking-step--active' : 'thinking-step--done'}`}>
                      <span className="thinking-step-icon" aria-hidden="true">
                        {isLast ? '⟳' : '✓'}
                      </span>
                      <span className="thinking-step-text">{step.content}</span>
                      <span className="thinking-step-timer">{formatElapsed(elapsed)}</span>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="msg-content">{msg.content}</div>
            )}

            {msg.role === 'confirmation' && (
              <div className="confirmation-actions">
                <button
                  className="confirm-btn approve"
                  onClick={() => handleConfirm(msg.key, true)}
                  disabled={sending}
                >
                  Approve
                </button>
                <button
                  className="confirm-btn cancel"
                  onClick={() => handleConfirm(msg.key, false)}
                  disabled={sending}
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="input-row">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message…"
          disabled={sending}
          autoFocus
        />
        <button
          className="send-btn"
          onClick={handleSend}
          disabled={sending || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  )
}
