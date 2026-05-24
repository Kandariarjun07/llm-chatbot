import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowRight,
  BookmarkSimple,
  DownloadSimple,
  FileCsv,
  Image as ImageIcon,
  FileXls,
  Lightning,
  Spinner,
  Sparkle,
  Table,
  Trash,
  UploadSimple,
  WarningCircle,
  X,
} from '@phosphor-icons/react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  ScatterChart,
  Scatter,
  Legend,
  AreaChart,
  Area,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
} from 'recharts'
import {
  sheetsApi,
  type SheetMeta,
  type SheetQueryResponse,
} from '../lib/api'

const SAVED_KEY = 'snti:sheets:saved-queries'

interface SavedQuery {
  id: string
  question: string
  modelChoice: string
  createdAt: number
}

type ModelChoice = 'Fast' | 'Think'

export default function Sheets() {
  const [sheet, setSheet] = useState<SheetMeta | null>(null)
  const [loadingMeta, setLoadingMeta] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')

  const [question, setQuestion] = useState('')
  const [modelChoice, setModelChoice] = useState<ModelChoice>('Fast')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<SheetQueryResponse | null>(null)
  const [runError, setRunError] = useState('')

  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [csvExporting, setCsvExporting] = useState(false)
  const [csvExportError, setCsvExportError] = useState('')

  const [savedQueries, setSavedQueries] = useState<SavedQuery[]>([])
  const [showSaved, setShowSaved] = useState(false)

  const [schemaOpen, setSchemaOpen] = useState(false)
  const [sampleOpen, setSampleOpen] = useState(false)
  const [sqlOpen, setSqlOpen] = useState(false)

  const [suggestions, setSuggestions] = useState<string[]>([])
  const [loadingSuggestions, setLoadingSuggestions] = useState(false)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  const fetchSuggestions = useCallback(async () => {
    setLoadingSuggestions(true)
    try {
      const res = await sheetsApi.suggestions()
      setSuggestions(res.data?.suggestions ?? [])
    } catch {
      setSuggestions([])
    } finally {
      setLoadingSuggestions(false)
    }
  }, [])

  // ── load current sheet on mount ────────────────────────────────
  useEffect(() => {
    let cancelled = false
    sheetsApi
      .current()
      .then((res) => {
        if (cancelled) return
        setSheet(res.data ?? null)
        if (res.data) fetchSuggestions()
      })
      .catch(() => {
        if (cancelled) return
        setSheet(null)
      })
      .finally(() => {
        if (cancelled) return
        setLoadingMeta(false)
      })
    return () => {
      cancelled = true
    }
  }, [fetchSuggestions])

  // auto-resize textarea
  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 180) + 'px'
  }, [question])

  // load saved queries
  useEffect(() => {
    try {
      const raw = localStorage.getItem(SAVED_KEY)
      if (raw) setSavedQueries(JSON.parse(raw))
    } catch { /* ignore */ }
  }, [])

  const persistSaved = (next: SavedQuery[]) => {
    setSavedQueries(next)
    try { localStorage.setItem(SAVED_KEY, JSON.stringify(next)) } catch { /* ignore */ }
  }

  // ── handlers ───────────────────────────────────────────────────
  const handleFile = useCallback(async (file: File) => {
    setUploadError('')
    setUploading(true)
    setResult(null)
    try {
      const res = await sheetsApi.upload(file)
      setSheet(res.data)
      setSchemaOpen(true)
      fetchSuggestions()
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string }
      setUploadError(e.response?.data?.detail || e.message || 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }, [])

  const handleRun = useCallback(async () => {
    const q = question.trim()
    if (!q || running) return
    setRunError('')
    setExportError('')
    setRunning(true)
    setResult(null)
    try {
      const res = await sheetsApi.query(q, modelChoice)
      setResult(res.data)
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string }
      setRunError(e.response?.data?.detail || e.message || 'Query failed.')
    } finally {
      setRunning(false)
    }
  }, [question, modelChoice, running])

  const handleExport = useCallback(async () => {
    if (!result || exporting) return
    setExportError('')
    setExporting(true)
    try {
      // Re-use the exact SQL the user just inspected — no second LLM call.
      const out = await sheetsApi.exportXlsx({ sql: result.sql })
      const source = (sheet?.filename || 'result').replace(/\.[^.]+$/, '')
      const downloadName = `${source}_filtered.xlsx`

      const a = document.createElement('a')
      a.href = out.url
      a.download = downloadName
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      // Revoke object URL on the next tick so the browser has finished
      // initiating the download.
      setTimeout(() => URL.revokeObjectURL(out.url), 1000)
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string }
      setExportError(e.response?.data?.detail || e.message || 'Export failed.')
    } finally {
      setExporting(false)
    }
  }, [result, sheet, exporting])

  const handleDelete = useCallback(async () => {
    if (!confirm('Remove the current spreadsheet from the server?')) return
    try {
      await sheetsApi.delete()
    } catch {
      // best-effort
    }
    setSheet(null)
    setResult(null)
    setQuestion('')
  }, [])

  const handleSaveQuery = useCallback(() => {
    const q = question.trim()
    if (!q) return
    const next: SavedQuery = {
      id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      question: q,
      modelChoice,
      createdAt: Date.now(),
    }
    persistSaved([next, ...savedQueries].slice(0, 20))
  }, [question, modelChoice, savedQueries])

  const handleDeleteSaved = useCallback((id: string) => {
    persistSaved(savedQueries.filter((s) => s.id !== id))
  }, [savedQueries])

  const handleLoadSaved = useCallback((sq: SavedQuery) => {
    setQuestion(sq.question)
    setModelChoice(sq.modelChoice as ModelChoice)
    setShowSaved(false)
  }, [])

  const handleCsvExport = useCallback(async () => {
    if (!result || csvExporting) return
    setCsvExportError('')
    setCsvExporting(true)
    try {
      const out = await sheetsApi.exportCsv({ sql: result.sql })
      const source = (sheet?.filename || 'result').replace(/\.[^.]+$/, '')
      const a = document.createElement('a')
      a.href = out.url
      a.download = `${source}_filtered.csv`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      setTimeout(() => URL.revokeObjectURL(out.url), 1000)
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string }
      setCsvExportError(e.response?.data?.detail || e.message || 'CSV export failed.')
    } finally {
      setCsvExporting(false)
    }
  }, [result, sheet, csvExporting])

  // ── render ─────────────────────────────────────────────────────
  if (loadingMeta) {
    return (
      <div className="flex items-center justify-center h-full" style={{ color: 'var(--text-subtle)' }}>
        <Spinner className="animate-spin" size={18} />
        <span className="ml-2 text-[13px]">loading workspace…</span>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        {/* Header / Empty state */}
        {!sheet ? (
          <EmptyState
            uploading={uploading}
            error={uploadError}
            onPick={() => fileInputRef.current?.click()}
          />
        ) : (
          <SheetHeader
            sheet={sheet}
            onReplace={() => fileInputRef.current?.click()}
            onDelete={handleDelete}
            replacing={uploading}
          />
        )}

        {/* Split workspace: schema on left, composer+results on right (desktop) */}
        {sheet && (
          <div className="sheets-split-workspace">
            {/* Left pane: schema, stats & sample rows */}
            <div className="sheets-left-pane space-y-4">
              <Collapsible
                label={`Columns & types — ${sheet.column_count} column${sheet.column_count === 1 ? '' : 's'}`}
                icon={<Table size={13} />}
                open={schemaOpen}
                onToggle={() => setSchemaOpen((v) => !v)}
              >
                <SchemaTable sheet={sheet} />
              </Collapsible>

              <Collapsible
                label={`Sample rows — first ${sheet.sample_rows.length}`}
                icon={<Sparkle size={13} />}
                open={sampleOpen}
                onToggle={() => setSampleOpen((v) => !v)}
              >
                <ResultTable
                  columns={sheet.columns}
                  rows={sheet.sample_rows as Record<string, unknown>[]}
                  muted
                />
              </Collapsible>
            </div>

            {/* Right pane: composer + results */}
            <div className="space-y-6">
              {/* Composer */}
              <div
                className="rounded-2xl p-4 space-y-3"
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                }}
              >
                <p className="text-[11px] uppercase tracking-[0.22em]" style={{ color: 'var(--accent)' }}>
                  — ask in plain english
                </p>
                <textarea
                  ref={taRef}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                      e.preventDefault()
                      handleRun()
                    }
                  }}
                  placeholder='e.g. "show the customers with revenue over 10,000 sorted by signup date"'
                  rows={2}
                  disabled={running}
                  className="w-full bg-transparent outline-none resize-none text-[14px] leading-relaxed"
                  style={{ color: 'var(--text)' }}
                />

                <div className="flex flex-wrap gap-2">
                  {loadingSuggestions ? (
                    <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                      <Spinner className="animate-spin inline mr-1" size={11} /> Generating suggestions…
                    </span>
                  ) : (
                    suggestions.map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setQuestion(s)}
                        className="px-2.5 py-1 rounded-full text-[11px] transition-colors"
                        style={{
                          border: '1px solid var(--border-strong)',
                          color: 'var(--text-muted)',
                          background: 'transparent',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.borderColor = 'var(--accent-ring)'
                          e.currentTarget.style.color = 'var(--text)'
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.borderColor = 'var(--border-strong)'
                          e.currentTarget.style.color = 'var(--text-muted)'
                        }}
                      >
                        {s}
                      </button>
                    ))
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <div
                    role="tablist"
                    aria-label="Response mode"
                    className="flex items-center rounded-lg p-[2px]"
                    style={{
                      background: 'var(--bg-sunken)',
                      border: '1px solid var(--border-strong)',
                    }}
                  >
                    {(['Fast', 'Think'] as const).map((m) => {
                      const active = modelChoice === m
                      return (
                        <button
                          key={m}
                          type="button"
                          role="tab"
                          aria-selected={active}
                          onClick={() => setModelChoice(m)}
                          title={m === 'Fast' ? 'Quick answers, low latency' : 'Stronger reasoning, higher quality'}
                          className="px-2.5 py-1 rounded-md text-[12px] transition-colors"
                          style={{
                            background: active ? 'var(--accent)' : 'transparent',
                            color: active ? 'var(--bg)' : 'var(--text-muted)',
                            fontWeight: active ? 600 : 400,
                          }}
                        >
                          {m.toLowerCase()}
                        </button>
                      )
                    })}
                  </div>
                  <button
                    onClick={handleSaveQuery}
                    disabled={!question.trim()}
                    className="px-2 py-1.5 rounded-lg text-[11px] transition-colors"
                    style={{
                      border: '1px solid var(--border-strong)',
                      color: 'var(--text-muted)',
                      background: 'transparent',
                    }}
                    title="Save this query for later"
                  >
                    <BookmarkSimple size={13} weight="fill" /> save
                  </button>
                  <button
                    onClick={() => setShowSaved((v) => !v)}
                    className="px-2 py-1.5 rounded-lg text-[11px] transition-colors"
                    style={{
                      border: '1px solid var(--border-strong)',
                      color: 'var(--text-muted)',
                      background: 'transparent',
                    }}
                    title="Saved queries"
                  >
                    saved ({savedQueries.length})
                  </button>
                  <span className="text-[10px] uppercase tracking-[0.18em]" style={{ color: 'var(--text-subtle)' }}>
                    ctrl/⌘ + enter
                  </span>
                  <div className="flex-1" />
                  <button
                    onClick={handleRun}
                    disabled={running || !question.trim()}
                    className="btn-primary !px-4 !py-2 text-[13px]"
                  >
                    {running ? (
                      <>
                        <Spinner className="animate-spin" size={13} /> querying…
                      </>
                    ) : (
                      <>
                        run query <ArrowRight size={13} weight="bold" />
                      </>
                    )}
                  </button>
                </div>

                {showSaved && savedQueries.length > 0 && (
                  <div
                    className="rounded-lg p-2 space-y-1 max-h-48 overflow-y-auto"
                    style={{ background: 'var(--bg-sunken)', border: '1px solid var(--border-strong)' }}
                  >
                    {savedQueries.map((sq) => (
                      <div
                        key={sq.id}
                        className="flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer text-[12px] group"
                        style={{ color: 'var(--text)' }}
                        onClick={() => handleLoadSaved(sq)}
                      >
                        <span className="flex-1 truncate">{sq.question}</span>
                        <span className="text-[10px] shrink-0" style={{ color: 'var(--text-subtle)' }}>
                          {new Date(sq.createdAt).toLocaleDateString()}
                        </span>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteSaved(sq.id) }}
                          className="opacity-0 group-hover:opacity-100 p-1 rounded transition-opacity"
                          style={{ color: 'var(--danger)' }}
                          aria-label="Delete saved query"
                        >
                          <Trash size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {runError && <InlineError message={runError} />}
              </div>

              {/* Result */}
              {result && (
                <div
                  className="rounded-2xl p-4 space-y-4"
                  style={{
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                  }}
                >
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-[11px] uppercase tracking-[0.22em]" style={{ color: 'var(--accent)' }}>
                      — result
                    </span>
                    <span className="text-[12px]" style={{ color: 'var(--text-muted)' }}>
                      {result.row_count.toLocaleString()} row{result.row_count === 1 ? '' : 's'} ·{' '}
                      {result.columns.length} column{result.columns.length === 1 ? '' : 's'}
                      {result.truncated && ' · preview truncated'}
                    </span>
                    <div className="flex-1" />
                    <button
                      onClick={handleCsvExport}
                      disabled={csvExporting || result.row_count === 0}
                      className="btn-ghost !px-3 !py-1.5 text-[12px]"
                      title="Download as CSV"
                    >
                      {csvExporting ? (
                        <Spinner className="animate-spin" size={12} />
                      ) : (
                        <>
                          <FileCsv size={13} weight="bold" /> csv
                        </>
                      )}
                    </button>
                    <button
                      onClick={handleExport}
                      disabled={exporting || result.row_count === 0}
                      className="btn-primary !px-3 !py-1.5 text-[12px]"
                      title="Download the full query result as Excel"
                    >
                      {exporting ? (
                        <>
                          <Spinner className="animate-spin" size={12} /> exporting…
                        </>
                      ) : (
                        <>
                          <DownloadSimple size={13} weight="bold" /> .xlsx
                        </>
                      )}
                    </button>
                  </div>

                  {result.summary && (
                    <p className="text-[13px] leading-relaxed" style={{ color: 'var(--text)' }}>
                      {result.summary}
                    </p>
                  )}

                  {/* Auto-chart */}
                  <AutoChart chart={result.chart} columns={result.columns} rows={result.rows} />

                  <Collapsible
                    label="View generated SQL"
                    icon={<Lightning size={12} />}
                    open={sqlOpen}
                    onToggle={() => setSqlOpen((v) => !v)}
                  >
                    <pre
                      className="text-[12px] leading-relaxed p-3 rounded-md overflow-x-auto whitespace-pre-wrap"
                      style={{
                        background: 'var(--bg-sunken)',
                        color: 'var(--text)',
                        border: '1px solid var(--border-strong)',
                      }}
                    >
                      {result.sql}
                    </pre>
                  </Collapsible>

                  <ResultTable columns={result.columns} rows={result.rows} />

                  {exportError && <InlineError message={exportError} />}
                  {csvExportError && <InlineError message={csvExportError} />}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Hidden file input — shared by upload & replace */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xls,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleFile(f)
            e.target.value = ''
          }}
        />
      </div>
    </div>
  )
}

// ── Pieces ─────────────────────────────────────────────────────────

function EmptyState({
  uploading,
  error,
  onPick,
}: {
  uploading: boolean
  error: string
  onPick: () => void
}) {
  return (
    <div className="py-16">
      <p className="text-[11px] uppercase tracking-[0.22em] mb-3" style={{ color: 'var(--accent)' }}>
        — sheets workspace
      </p>
      <h1
        className="font-display text-5xl md:text-6xl leading-[1.02] tracking-tight"
        style={{ color: 'var(--text)' }}
      >
        ask your <span className="mark">spreadsheet</span>.
      </h1>
      <p
        className="mt-6 text-[13px] leading-relaxed max-w-md"
        style={{ color: 'var(--text-muted)' }}
      >
        Upload an Excel or CSV file and ask questions in plain English. The model
        only ever sees the column names and basic statistics — never your raw rows.
        Filtered results download as a fresh <code>.xlsx</code>.
      </p>

      <button
        onClick={onPick}
        disabled={uploading}
        className="mt-10 flex items-center gap-2 px-5 py-3 rounded-xl text-[14px] transition-all"
        style={{
          background: 'var(--accent)',
          color: 'var(--bg)',
          border: '1px solid var(--accent)',
          opacity: uploading ? 0.6 : 1,
        }}
      >
        {uploading ? (
          <>
            <Spinner className="animate-spin" size={15} /> uploading & parsing…
          </>
        ) : (
          <>
            <UploadSimple size={15} weight="bold" /> upload .xlsx / .csv
          </>
        )}
      </button>

      <p className="mt-3 text-[11px]" style={{ color: 'var(--text-subtle)' }}>
        up to 20 MB · only one sheet at a time · replacing deletes the old one
      </p>

      {error && (
        <div className="mt-6 max-w-md">
          <InlineError message={error} />
        </div>
      )}
    </div>
  )
}

function SheetHeader({
  sheet,
  onReplace,
  onDelete,
  replacing,
}: {
  sheet: SheetMeta
  onReplace: () => void
  onDelete: () => void
  replacing: boolean
}) {
  return (
    <div
      className="rounded-2xl p-4 flex items-start gap-4"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
    >
      <div
        className="w-10 h-10 rounded-md flex items-center justify-center shrink-0"
        style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
      >
        <FileXls size={20} weight="fill" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] uppercase tracking-[0.22em]" style={{ color: 'var(--text-subtle)' }}>
          active sheet
        </p>
        <h2 className="font-display text-[20px] leading-tight truncate" style={{ color: 'var(--text)' }}>
          {sheet.filename}
        </h2>
        <p className="text-[12px] mt-1" style={{ color: 'var(--text-muted)' }}>
          {sheet.row_count.toLocaleString()} rows · {sheet.column_count} columns
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={onReplace}
          disabled={replacing}
          className="px-3 py-1.5 rounded-lg text-[12px] transition-colors"
          style={{
            border: '1px solid var(--border-strong)',
            color: 'var(--text-muted)',
            background: 'transparent',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = 'var(--accent-ring)'
            e.currentTarget.style.color = 'var(--text)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = 'var(--border-strong)'
            e.currentTarget.style.color = 'var(--text-muted)'
          }}
        >
          {replacing ? (
            <Spinner className="animate-spin inline" size={12} />
          ) : (
            <>replace</>
          )}
        </button>
        <button
          onClick={onDelete}
          className="p-2 rounded-lg transition-colors"
          style={{ color: 'var(--text-muted)' }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = 'var(--danger)'
            e.currentTarget.style.background = 'var(--danger-soft)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = 'var(--text-muted)'
            e.currentTarget.style.background = 'transparent'
          }}
          aria-label="Delete sheet"
        >
          <Trash size={14} />
        </button>
      </div>
    </div>
  )
}

function Collapsible({
  label,
  icon,
  open,
  onToggle,
  children,
}: {
  label: string
  icon?: React.ReactNode
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div
      className="rounded-xl"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
    >
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-4 py-3 text-[13px] text-left"
        style={{ color: 'var(--text)' }}
      >
        {icon && <span style={{ color: 'var(--accent)' }}>{icon}</span>}
        <span className="flex-1">{label}</span>
        <span className="text-[11px]" style={{ color: 'var(--text-subtle)' }}>
          {open ? 'hide' : 'show'}
        </span>
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  )
}

function SchemaTable({ sheet }: { sheet: SheetMeta }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12px]" style={{ color: 'var(--text)' }}>
        <thead>
          <tr style={{ color: 'var(--text-subtle)' }} className="text-left uppercase tracking-[0.16em] text-[10px]">
            <th className="py-2 pr-3">column</th>
            <th className="py-2 pr-3">type</th>
            <th className="py-2 pr-3">non-null</th>
            <th className="py-2 pr-3">null</th>
            <th className="py-2">stats</th>
          </tr>
        </thead>
        <tbody>
          {sheet.schema.map((c) => {
            const s = sheet.statistics[c.column]
            return (
              <tr
                key={c.column}
                style={{ borderTop: '1px solid var(--border)' }}
              >
                <td className="py-2 pr-3 font-mono">{c.column}</td>
                <td className="py-2 pr-3" style={{ color: 'var(--text-muted)' }}>{c.dtype}</td>
                <td className="py-2 pr-3 tabular-nums">{c.non_null_count.toLocaleString()}</td>
                <td className="py-2 pr-3 tabular-nums" style={{ color: c.null_count ? 'var(--text-muted)' : 'var(--text-subtle)' }}>
                  {c.null_count.toLocaleString()}
                </td>
                <td className="py-2 tabular-nums" style={{ color: 'var(--text-muted)' }}>
                  {s
                    ? `min ${fmtNum(s.min)} · max ${fmtNum(s.max)} · mean ${fmtNum(s.mean)}`
                    : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ResultTable({
  columns,
  rows,
  muted,
}: {
  columns: string[]
  rows: Record<string, unknown>[]
  muted?: boolean
}) {
  if (rows.length === 0) {
    return (
      <p className="text-[12px] italic py-3" style={{ color: 'var(--text-subtle)' }}>
        no rows returned.
      </p>
    )
  }
  return (
    <div
      className="overflow-x-auto rounded-md"
      style={{ border: '1px solid var(--border-strong)' }}
    >
      <table className="w-full text-[12px]" style={{ color: muted ? 'var(--text-muted)' : 'var(--text)' }}>
        <thead>
          <tr
            style={{
              background: 'var(--bg-sunken)',
              color: 'var(--text-subtle)',
            }}
            className="text-left uppercase tracking-[0.16em] text-[10px]"
          >
            {columns.map((c) => (
              <th key={c} className="px-3 py-2">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>
              {columns.map((c) => (
                <td key={c} className="px-3 py-2 whitespace-nowrap">
                  {fmtCell(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function InlineError({ message }: { message: string }) {
  return (
    <div
      className="flex items-start gap-2 p-3 rounded-lg text-[12px]"
      style={{
        background: 'var(--danger-soft)',
        color: 'var(--danger)',
        border: '1px solid var(--danger)',
      }}
    >
      <WarningCircle size={14} weight="fill" className="mt-0.5 shrink-0" />
      <span className="flex-1 whitespace-pre-wrap break-words">{message}</span>
      <X size={12} className="opacity-0" />
    </div>
  )
}

// ── chart component ────────────────────────────────────────────────

const CHART_COLORS = [
  'var(--accent)',
  '#60a5fa',
  '#34d399',
  '#fbbf24',
  '#f87171',
  '#a78bfa',
  '#22d3ee',
  '#fb923c',
]

const TOOLTIP_STYLE = {
  background: 'var(--bg-elevated)',
  border: '2px solid var(--accent)',
  borderRadius: 8,
  color: 'var(--text)',
  fontSize: 12,
  boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
}

async function downloadChartPng(container: HTMLDivElement | null, filename: string) {
  if (!container) return
  const svg = container.querySelector('svg')
  if (!svg) return

  const clone = svg.cloneNode(true) as SVGSVGElement
  const rootStyles = getComputedStyle(document.documentElement)

  // Inline CSS custom properties so the exported SVG renders standalone
  const walk = (el: Element) => {
    for (const attr of Array.from(el.attributes)) {
      if (attr.value.includes('var(--')) {
        let val = attr.value
        val = val.replace(/var\(--[\w-]+\)/g, (m) => {
          const name = m.slice(4, -1)
          return rootStyles.getPropertyValue(name).trim() || m
        })
        el.setAttribute(attr.name, val)
      }
    }
    Array.from(el.children).forEach(walk)
  }
  walk(clone)

  const rect = svg.getBoundingClientRect()
  clone.setAttribute('width', String(rect.width))
  clone.setAttribute('height', String(rect.height))
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')

  const svgStr = new XMLSerializer().serializeToString(clone)
  const blob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)

  const canvas = document.createElement('canvas')
  canvas.width = rect.width * 2
  canvas.height = rect.height * 2
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    URL.revokeObjectURL(url)
    return
  }

  const img = document.createElement('img')
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve()
    img.onerror = reject
    img.src = url
  })

  ctx.scale(2, 2)
  ctx.drawImage(img, 0, 0)
  URL.revokeObjectURL(url)

  const a = document.createElement('a')
  a.href = canvas.toDataURL('image/png')
  a.download = filename
  a.click()
}

function ChartCard({
  title,
  children,
  filename,
}: {
  title: string
  children: React.ReactElement
  filename: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  return (
    <div className="rounded-xl p-4" style={{ background: 'var(--bg-sunken)', border: '1px solid var(--border-strong)' }}>
      <div className="flex items-center justify-between mb-2">
        <p className="text-[11px] uppercase tracking-[0.18em]" style={{ color: 'var(--text-subtle)' }}>
          — {title}
        </p>
        <button
          onClick={() => downloadChartPng(ref.current, filename)}
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] transition-colors cursor-pointer"
          style={{
            border: '1px solid var(--border)',
            color: 'var(--text-muted)',
            background: 'transparent',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = 'var(--accent-ring)'
            e.currentTarget.style.color = 'var(--text)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = 'var(--border)'
            e.currentTarget.style.color = 'var(--text-muted)'
          }}
          title="Download chart as PNG"
        >
          <ImageIcon size={10} weight="fill" /> PNG
        </button>
      </div>
      <div className="h-56" ref={ref}>
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function AutoChart({
  chart,
  rows,
  columns,
}: {
  chart: { type: string; title?: string; x?: string; y?: string; labels?: string; values?: string; series?: { key: string; name: string }[] } | null
  rows: Record<string, unknown>[]
  columns: string[]
}) {
  if (rows.length < 1 || rows.length > 100) return null

  const type = chart?.type
  const series = chart?.series?.length ? chart.series : []

  // ── Pie ────────────────────────────────────────────────────────
  if (type === 'pie') {
    const labelCol = chart?.labels || columns[0]
    const valueCol = chart?.values || columns.find((c) => rows.every((r) => typeof r[c] === 'number')) || columns[1]
    if (!labelCol || !valueCol) return null
    const data = rows.map((r) => ({
      name: String(r[labelCol]).slice(0, 20),
      value: Number(r[valueCol]) || 0,
    }))
    return (
      <ChartCard title={chart?.title || 'Distribution'} filename="chart-pie.png">
        {/* @ts-ignore */}
        <PieChart>
          {/* @ts-ignore */}
          <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
          {/* @ts-ignore */}
          <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-muted)' }} />
          {/* @ts-ignore */}
          <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80}>
            {data.map((_, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
          </Pie>
        </PieChart>
      </ChartCard>
    )
  }

  // ── Scatter ──────────────────────────────────────────────────────
  if (type === 'scatter') {
    const xCol = chart?.x || columns.find((c) => rows.every((r) => typeof r[c] === 'number')) || columns[0]
    const yCol = chart?.y || columns.find((c, i) => i > columns.indexOf(xCol) && rows.every((r) => typeof r[c] === 'number')) || columns[1]
    if (!xCol || !yCol) return null
    const data = rows.map((r) => ({
      x: Number(r[xCol]) || 0,
      y: Number(r[yCol]) || 0,
    }))
    return (
      <ChartCard title={chart?.title || 'Correlation'} filename="chart-scatter.png">
        {/* @ts-ignore */}
        <ScatterChart margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
          {/* @ts-ignore */}
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-strong)" />
          {/* @ts-ignore */}
          <XAxis type="number" dataKey="x" name={xCol} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
          {/* @ts-ignore */}
          <YAxis type="number" dataKey="y" name={yCol} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
          {/* @ts-ignore */}
          <Tooltip cursor={{ strokeDasharray: '3 3' }} contentStyle={TOOLTIP_STYLE} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
          {/* @ts-ignore */}
          <Scatter data={data} fill="var(--accent)" />
        </ScatterChart>
      </ChartCard>
    )
  }

  // ── Radar ────────────────────────────────────────────────────────
  if (type === 'radar') {
    const xCol = chart?.x || columns[0]
    const radarSeries = series.length ? series : [{ key: columns.find((c) => rows.every((r) => typeof r[c] === 'number')) || columns[1], name: 'Value' }]
    const data = rows.map((r) => {
      const point: Record<string, unknown> = { subject: String(r[xCol]).slice(0, 20) }
      radarSeries.forEach((s) => { point[s.key] = Number(r[s.key]) || 0 })
      return point
    })
    return (
      <ChartCard title={chart?.title || 'Radar Comparison'} filename="chart-radar.png">
        {/* @ts-ignore */}
        <RadarChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
          {/* @ts-ignore */}
          <PolarGrid stroke="var(--border-strong)" />
          {/* @ts-ignore */}
          <PolarAngleAxis dataKey="subject" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} />
          {/* @ts-ignore */}
          <PolarRadiusAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} />
          {/* @ts-ignore */}
          <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
          {radarSeries.map((s, i) => (
            /* @ts-ignore */
            <Radar key={s.key} name={s.name} dataKey={s.key} stroke={CHART_COLORS[i % CHART_COLORS.length]} fill={CHART_COLORS[i % CHART_COLORS.length]} fillOpacity={0.3} />
          ))}
        </RadarChart>
      </ChartCard>
    )
  }

  // For cartesian charts (bar, stacked_bar, line, area, histogram) we share the same data prep
  const xCol = chart?.x || columns[0]
  const cartSeries = series.length ? series : [{ key: chart?.y || columns.find((c) => rows.every((r) => typeof r[c] === 'number')) || columns[1], name: 'Value' }]
  if (!xCol || !cartSeries[0]?.key) return null

  const data = rows.map((r) => {
    const point: Record<string, unknown> = { name: String(r[xCol]).slice(0, 20) }
    cartSeries.forEach((s) => { point[s.key] = Number(r[s.key]) || 0 })
    return point
  })

  // ── Stacked Bar ──────────────────────────────────────────────────
  if (type === 'stacked_bar') {
    return (
      <ChartCard title={chart?.title || 'Stacked Comparison'} filename="chart-stacked-bar.png">
        {/* @ts-ignore */}
        <BarChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
          {/* @ts-ignore */}
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-strong)" />
          {/* @ts-ignore */}
          <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
          {/* @ts-ignore */}
          <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
          {/* @ts-ignore */}
          <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
          {/* @ts-ignore */}
          <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-muted)' }} />
          {cartSeries.map((s, i) => (
            /* @ts-ignore */
            <Bar key={s.key} dataKey={s.key} name={s.name} stackId="a" fill={CHART_COLORS[i % CHART_COLORS.length]} radius={[0, 0, 0, 0]} />
          ))}
        </BarChart>
      </ChartCard>
    )
  }

  // ── Area ─────────────────────────────────────────────────────────
  if (type === 'area') {
    return (
      <ChartCard title={chart?.title || 'Area Analysis'} filename="chart-area.png">
        {/* @ts-ignore */}
        <AreaChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
          {/* @ts-ignore */}
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-strong)" />
          {/* @ts-ignore */}
          <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
          {/* @ts-ignore */}
          <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
          {/* @ts-ignore */}
          <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
          {/* @ts-ignore */}
          <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-muted)' }} />
          {cartSeries.map((s, i) => (
            /* @ts-ignore */
            <Area key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={CHART_COLORS[i % CHART_COLORS.length]} fill={CHART_COLORS[i % CHART_COLORS.length]} fillOpacity={0.3} />
          ))}
        </AreaChart>
      </ChartCard>
    )
  }

  // ── Line ─────────────────────────────────────────────────────────
  if (type === 'line') {
    return (
      <ChartCard title={chart?.title || 'Trend'} filename="chart-line.png">
        {/* @ts-ignore */}
        <LineChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
          {/* @ts-ignore */}
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-strong)" />
          {/* @ts-ignore */}
          <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
          {/* @ts-ignore */}
          <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
          {/* @ts-ignore */}
          <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
          {/* @ts-ignore */}
          <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-muted)' }} />
          {cartSeries.map((s, i) => (
            /* @ts-ignore */
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={CHART_COLORS[i % CHART_COLORS.length]} strokeWidth={2} dot={false} />
          ))}
        </LineChart>
      </ChartCard>
    )
  }

  // ── Default: Grouped Bar (or Histogram approximated as bar) ────
  return (
    <ChartCard title={chart?.title || 'Comparison'} filename="chart-bar.png">
      {/* @ts-ignore */}
      <BarChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
        {/* @ts-ignore */}
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-strong)" />
        {/* @ts-ignore */}
        <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
        {/* @ts-ignore */}
        <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
        {/* @ts-ignore */}
        <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: 'var(--text)' }} itemStyle={{ color: 'var(--text)' }} />
        {/* @ts-ignore */}
        <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-muted)' }} />
        {cartSeries.map((s, i) => (
          /* @ts-ignore */
          <Bar key={s.key} dataKey={s.key} name={s.name} fill={CHART_COLORS[i % CHART_COLORS.length]} radius={[4, 4, 0, 0]} />
        ))}
      </BarChart>
    </ChartCard>
  )
}

// ── helpers ────────────────────────────────────────────────────────

function fmtNum(n: number): string {
  if (!Number.isFinite(n)) return '—'
  if (Math.abs(n) >= 1000 || (Math.abs(n) < 1 && n !== 0)) {
    return n.toPrecision(4)
  }
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') {
    return Number.isInteger(v) ? v.toLocaleString() : fmtNum(v)
  }
  if (typeof v === 'string') return v
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}
