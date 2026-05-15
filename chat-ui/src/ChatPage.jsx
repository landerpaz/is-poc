import { useState, useRef, useEffect } from 'react'
import { sendMessage } from './api'

// conversation_id format: <userId>-<uuid>
// Created once per ChatPage mount (i.e. each time user clicks "Go to Chat").
// The same id is sent with every message in this session so the server
// and Redis can group all turns under one key.
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
      const reply = await sendMessage(userId, conversationId, text)
      setMessages(prev => [
        ...prev.filter(m => m.key !== thinkingKey),
        { role: 'agent', content: reply ?? '(no response)' },
      ])
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
            <div className="msg-content">{msg.content}</div>
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
