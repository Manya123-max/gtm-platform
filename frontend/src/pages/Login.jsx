import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

function ForceLogo() {
  return (
    <svg width="40" height="40" viewBox="0 0 30 30" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="30" height="30" rx="8" fill="url(#gradLogin)" />
      <path d="M16.5 7.5L12 16h5L14 22.5l7.5-10.5H17L16.5 7.5z" fill="white" fillOpacity="0.95" />
      <defs>
        <linearGradient id="gradLogin" x1="0" y1="0" x2="30" y2="30" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#0A67FF" />
          <stop offset="100%" stopColor="#00C8FF" />
        </linearGradient>
      </defs>
    </svg>
  )
}

export default function Login() {
  const { login, authError } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await login(email, password)
      navigate(location.state?.from || '/', { replace: true })
    } catch (err) {
      setError(authError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="flex min-h-screen items-center justify-center px-4"
      style={{ background: 'var(--c-bg)' }}
    >
      <div
        className="w-full max-w-sm rounded-2xl p-8"
        style={{
          background: 'var(--c-surface)',
          border: '1px solid var(--c-border)',
        }}
      >
        <div className="flex flex-col items-center gap-2 mb-6">
          <ForceLogo />
          <div
            className="text-lg font-bold"
            style={{
              background: 'linear-gradient(90deg, #0A67FF, #00C8FF)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            4CECloud Labs GTM
          </div>
          <div className="text-xs" style={{ color: 'var(--c-text3)' }}>
            Sign in to your GTM workspace
          </div>
        </div>

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--c-text2)' }}>
              Email
            </label>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              className="w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500/40"
              style={{
                background: 'var(--c-surface2)',
                border: '1px solid var(--c-border)',
                color: 'var(--c-text)',
              }}
              placeholder="you@company.com"
            />
          </div>

          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--c-text2)' }}>
              Password
            </label>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500/40"
              style={{
                background: 'var(--c-surface2)',
                border: '1px solid var(--c-border)',
                color: 'var(--c-text)',
              }}
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div
              className="rounded-lg px-3 py-2 text-xs"
              style={{ background: 'rgba(239,68,68,0.1)', color: '#EF4444', border: '1px solid rgba(239,68,68,0.3)' }}
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg py-2 text-sm font-semibold text-white transition-opacity disabled:opacity-50"
            style={{ background: 'linear-gradient(90deg, #0A67FF, #00C8FF)' }}
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <div className="mt-5 text-center text-xs" style={{ color: 'var(--c-text3)' }}>
          Don&apos;t have an account?{' '}
          <Link to="/register" className="font-medium" style={{ color: '#00C8FF' }}>
            Create one
          </Link>
        </div>
      </div>
    </div>
  )
}
