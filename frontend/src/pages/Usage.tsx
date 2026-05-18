import { useEffect, useState } from 'react'
import { usageApi } from '../lib/api'
import { ChartPieSlice, Database, Brain } from '@phosphor-icons/react'

interface UsageData {
  storage: {
    used_bytes: number
    quota_bytes: number
    used_mb: number
    quota_mb: number
  }
  limits: {
    deep_research_remaining: number
  }
}

export default function Usage() {
  const [data, setData] = useState<UsageData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    usageApi.getUsage()
      .then((res) => setData(res.data))
      .catch((e) => setError(e.response?.data?.detail || 'Failed to load usage.'))
      .finally(() => setLoading(false))
  }, [])

  const storagePct = data
    ? Math.min(100, Math.round((data.storage.used_bytes / data.storage.quota_bytes) * 100))
    : 0

  return (
    <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">
      <div className="flex items-center gap-3">
        <ChartPieSlice size={22} weight="duotone" style={{ color: 'var(--accent)' }} />
        <h1 className="font-display text-[22px] tracking-tight" style={{ color: 'var(--text)' }}>
          Usage Dashboard
        </h1>
      </div>

      {loading && (
        <div className="text-[13px]" style={{ color: 'var(--text-subtle)' }}>Loading…</div>
      )}
      {error && (
        <div className="rounded-lg p-3 text-[13px]" style={{ background: 'var(--danger-soft)', color: 'var(--danger)' }}>
          {error}
        </div>
      )}

      {!loading && data && (
        <div className="space-y-4">
          {/* Storage */}
          <div
            className="rounded-xl p-5 space-y-3"
            style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}
          >
            <div className="flex items-center gap-2">
              <Database size={18} style={{ color: 'var(--accent)' }} />
              <span className="text-[14px] font-medium" style={{ color: 'var(--text)' }}>
                Storage
              </span>
              <span className="ml-auto text-[12px]" style={{ color: 'var(--text-subtle)' }}>
                {data.storage.used_mb} / {data.storage.quota_mb} MB
              </span>
            </div>
            <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--border-strong)' }}>
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${storagePct}%`,
                  background: storagePct > 90 ? 'var(--danger)' : 'var(--accent)',
                }}
              />
            </div>
            <p className="text-[11px]" style={{ color: 'var(--text-subtle)' }}>
              {storagePct}% used — {data.storage.quota_mb - data.storage.used_mb} MB remaining
            </p>
          </div>

          {/* Limits */}
          <div
            className="rounded-xl p-5 space-y-2"
            style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)' }}
          >
            <div className="flex items-center gap-2">
              <Brain size={18} style={{ color: 'var(--accent)' }} />
              <span className="text-[14px] font-medium" style={{ color: 'var(--text)' }}>
                Deep Research
              </span>
              <span
                className="ml-auto text-[12px] font-semibold px-2 py-0.5 rounded-full"
                style={{
                  background: 'var(--accent-soft)',
                  color: 'var(--accent)',
                }}
              >
                {data.limits.deep_research_remaining} / 5 left this week
              </span>
            </div>
            <p className="text-[11px]" style={{ color: 'var(--text-subtle)' }}>
              Resets every Monday at 00:00 UTC.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
