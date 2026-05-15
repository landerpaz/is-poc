import { useState } from 'react'
import { login } from './api'

export default function LoginPage({ onLogin }) {
  const [userId, setUserId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(userId.trim(), password)
      onLogin(userId.trim())
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-container">
      <div className="login-card">
        <h1 className="brand">Agentic</h1>
        <h2 className="login-subtitle">Sign in to continue</h2>
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="userId">User ID</label>
            <input
              id="userId"
              type="text"
              value={userId}
              onChange={e => setUserId(e.target.value)}
              placeholder="Enter your user ID"
              autoComplete="username"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Enter your password"
              autoComplete="current-password"
              required
            />
          </div>
          {error && <div className="error-box">{error}</div>}
          <button type="submit" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
