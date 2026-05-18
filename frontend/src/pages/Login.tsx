import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { authApi } from '../lib/api'
import { useAuthStore } from '../store/authStore'
import { ArrowRight, Spinner, WarningCircle, Eye, EyeSlash, Copy, Check } from '@phosphor-icons/react'
import ThemeToggle from '../components/ThemeToggle'

export default function Login() {
  const [mode, setMode] = useState<'signin' | 'signup' | 'verify'>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [otp, setOtp] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [copied, setCopied] = useState(false)
  const setUser = useAuthStore((s) => s.setUser)
  const setTokens = useAuthStore((s) => s.setTokens)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (mode === 'signup') {
        await authApi.signUp(email, password, name || undefined)
        setError('')
        setMode('verify')
        return
      }
      if (mode === 'verify') {
        const res = await authApi.verifyOtp(email, password, otp)
        const data = res.data
        setUser({ user_id: data.user_id, email: data.email, name: data.name, email_verified: data.email_verified })
        setTokens(data.id_token, data.refresh_token)
        localStorage.setItem('id_token', data.id_token)
        localStorage.setItem('refresh_token', data.refresh_token)
        navigate('/chat')
        return
      }
      const res = await authApi.signIn(email, password)
      const data = res.data
      setUser({ user_id: data.user_id, email: data.email, name: data.name, email_verified: data.email_verified })
      setTokens(data.id_token, data.refresh_token)
      localStorage.setItem('id_token', data.id_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      navigate('/chat')
    } catch (err: any) {
      const detail = err.response?.data?.detail || 'Something went wrong'
      if (err.response?.status === 403 && detail.toLowerCase().includes('otp sent')) {
        setMode('verify')
      }
      setError(detail)
    } finally {
      setLoading(false)
    }
  }

  const handleResendOtp = async () => {
    setError('')
    setLoading(true)
    try {
      await authApi.resendVerification(email, password)
      setError('A new OTP has been sent. Check spam / junk if you do not see it.')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to resend OTP')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="min-h-[100dvh] flex font-sans relative overflow-hidden"
      style={{ background: 'var(--bg)', color: 'var(--text)' }}
    >
      {/* Left — editorial brand panel */}
      <div
        className="hidden lg:flex lg:w-1/2 relative flex-col justify-between p-12"
        style={{ borderRight: '1px solid var(--border)' }}
      >
        {/* Vertical tick rail (ref 2) */}
        <div className="absolute left-6 top-20 bottom-20 flex flex-col justify-between">
          {Array.from({ length: 7 }).map((_, i) => (
            <span
              key={i}
              className="block w-px h-5"
              style={{ background: i % 2 === 0 ? 'var(--accent)' : 'var(--border-strong)' }}
            />
          ))}
        </div>

        {/* Brand mark */}
        <div className="flex items-center gap-3 pl-12 relative z-10">
          <img
            src="/logo.jpeg"
            alt="SNTI"
            className="w-10 h-10 rounded-md object-cover"
          />
          <div className="leading-tight">
            <div className="font-display text-[22px] tracking-tight">snti<span className="mark">.</span></div>
            <div
              className="text-[10px] uppercase tracking-[0.22em] mt-0.5"
              style={{ color: 'var(--text-subtle)' }}
            >
              private · fast · yours
            </div>
          </div>
        </div>

        {/* Headline */}
        <div className="pl-12 relative z-10 space-y-8">
          <div className="flex items-center gap-3">
            <span className="h-px w-10" style={{ background: 'var(--accent)' }} />
            <span
              className="text-[11px] uppercase tracking-[0.22em]"
              style={{ color: 'var(--text-muted)' }}
            >
              a thoughtful assistant
            </span>
          </div>
          <h1
            className="font-display leading-[0.95] tracking-tight"
            style={{ fontSize: 'clamp(3rem, 6vw, 5rem)' }}
          >
            made for
            <br />
            <span className="mark">quiet</span> thinking
            <span style={{ color: 'var(--accent)' }}>.</span>
          </h1>
          <p
            className="max-w-md text-[14px] leading-relaxed"
            style={{ color: 'var(--text-muted)' }}
          >
            Conversations, images, and ideas — all in one measured,
            intentional interface. No noise, just signal.
          </p>
        </div>

        {/* Footer meta */}
        <div className="pl-12 flex items-end justify-between relative z-10">
          <div
            className="text-[10px] uppercase tracking-[0.22em]"
            style={{ color: 'var(--text-subtle)' }}
          >
            v1.0 · {new Date().getFullYear()}
          </div>
          <div className="flex gap-5 text-[10px] uppercase tracking-[0.22em]" style={{ color: 'var(--text-subtle)' }}>
            <span>ig</span><span>tw</span><span>in</span>
          </div>
        </div>
      </div>

      {/* Right — auth form */}
      <div className="flex-1 flex flex-col px-6 lg:px-16 py-8 relative">
        <div className="flex items-center justify-between">
          <div
            className="text-[10px] uppercase tracking-[0.22em] lg:hidden"
            style={{ color: 'var(--text-subtle)' }}
          >
            snti
          </div>
          <div className="ml-auto">
            <ThemeToggle compact />
          </div>
        </div>

        <div className="flex-1 flex items-center">
          <div className="w-full max-w-sm mx-auto">
            <div className="mb-10">
              <p
                className="text-[11px] uppercase tracking-[0.22em] mb-3"
                style={{ color: 'var(--accent)' }}
              >
                {mode === 'signin' ? '— welcome back' : mode === 'signup' ? '— new here' : '— verification'}
              </p>
              <h2 className="font-display text-4xl leading-[1.05] tracking-tight mb-3">
                {mode === 'signin' ? (
                  <>sign <span className="mark">in</span></>
                ) : mode === 'signup' ? (
                  <>create <span className="mark">account</span></>
                ) : (
                  <>verify <span className="mark">email</span></>
                )}
              </h2>
              <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
                {mode === 'signin'
                  ? 'Continue where you left off.'
                  : mode === 'signup'
                  ? 'A few seconds is all it takes.'
                  : `We sent a 6-digit code to ${email}. It may take a minute — check your spam / junk folder too.`}
              </p>
            </div>

            {error && (
              <div
                className="mb-5 flex items-start gap-2 p-3 rounded-lg text-[13px]"
                style={{
                  background: 'var(--danger-soft)',
                  color: 'var(--danger)',
                  border: '1px solid var(--danger)',
                }}
              >
                <WarningCircle size={16} weight="fill" className="mt-0.5 shrink-0" />
                <div className="flex-1">
                  <span>{error}</span>
                  {mode === 'verify' && (
                    <button
                      type="button"
                      onClick={handleResendOtp}
                      disabled={loading}
                      className="block mt-2 text-[11px] underline underline-offset-2"
                      style={{ color: 'var(--danger)' }}
                    >
                      {loading ? 'sending…' : 'resend OTP'}
                    </button>
                  )}
                </div>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-5">
              {mode === 'verify' ? (
                <div>
                  <label
                    className="block text-[10px] uppercase tracking-[0.22em] mb-2 text-center"
                    style={{ color: 'var(--text-subtle)' }}
                  >
                    enter 6-digit code
                  </label>
                  <div className="relative">
                    <input
                      type="text"
                      value={otp}
                      onChange={(e) => {
                        const val = e.target.value.replace(/[^0-9]/g, '').slice(0, 6)
                        setOtp(val)
                      }}
                      placeholder="• • • • • •"
                      required
                      maxLength={6}
                      className="input text-center font-display text-2xl tracking-[0.5em] !py-4 w-full pr-12"
                    />
                    {otp.length > 0 && (
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            await navigator.clipboard.writeText(otp)
                            setCopied(true)
                            setTimeout(() => setCopied(false), 1500)
                          } catch { /* ignore */ }
                        }}
                        className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded transition-colors"
                        style={{ color: copied ? 'var(--accent)' : 'var(--text-muted)' }}
                        aria-label="Copy OTP"
                        title="Copy OTP"
                      >
                        {copied ? <Check size={16} weight="bold" /> : <Copy size={16} />}
                      </button>
                    )}
                  </div>
                  <p className="mt-3 text-[11px] text-center" style={{ color: 'var(--text-subtle)' }}>
                    Didn&apos;t receive it? Check spam / promotions — or tap resend below.
                  </p>
                </div>
              ) : (
                <>
                  {mode === 'signup' && (
                    <div>
                      <label
                        className="block text-[10px] uppercase tracking-[0.22em] mb-2"
                        style={{ color: 'var(--text-subtle)' }}
                      >
                        name
                      </label>
                      <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="your name"
                        className="input"
                      />
                    </div>
                  )}
                  <div>
                    <label
                      className="block text-[10px] uppercase tracking-[0.22em] mb-2"
                      style={{ color: 'var(--text-subtle)' }}
                    >
                      email
                    </label>
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@example.com"
                      required
                      className="input"
                    />
                  </div>
                  <div>
                    <label
                      className="block text-[10px] uppercase tracking-[0.22em] mb-2"
                      style={{ color: 'var(--text-subtle)' }}
                    >
                      password
                    </label>
                    <div className="relative">
                      <input
                        type={showPassword ? 'text' : 'password'}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="min 6 characters"
                        required
                        minLength={6}
                        className="input w-full pr-10"
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword((v) => !v)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded"
                        style={{ color: 'var(--text-muted)' }}
                        aria-label={showPassword ? 'Hide password' : 'Show password'}
                      >
                        {showPassword ? <EyeSlash size={16} /> : <Eye size={16} />}
                      </button>
                    </div>
                    {mode === 'signin' && (
                      <div className="mt-2 text-right">
                        <Link
                          to="/forgot-password"
                          className="text-[11px] underline underline-offset-2"
                          style={{ color: 'var(--accent)' }}
                        >
                          forgot password?
                        </Link>
                      </div>
                    )}
                  </div>
                </>
              )}

              <button
                type="submit"
                disabled={loading}
                className="btn-primary w-full !py-3"
              >
                {loading ? (
                  <Spinner className="animate-spin" size={16} />
                ) : (
                  <>
                    {mode === 'signin' ? 'sign in' : mode === 'signup' ? 'create account' : 'verify OTP'}
                    <ArrowRight size={15} weight="bold" />
                  </>
                )}
              </button>
            </form>

            <div
              className="mt-8 text-[13px] text-center"
              style={{ color: 'var(--text-muted)' }}
            >
              {mode === 'signin' ? (
                <>
                  no account yet?{' '}
                  <button
                    onClick={() => setMode('signup')}
                    className="font-medium underline underline-offset-2"
                    style={{ color: 'var(--accent)' }}
                  >
                    create one
                  </button>
                </>
              ) : mode === 'signup' ? (
                <>
                  already here?{' '}
                  <button
                    onClick={() => setMode('signin')}
                    className="font-medium underline underline-offset-2"
                    style={{ color: 'var(--accent)' }}
                  >
                    sign in
                  </button>
                </>
              ) : (
                <>
                  wrong email?{' '}
                  <button
                    onClick={() => setMode('signin')}
                    className="font-medium underline underline-offset-2"
                    style={{ color: 'var(--accent)' }}
                  >
                    go back
                  </button>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Rule + number */}
        <div className="flex items-center justify-between mt-auto pt-6">
          <div className="rule flex-1" />
          <span
            className="ml-4 font-display text-[11px] tracking-[0.2em]"
            style={{ color: 'var(--text-subtle)' }}
          >
            01 / welcome
          </span>
        </div>
      </div>
    </div>
  )
}
