import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  ArrowRight,
  Search,
  Send,
  Handshake,
  TrendingUp,
  Target,
  MessageSquare,
  Sparkles,
  Play,
  Check,
  AlertCircle
} from 'lucide-react'

// ── Google Brand Icon ──────────────────────────────────────────────────────────
function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M17.64 9.20455C17.64 8.56636 17.5827 7.95273 17.4764 7.36364H9V10.845H13.8436C13.635 11.97 13.0009 12.9232 12.0477 13.5614V15.8195H14.9564C16.6582 14.2527 17.64 11.9455 17.64 9.20455Z" fill="#4285F4"/>
      <path d="M9 18C11.43 18 13.4673 17.1941 14.9564 15.8195L12.0477 13.5614C11.2418 14.1014 10.2109 14.4205 9 14.4205C6.65591 14.4205 4.67182 12.8373 3.96409 10.71H0.957275V13.0418C2.43818 15.9832 5.48182 18 9 18Z" fill="#34A853"/>
      <path d="M3.96409 10.71C3.78409 10.17 3.68182 9.59318 3.68182 9C3.68182 8.40682 3.78409 7.83 3.96409 7.29V4.95818H0.957275C0.347727 6.17318 0 7.54773 0 9C0 10.4523 0.347727 11.8268 0.957275 13.0418L3.96409 10.71Z" fill="#FBBC05"/>
      <path d="M9 3.57955C10.3214 3.57955 11.5077 4.03364 12.4405 4.92545L15.0218 2.34409C13.4632 0.891818 11.4259 0 9 0C5.48182 0 2.43818 2.01682 0.957275 4.95818L3.96409 7.29C4.67182 5.16273 6.65591 3.57955 9 3.57955Z" fill="#EA4335"/>
    </svg>
  )
}

// ── Microsoft Brand Icon ──────────────────────────────────────────────────────
function MicrosoftIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="0" y="0" width="8.5" height="8.5" fill="#F25022"/>
      <rect x="9.5" y="0" width="8.5" height="8.5" fill="#7FBA00"/>
      <rect x="0" y="9.5" width="8.5" height="8.5" fill="#00A4EF"/>
      <rect x="9.5" y="9.5" width="8.5" height="8.5" fill="#FFB900"/>
    </svg>
  )
}

// ── G2M Brand Monogram ────────────────────────────────────────────────────────
function G2MLogo() {
  return (
    <div className="flex items-center tracking-tight font-black select-none">
      <span className="text-[34px] leading-none text-[#1E1B4B]">G</span>
      <span className="text-[34px] leading-none italic font-black bg-gradient-to-r from-[#5B4EFF] to-[#8B5CF6] bg-clip-text text-transparent px-0.5 transform -skew-x-6">
        2
      </span>
      <span className="text-[34px] leading-none text-[#1E1B4B]">M</span>
    </div>
  )
}

export default function Login({ initialMode = 'login' }) {
  const { login, register, authError } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [mode, setMode] = useState(initialMode) // 'login' or 'signup'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const handleTabChange = (targetMode) => {
    setMode(targetMode)
    setError('')
    setNotice('')
  }

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setNotice('')
    setBusy(true)

    try {
      if (mode === 'login') {
        await login(email, password)
        navigate(location.state?.from || '/', { replace: true })
      } else {
        if (password !== confirmPassword) {
          setError('Passwords do not match')
          setBusy(false)
          return
        }
        await register(name, email, password, confirmPassword)
        navigate('/', { replace: true })
      }
    } catch (err) {
      setError(authError(err))
    } finally {
      setBusy(false)
    }
  }

  const handleSocialClick = (provider) => {
    setNotice(`Connecting to ${provider} Single Sign-On...`)
    setTimeout(() => {
      setNotice(`SSO with ${provider} is managed by your organization's directory. Please sign in with your enterprise email above.`)
    }, 1200)
  }

  const handleForgotPassword = () => {
    setNotice('Please contact your workspace administrator to reset or retrieve your account credentials.')
  }

  return (
    <div className="min-h-screen bg-[#F8F9FD] flex flex-col justify-between py-6 px-4 sm:px-6 lg:px-12 selection:bg-[#5B4EFF]/15">
      {/* ── Top Auxiliary Bar ────────────────────────────────────────────── */}
      <div className="w-full max-w-7xl mx-auto flex items-center justify-between text-xs text-gray-500 mb-4 sm:mb-6">
        <div className="hidden sm:block text-gray-400 font-medium">
          Seven agents. One connected GTM workspace.
        </div>
        <div className="ml-auto">
          <a
            href="mailto:support@forcecloudlabs.com"
            className="text-gray-500 hover:text-[#5B4EFF] font-medium transition-colors"
          >
            Need help?
          </a>
        </div>
      </div>

      {/* ── Main Two-Column Showcase + Auth Card ─────────────────────────── */}
      <div className="w-full max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12 items-center flex-1 my-auto">
        
        {/* ── LEFT SHOWCASE PANEL ───────────────────────────────────────── */}
        <div className="lg:col-span-7 bg-[#F4EFFD] border border-purple-100/80 rounded-[32px] p-8 sm:p-10 lg:p-12 relative overflow-hidden shadow-[0_10px_40px_rgba(91,78,255,0.04)] min-h-[640px] flex flex-col justify-between">
          
          {/* Subtle Organic Lavender Wavy Ribbon Illustration */}
          <svg
            className="absolute inset-0 w-full h-full pointer-events-none opacity-50"
            viewBox="0 0 650 750"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="M-40 460 C 140 450, 190 320, 310 330 C 430 340, 500 460, 660 410"
              stroke="url(#waveGrad1)"
              strokeWidth="96"
              strokeLinecap="round"
              fill="none"
            />
            <path
              d="M-20 620 C 130 610, 230 480, 370 510 C 490 540, 560 480, 660 450"
              stroke="url(#waveGrad2)"
              strokeWidth="48"
              strokeLinecap="round"
              fill="none"
            />
            <defs>
              <linearGradient id="waveGrad1" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#DDD3FB" />
                <stop offset="100%" stopColor="#C9B8FA" />
              </linearGradient>
              <linearGradient id="waveGrad2" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#E6DCFD" />
                <stop offset="100%" stopColor="#D5C5FB" />
              </linearGradient>
            </defs>
          </svg>

          {/* Top: Brand Logo + Headline */}
          <div className="relative z-10">
            <G2MLogo />
            
            <div className="mt-8 space-y-1">
              <h1 className="text-3xl sm:text-4xl lg:text-[42px] font-black text-[#151238] tracking-tight leading-[1.15]">
                A smarter team.
                <br />
                A stronger pipeline.
              </h1>
              <p className="text-sm sm:text-base text-gray-500 font-medium pt-2">
                Discover, engage and grow with connected AI agents.
              </p>
            </div>
          </div>

          {/* Middle: 7 Agent Floating Cards (Two Staggered Columns) */}
          <div className="relative z-10 my-8 grid grid-cols-1 sm:grid-cols-2 gap-3.5 sm:gap-4 items-start">
            
            {/* Column 1 (Left: 4 Cards) */}
            <div className="space-y-3.5">
              {/* Card 1: Prospect Intelligence */}
              <div className="bg-white rounded-2xl p-3.5 px-4 shadow-[0_4px_18px_rgba(30,27,75,0.05)] border border-white/80 flex items-center gap-3.5 transition-transform hover:-translate-y-0.5">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#ECE8FD] to-[#E0D7FA] flex items-center justify-center text-[#5B4EFF] shrink-0 shadow-sm">
                  <Search size={18} strokeWidth={2.4} />
                </div>
                <div>
                  <div className="text-[13px] font-bold text-[#1E1B4B] leading-tight">
                    Prospect Intelligence
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">
                    Find the right people
                  </div>
                </div>
              </div>

              {/* Card 2: Multi-Channel Outreach */}
              <div className="bg-white rounded-2xl p-3.5 px-4 shadow-[0_4px_18px_rgba(30,27,75,0.05)] border border-white/80 flex items-center gap-3.5 transition-transform hover:-translate-y-0.5">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#ECE8FD] to-[#E0D7FA] flex items-center justify-center text-[#5B4EFF] shrink-0 shadow-sm">
                  <Send size={18} strokeWidth={2.4} />
                </div>
                <div>
                  <div className="text-[13px] font-bold text-[#1E1B4B] leading-tight">
                    Multi-Channel Outreach
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">
                    Start relevant conversations
                  </div>
                </div>
              </div>

              {/* Card 3: Deal Intelligence */}
              <div className="bg-white rounded-2xl p-3.5 px-4 shadow-[0_4px_18px_rgba(30,27,75,0.05)] border border-white/80 flex items-center gap-3.5 transition-transform hover:-translate-y-0.5">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#ECE8FD] to-[#E0D7FA] flex items-center justify-center text-[#5B4EFF] shrink-0 shadow-sm">
                  <Handshake size={18} strokeWidth={2.4} />
                </div>
                <div>
                  <div className="text-[13px] font-bold text-[#1E1B4B] leading-tight">
                    Deal Intelligence
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">
                    Choose the next best action
                  </div>
                </div>
              </div>

              {/* Card 4: Predictive Revenue */}
              <div className="bg-white rounded-2xl p-3.5 px-4 shadow-[0_4px_18px_rgba(30,27,75,0.05)] border border-white/80 flex items-center gap-3.5 transition-transform hover:-translate-y-0.5">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#ECE8FD] to-[#E0D7FA] flex items-center justify-center text-[#5B4EFF] shrink-0 shadow-sm">
                  <TrendingUp size={18} strokeWidth={2.4} />
                </div>
                <div>
                  <div className="text-[13px] font-bold text-[#1E1B4B] leading-tight">
                    Predictive Revenue
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">
                    See what comes next
                  </div>
                </div>
              </div>
            </div>

            {/* Column 2 (Right: 3 Cards, Staggered Down) */}
            <div className="space-y-3.5 sm:mt-10">
              {/* Card 5: Signal Intelligence */}
              <div className="bg-white rounded-2xl p-3.5 px-4 shadow-[0_4px_18px_rgba(30,27,75,0.05)] border border-white/80 flex items-center gap-3.5 transition-transform hover:-translate-y-0.5">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#ECE8FD] to-[#E0D7FA] flex items-center justify-center text-[#5B4EFF] shrink-0 shadow-sm">
                  <Target size={18} strokeWidth={2.4} />
                </div>
                <div>
                  <div className="text-[13px] font-bold text-[#1E1B4B] leading-tight">
                    Signal Intelligence
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">
                    Spot buying intent
                  </div>
                </div>
              </div>

              {/* Card 6: Conversation Intelligence */}
              <div className="bg-white rounded-2xl p-3.5 px-4 shadow-[0_4px_18px_rgba(30,27,75,0.05)] border border-white/80 flex items-center gap-3.5 transition-transform hover:-translate-y-0.5">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#ECE8FD] to-[#E0D7FA] flex items-center justify-center text-[#5B4EFF] shrink-0 shadow-sm">
                  <MessageSquare size={18} strokeWidth={2.4} />
                </div>
                <div>
                  <div className="text-[13px] font-bold text-[#1E1B4B] leading-tight">
                    Conversation Intelligence
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">
                    Keep every reply in context
                  </div>
                </div>
              </div>

              {/* Card 7: Content Intelligence */}
              <div className="bg-white rounded-2xl p-3.5 px-4 shadow-[0_4px_18px_rgba(30,27,75,0.05)] border border-white/80 flex items-center gap-3.5 transition-transform hover:-translate-y-0.5">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#ECE8FD] to-[#E0D7FA] flex items-center justify-center text-[#5B4EFF] shrink-0 shadow-sm">
                  <Sparkles size={18} strokeWidth={2.4} />
                </div>
                <div>
                  <div className="text-[13px] font-bold text-[#1E1B4B] leading-tight">
                    Content Intelligence
                  </div>
                  <div className="text-[11px] text-gray-500 mt-0.5">
                    Create with context
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Bottom Copyright */}
          <div className="relative z-10 text-right text-[11px] text-gray-400 font-medium">
            © 2026 All Rights Reserved
          </div>
        </div>

        {/* ── RIGHT AUTHENTICATION CARD ─────────────────────────────────── */}
        <div className="lg:col-span-5 flex flex-col items-center">
          <div className="w-full max-w-[430px] bg-white rounded-[26px] p-7 sm:p-9 shadow-[0_12px_36px_rgba(30,27,75,0.04)] border border-gray-100">
            
            {/* Header / Eyebrow */}
            <div className="text-[11px] font-bold tracking-wider uppercase text-gray-400 mb-1.5">
              WORKSPACE ACCESS
            </div>
            <h2 className="text-2xl sm:text-3xl font-extrabold text-[#111827] tracking-tight">
              {mode === 'login' ? 'Welcome back' : 'Create account'}
            </h2>
            <p className="text-xs sm:text-sm text-gray-500 mt-1 mb-6">
              {mode === 'login'
                ? 'Sign in to your connected GTM workspace.'
                : 'Start running multi-agent GTM motions in minutes.'}
            </p>

            {/* Segmented Pill Switcher [ Log in | Sign up ] */}
            <div className="bg-[#F1F3F9] p-1 rounded-xl flex items-center gap-1 mb-6">
              <button
                type="button"
                onClick={() => handleTabChange('login')}
                className={`flex-1 py-2 rounded-lg text-xs sm:text-sm font-semibold transition-all ${
                  mode === 'login'
                    ? 'bg-[#5B4EFF] text-white shadow-sm'
                    : 'text-gray-600 hover:text-gray-900 font-medium'
                }`}
              >
                Log in
              </button>
              <button
                type="button"
                onClick={() => handleTabChange('signup')}
                className={`flex-1 py-2 rounded-lg text-xs sm:text-sm font-semibold transition-all ${
                  mode === 'signup'
                    ? 'bg-[#5B4EFF] text-white shadow-sm'
                    : 'text-gray-600 hover:text-gray-900 font-medium'
                }`}
              >
                Sign up
              </button>
            </div>

            {/* Error Notification */}
            {error && (
              <div className="mb-4 rounded-xl px-3.5 py-2.5 text-xs bg-red-50 text-red-600 border border-red-200/80 flex items-start gap-2">
                <AlertCircle size={15} className="shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            {/* Info Notice */}
            {notice && (
              <div className="mb-4 rounded-xl px-3.5 py-2.5 text-xs bg-blue-50 text-blue-700 border border-blue-200/80">
                {notice}
              </div>
            )}

            {/* Form */}
            <form onSubmit={onSubmit} className="space-y-4">
              {mode === 'signup' && (
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                    Full name
                  </label>
                  <input
                    type="text"
                    required
                    autoComplete="name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="w-full rounded-xl border border-gray-200 px-3.5 py-2.5 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/25 focus:border-[#5B4EFF] transition-all bg-white"
                    placeholder="Jane Smith"
                  />
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                  Email address
                </label>
                <input
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded-xl border border-gray-200 px-3.5 py-2.5 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/25 focus:border-[#5B4EFF] transition-all bg-white"
                  placeholder="you@company.com"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                  Password
                </label>
                <input
                  type="password"
                  required
                  minLength={mode === 'signup' ? 8 : undefined}
                  autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-xl border border-gray-200 px-3.5 py-2.5 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/25 focus:border-[#5B4EFF] transition-all bg-white"
                  placeholder="••••••••••••"
                />
              </div>

              {mode === 'signup' && (
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                    Confirm password
                  </label>
                  <input
                    type="password"
                    required
                    minLength={8}
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="w-full rounded-xl border border-gray-200 px-3.5 py-2.5 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/25 focus:border-[#5B4EFF] transition-all bg-white"
                    placeholder="Repeat password"
                  />
                </div>
              )}

              {/* Login Options Row */}
              {mode === 'login' && (
                <div className="flex items-center justify-between text-xs pt-0.5">
                  <label className="flex items-center gap-2 text-gray-600 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={rememberMe}
                      onChange={(e) => setRememberMe(e.target.checked)}
                      className="w-4 h-4 rounded border-gray-300 text-[#5B4EFF] focus:ring-[#5B4EFF] transition-colors"
                    />
                    <span>Remember me</span>
                  </label>
                  <button
                    type="button"
                    onClick={handleForgotPassword}
                    className="text-[#5B4EFF] hover:underline font-medium"
                  >
                    Forgot password?
                  </button>
                </div>
              )}

              {/* Primary Action Button */}
              <button
                type="submit"
                disabled={busy}
                className="w-full py-3 px-4 rounded-xl font-semibold text-sm text-white bg-[#5B4EFF] hover:bg-[#4C3FF0] active:scale-[0.99] shadow-[0_4px_14px_rgba(91,78,255,0.3)] hover:shadow-[0_6px_20px_rgba(91,78,255,0.4)] transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60 mt-2"
              >
                <span>{busy ? (mode === 'login' ? 'Signing in…' : 'Creating account…') : (mode === 'login' ? 'Log in' : 'Create account')}</span>
                <ArrowRight size={16} />
              </button>
            </form>

            {/* Divider */}
            <div className="relative my-6 text-center">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-gray-200" />
              </div>
              <span className="relative px-3 bg-white text-[11px] text-gray-400 font-medium uppercase tracking-wider">
                or continue with
              </span>
            </div>

            {/* Social Authentication Buttons */}
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => handleSocialClick('Google')}
                className="w-full border border-gray-200 rounded-xl py-2.5 px-3 flex items-center justify-center gap-2 hover:bg-gray-50/80 transition-colors text-xs font-semibold text-gray-700 cursor-pointer shadow-sm"
              >
                <GoogleIcon />
                <span>Google</span>
              </button>

              <button
                type="button"
                onClick={() => handleSocialClick('Microsoft')}
                className="w-full border border-gray-200 rounded-xl py-2.5 px-3 flex items-center justify-center gap-2 hover:bg-gray-50/80 transition-colors text-xs font-semibold text-gray-700 cursor-pointer shadow-sm"
              >
                <MicrosoftIcon />
                <span>Microsoft</span>
              </button>
            </div>

            {/* Footer Notice */}
            <div className="text-[11px] text-gray-400 text-center mt-5 leading-relaxed">
              By continuing, you agree to our Terms and Privacy Policy.
            </div>
          </div>

          {/* Product Walkthrough Link Below Card */}
          <a
            href="https://www.youtube.com"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-medium text-[#5B4EFF] hover:underline flex items-center justify-center gap-1.5 mt-5 transition-colors cursor-pointer"
          >
            <Play size={12} className="fill-[#5B4EFF]" />
            <span>Watch the product walkthrough</span>
          </a>
        </div>
      </div>

      {/* Spacer */}
      <div className="h-2" />
    </div>
  )
}
