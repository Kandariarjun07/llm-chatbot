import { useState, useCallback } from 'react'
import { imagesApi } from '../lib/api'
import {
  ImageSquare,
  Spinner,
  DownloadSimple,
  ArrowsClockwise,
  Sparkle,
  Trash,
  WarningCircle,
} from '@phosphor-icons/react'

const MODELS = [
  { id: 'flux', label: 'Flux', desc: 'Balanced default' },
  { id: 'zimage', label: 'Zimage', desc: 'Custom model' },
  { id: 'klein', label: 'Klein', desc: 'Custom model' },
]

const RATIOS = [
  { id: 'square', label: '1:1', w: 1024, h: 1024 },
  { id: 'landscape', label: '16:9', w: 1280, h: 720 },
  { id: 'portrait', label: '9:16', w: 720, h: 1280 },
  { id: 'wide', label: '21:9', w: 1536, h: 640 },
]

const SUGGESTIONS = [
  'A cyberpunk alley at dusk, neon reflecting in rain puddles.',
  'A lone mountain cabin at golden hour, warm window glow.',
  'Abstract geometric composition in bronze and ivory tones.',
  'Portrait of a futurist architect, studio lighting, editorial.',
]

interface GeneratedImage {
  url: string
  blob: Blob
  model: string
  seed: number
  prompt: string
  timestamp: number
}

export default function Images() {
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState('flux')
  const [ratio, setRatio] = useState('square')
  const [seed, setSeed] = useState(() => Math.floor(Math.random() * 10000))
  const [generating, setGenerating] = useState(false)
  const [current, setCurrent] = useState<GeneratedImage | null>(null)
  const [history, setHistory] = useState<GeneratedImage[]>(() => {
    const saved = localStorage.getItem('image_history')
    return saved ? JSON.parse(saved) : []
  })
  const [error, setError] = useState('')

  const generate = useCallback(async () => {
    if (!prompt.trim() || generating) return
    setGenerating(true)
    setError('')
    const r = RATIOS.find((x) => x.id === ratio) || RATIOS[0]

    try {
      const res = await imagesApi.generate({
        prompt: prompt.trim(),
        model,
        width: r.w,
        height: r.h,
        seed,
      })
      const img: GeneratedImage = {
        url: res.url,
        blob: res.blob,
        model: res.model,
        seed: res.seed,
        prompt: prompt.trim(),
        timestamp: Date.now(),
      }
      setCurrent(img)
      setHistory((prev) => {
        const next = [img, ...prev]
        localStorage.setItem('image_history', JSON.stringify(next))
        return next
      })
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to generate image')
    } finally {
      setGenerating(false)
    }
  }, [prompt, model, ratio, seed, generating])

  const reroll = () => {
    setSeed(Math.floor(Math.random() * 10000))
    generate()
  }

  const download = (img: GeneratedImage) => {
    const a = document.createElement('a')
    a.href = img.url
    a.download = `snti_${img.model}_${img.seed}.png`
    a.click()
  }

  const clearHistory = () => {
    setHistory([])
    setCurrent(null)
    localStorage.removeItem('image_history')
  }

  const selectedRatio = RATIOS.find((r) => r.id === ratio) || RATIOS[0]
  const labelCls = 'block text-[10px] uppercase tracking-[0.22em] mb-2'
  const labelStyle: React.CSSProperties = { color: 'var(--text-subtle)' }

  return (
    <div className="flex flex-col h-full">
      <div className="max-w-4xl mx-auto w-full px-6 py-8 space-y-6">
        {/* Header */}
        <div>
          <p
            className="text-[11px] uppercase tracking-[0.22em] mb-3"
            style={{ color: 'var(--accent)' }}
          >
            — image generation
          </p>
          <h1 className="font-display text-5xl leading-[1.02] tracking-tight">
            compose with <span className="mark">light</span>.
          </h1>
        </div>

        {/* Controls */}
        <div
          className="rounded-2xl p-6 space-y-6"
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
          }}
        >
          <div>
            <label className={labelCls} style={labelStyle}>prompt</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe the image you want to generate..."
              rows={3}
              className="input resize-none"
            />
            <div className="flex flex-wrap gap-2 mt-3">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => setPrompt(s)}
                  className="px-3 py-1.5 rounded-full text-[11px] transition-colors"
                  style={{
                    background: 'transparent',
                    color: 'var(--text-muted)',
                    border: '1px solid var(--border-strong)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = 'var(--accent)'
                    e.currentTarget.style.color = 'var(--accent)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'var(--border-strong)'
                    e.currentTarget.style.color = 'var(--text-muted)'
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className={labelCls} style={labelStyle}>model</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="input !py-2.5"
              >
                {MODELS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls} style={labelStyle}>aspect</label>
              <select
                value={ratio}
                onChange={(e) => setRatio(e.target.value)}
                className="input !py-2.5"
              >
                {RATIOS.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls} style={labelStyle}>seed</label>
              <div className="flex gap-2">
                <input
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(Number(e.target.value))}
                  className="input !py-2.5"
                />
                <button
                  onClick={() => setSeed(Math.floor(Math.random() * 10000))}
                  className="p-2.5 rounded-xl transition-colors shrink-0"
                  style={{
                    background: 'transparent',
                    color: 'var(--text-muted)',
                    border: '1px solid var(--border-strong)',
                  }}
                  title="Random seed"
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = 'var(--accent)'
                    e.currentTarget.style.borderColor = 'var(--accent)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = 'var(--text-muted)'
                    e.currentTarget.style.borderColor = 'var(--border-strong)'
                  }}
                >
                  <ArrowsClockwise size={16} />
                </button>
              </div>
            </div>
          </div>

          {error && (
            <div
              className="flex items-start gap-2 p-3 rounded-lg text-[13px]"
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

          <div className="flex gap-3">
            <button
              onClick={generate}
              disabled={generating || !prompt.trim()}
              className="btn-primary flex-1"
            >
              {generating ? (
                <Spinner className="animate-spin" size={16} />
              ) : (
                <Sparkle size={15} weight="fill" />
              )}
              {generating ? 'generating…' : 'generate'}
            </button>
            {current && (
              <button
                onClick={reroll}
                disabled={generating}
                className="btn-secondary"
              >
                <ArrowsClockwise size={15} />
                reroll
              </button>
            )}
          </div>
        </div>

        {/* Result */}
        {current && (
          <div
            className="rounded-2xl p-5 space-y-4"
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
            }}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p
                  className="text-[11px] uppercase tracking-[0.22em]"
                  style={{ color: 'var(--text-subtle)' }}
                >
                  prompt
                </p>
                <p
                  className="font-display text-xl leading-snug tracking-tight mt-1 break-words"
                  style={{ color: 'var(--text)' }}
                >
                  {current.prompt}
                </p>
                <p
                  className="text-[11px] mt-2"
                  style={{ color: 'var(--text-muted)' }}
                >
                  {current.model} · {selectedRatio.label} · seed {current.seed}
                </p>
              </div>
              <button
                onClick={() => download(current)}
                className="p-2 rounded-lg shrink-0 transition-colors"
                style={{
                  background: 'transparent',
                  color: 'var(--text-muted)',
                  border: '1px solid var(--border-strong)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = 'var(--accent)'
                  e.currentTarget.style.borderColor = 'var(--accent)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = 'var(--text-muted)'
                  e.currentTarget.style.borderColor = 'var(--border-strong)'
                }}
                aria-label="Download image"
              >
                <DownloadSimple size={16} />
              </button>
            </div>
            <img
              src={current.url}
              alt={current.prompt}
              className="w-full rounded-xl"
              style={{
                border: '1px solid var(--border)',
                maxHeight: '60vh',
                objectFit: 'contain',
                background: 'var(--bg-sunken)',
              }}
            />
          </div>
        )}

        {/* History */}
        {history.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <p
                className="text-[10px] uppercase tracking-[0.22em]"
                style={{ color: 'var(--text-subtle)' }}
              >
                history · {history.length}
              </p>
              <button
                onClick={clearHistory}
                className="flex items-center gap-1.5 text-[11px] transition-colors"
                style={{ color: 'var(--danger)' }}
              >
                <Trash size={12} />
                clear
              </button>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
              {history.map((img, i) => (
                <button
                  key={i}
                  onClick={() => setCurrent(img)}
                  className="relative group rounded-xl overflow-hidden transition-colors"
                  style={{ border: '1px solid var(--border)' }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent)' }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)' }}
                >
                  <img
                    src={img.url}
                    alt={img.prompt}
                    className="w-full aspect-square object-cover"
                    onError={(e) => {
                      // URL may be revoked after reload — hide gracefully
                      ;(e.currentTarget as HTMLImageElement).style.opacity = '0.15'
                    }}
                  />
                  <div
                    className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-2"
                    style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.75), transparent)' }}
                  >
                    <p className="text-[11px] line-clamp-2 text-left" style={{ color: '#fff' }}>
                      {img.prompt}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Empty state when nothing generated */}
        {!current && history.length === 0 && (
          <div
            className="rounded-2xl p-10 text-center"
            style={{
              background: 'var(--bg-card)',
              border: '1px dashed var(--border-strong)',
            }}
          >
            <ImageSquare size={28} style={{ color: 'var(--accent)' }} className="mx-auto mb-3" />
            <p className="font-display text-2xl tracking-tight mb-1">
              nothing here <span className="mark">yet</span>.
            </p>
            <p className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
              Write a prompt above and press generate.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
