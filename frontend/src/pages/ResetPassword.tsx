import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { authApi } from '../lib/api'
import { ArrowLeft, Spinner, CheckCircle, WarningCircle } from '@phosphor-icons/react'

export default function ResetPassword() {
  const [searchParams] = useSearchParams()
  const oobCode = searchParams.get('oobCode') || ''

  const [email, setEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [verifying, setVerifying] = useState(true)
  const [done, setDone] = useState(false)
  const navigate = useNavigate()

  // Verify the oobCode on mount
  useEffect(() => {
    if (!oobCode) {
      setError('Invalid or missing reset link.')
      setVerifying(false)
      setLoading(false)
      return
    }
    authApi
      .verifyResetCode(oobCode)
      .then((res) => {
        setEmail(res.data.email)
        setVerifying(false)
        setLoading(false)
      })
      .catch((err: any) => {
        setError(err.response?.data?.detail || 'This reset link is invalid or has expired.')
        setVerifying(false)
        setLoading(false)
      })
  }, [oobCode])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await authApi.confirmReset(oobCode, newPassword)
      setDone(true)
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
                — create new password
              </p>
              <h2 className="font-display text-4xl leading-[1.05] tracking-tight mb-3">
                set a new <span className="mark">password</span>
              </h2>
              <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
                {done
                  ? 'Your password has been updated.'
                  : email
                    ? `For ${email}`
                    : verifying
                      ? 'Verifying your reset link...'
                      : 'Enter a strong new password below.'}
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

            {done ? (
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
                  <span>Password changed. You can now sign in.</span>
                </div>
                <button
                  onClick={() => navigate('/login')}
                  className="btn-primary w-full !py-3"
                >
                  go to sign in
                </button>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-5">
                <div>
                  <label
                    className="block text-[10px] uppercase tracking-[0.22em] mb-2"
                    style={{ color: 'var(--text-subtle)' }}
                  >
                    new password
                  </label>
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="min 6 characters"
                    required
                    minLength={6}
                    disabled={verifying}
                    className="input"
                  />
                </div>

                <button
                  type="submit"
                  disabled={loading || verifying}
                  className="btn-primary w-full !py-3"
                >
                  {loading ? (
                    <Spinner className="animate-spin" size={16} />
                  ) : (
                    <>save password</>
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
            03 / confirm
          </span>
        </div>
      </div>
    </div>
  )
}
