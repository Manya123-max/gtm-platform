import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

function ForceLogo() {
  return (
    <svg width="40" height="40" viewBox="0 0 30 30" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="30" height="30" rx="8" fill="url(#gradReg)" />
      <path d="M16.5 7.5L12 16h5L14 22.5l7.5-10.5H17L16.5 7.5z" fill="white" fillOpacity="0.95" />
      <defs>
        <linearGradient id="gradReg" x1="0" y1="0" x2="30" y2="30" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#0A67FF" />
          <stop offset="100%" stopColor="#00C8FF" />
        </linearGradient>
      </defs>
    </svg>
  )
}

const inputStyle = {
  background: 'var(--c-surface2)',
  border: '1px solid var(--c-border)',
  color: 'var(--c-text)',
}

export default function Register() {
  const { register, authError } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ name: '', email: '', password: '', confirm: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (key) => (e) => setForm(f => ({ ...f, [key]: e.target.value }))

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (form.password !== form.confirm) {
      setError('Passwords do not match')
      return
    }
    setBusy(true)
    try {
      await register(form.name, form.email, form.password, form.confirm)
      navigate('/', { replace: true })
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
        style={{ background: 'var(--c-surface)', border: '1px solid var(--c-border)' }}
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
            Create your account
          </div>
          <div className="text-xs" style={{ color: 'var(--c-text3)' }}>
            Start running GTM motions in minutes
          </div>
        </div>

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--c-text2)' }}>
              Name
            </label>
            <input
              type="text"
              required
              autoComplete="name"
              value={form.name}
              onChange={set('name')}
              className="w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500/40"
              style={inputStyle}
              placeholder="Jane Smith"
            />
          </div>

          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--c-text2)' }}>
              Email
            </label>
            <input
              type="email"
              required
              autoComplete="email"
              value={form.email}
              onChange={set('email')}
              className="w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500/40"
              style={inputStyle}
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
              minLength={8}
              autoComplete="new-password"
              value={form.password}
              onChange={set('password')}
              className="w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500/40"
              style={inputStyle}
              placeholder="At least 8 characters, 1 letter + 1 number"
            />
          </div>

          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--c-text2)' }}>
              Confirm Password
            </label>
            <input
              type="password"
              required
              autoComplete="new-password"
              value={form.confirm}
              onChange={set('confirm')}
              className="w-full rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500/40"
              style={inputStyle}
              placeholder="Repeat password"
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
            {busy ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <div className="mt-5 text-center text-xs" style={{ color: 'var(--c-text3)' }}>
          Already have an account?{' '}
          <Link to="/login" className="font-medium" style={{ color: '#00C8FF' }}>
            Sign in
          </Link>
        </div>
      </div>
    </div>
  )
}
