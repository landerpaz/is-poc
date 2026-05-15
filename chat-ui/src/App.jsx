import { useState } from 'react'
import LoginPage from './LoginPage'
import ChatPage from './ChatPage'

export default function App() {
  const [userId, setUserId] = useState(null)
  const [chatReady, setChatReady] = useState(false)

  function handleLogin(id) {
    setUserId(id)
  }

  function handleLogout() {
    setUserId(null)
    setChatReady(false)
  }

  if (!userId) {
    return <LoginPage onLogin={handleLogin} />
  }

  if (!chatReady) {
    return (
      <div className="welcome-container">
        <div className="welcome-card">
          <h1 className="brand">Agentic</h1>
          <p className="welcome-text">
            Welcome, <strong>{userId}</strong>! You are now signed in.
          </p>
          <a
            href="#"
            className="chat-link"
            onClick={e => { e.preventDefault(); setChatReady(true) }}
          >
            Go to Chat →
          </a>
        </div>
      </div>
    )
  }

  return <ChatPage userId={userId} onLogout={handleLogout} />
}
