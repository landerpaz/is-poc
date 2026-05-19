import { useState, useRef, useEffect } from 'react'
import { sendMessage, confirmAction } from './api'

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
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

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

  async function handleSend() {
    const text = input.trim()
    if (!text || sending) return

    setInput('')
    setSending(true)

    const thinkingKey = `thinking-${Date.now()}`
    setMessages(prev => [
      ...prev,
      { role: 'user', content: text },
      { role: 'thinking', content: 'The host agent is thinking…', key: thinkingKey },
    ])

    try {
      const result = await sendMessage(userId, conversationId, text)
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
    // Remove the confirmation widget and show a thinking indicator
    setMessages(prev => prev.filter(m => m.key !== confirmKey))
    setSending(true)

    const thinkingKey = `thinking-${Date.now()}`
    setMessages(prev => [
      ...prev,
      {
        role: 'thinking',
        content: approved ? 'Executing operation…' : 'Cancelling operation…',
        key: thinkingKey,
      },
    ])

    try {
      const result = await confirmAction(userId, conversationId, approved)
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

            <div className="msg-content">{msg.content}</div>

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
