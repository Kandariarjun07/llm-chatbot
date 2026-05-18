import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../lib/api'
import { ArrowLeft, Spinner, CheckCircle, WarningCircle } from '@phosphor-icons/react'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await authApi.forgotPassword(email)
      setSent(true)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="min-h-[100dvh] flex font-sans"
      style={{ background: 'var(--bg)', color: 'var(--text)' }}
    >
      <div className="flex-1 flex flex-col px-6 lg:px-16 py-8">
        <div className="flex items-center justify-between">
          <button
            onClick={() => navigate('/login')}
            className="flex items-center gap-2 text-[12px] uppercase tracking-[0.22em]"
            style={{ color: 'var(--text-subtle)' }}
          >
            <ArrowLeft size={14} />
            back
          </button>
        </div>

        <div className="flex-1 flex items-center">
          <div className="w-full max-w-sm mx-auto">
            <div className="mb-10">
              <p
                className="text-[11px] uppercase tracking-[0.22em] mb-3"
                style={{ color: 'var(--accent)' }}
              >
                — reset password
              </p>
              <h2 className="font-display text-4xl leading-[1.05] tracking-tight mb-3">
                forgot your <span className="mark">password</span>?
              </h2>
              <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
                {sent
                  ? 'Check your inbox for a reset link from Firebase.'
                  : "Enter your email and we'll send you a reset link."}
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
                <span>{error}</span>
              </div>
            )}

            {sent ? (
              <div className="space-y-5">
                <div
                  className="flex items-center gap-3 p-4 rounded-lg text-[13px]"
                  style={{
                    background: 'var(--success-soft)',
                    color: 'var(--success)',
                    border: '1px solid var(--success)',
                  }}
                >
                  <CheckCircle size={18} weight="fill" className="shrink-0" />
                  <span>Reset link sent. Check your email.</span>
                </div>
                <button
                  onClick={() => navigate('/login')}
                  className="btn-primary w-full !py-3"
                >
                  back to sign in
                </button>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-5">
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

                <button type="submit" disabled={loading} className="btn-primary w-full !py-3">
                  {loading ? (
                    <Spinner className="animate-spin" size={16} />
                  ) : (
                    <>send reset link</>
                  )}
                </button>
              </form>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between mt-auto pt-6">
          <div className="rule flex-1" />
          <span
            className="ml-4 font-display text-[11px] tracking-[0.2em]"
            style={{ color: 'var(--text-subtle)' }}
          >
            02 / reset
          </span>
        </div>
      </div>
    </div>
  )
}
