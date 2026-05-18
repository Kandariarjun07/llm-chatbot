import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** Optional fallback for granular boundaries (e.g. around a chart). */
  fallback?: (error: Error, reset: () => void) => ReactNode
  /** Human label shown in logs / UI so we can tell which boundary tripped. */
  scope?: string
}

interface State {
  error: Error | null
}

/**
 * React error boundary.
 *
 * Default React behaviour is to unmount the entire tree on an uncaught
 * render error — that turns a single broken chart into a blank white
 * page for the user. Wrapping subtrees in this boundary keeps the rest
 * of the app interactive and gives the user a concrete way to recover.
 *
 * Use a small `fallback` for leaf widgets (charts, markdown blocks).
 * Leave it undefined at the app root to show the full-page recovery UI.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Production: ship to monitoring (Sentry, etc.) here. Console is
    // good enough until that pipeline exists.
    // eslint-disable-next-line no-console
    console.error(
      `[ErrorBoundary${this.props.scope ? `:${this.props.scope}` : ''}]`,
      error,
      info.componentStack,
    )
  }

  reset = () => this.setState({ error: null })

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    if (this.props.fallback) return this.props.fallback(error, this.reset)

    return (
      <div
        role="alert"
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '24px',
          background: 'var(--bg, #0a0a0a)',
          color: 'var(--text, #f5f5f5)',
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial",
        }}
      >
        <div style={{ maxWidth: 480, width: '100%', textAlign: 'center' }}>
          <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 12 }}>
            Something went wrong
          </h1>
          <p style={{ opacity: 0.75, fontSize: 14, lineHeight: 1.6, marginBottom: 24 }}>
            The page hit an unexpected error. You can try again, or reload to
            start fresh. Your conversations are saved.
          </p>
          <details
            style={{
              textAlign: 'left',
              padding: '12px 14px',
              background: 'var(--bg-elevated, #141416)',
              borderRadius: 10,
              border: '1px solid rgba(255,255,255,0.08)',
              fontSize: 12,
              marginBottom: 20,
              opacity: 0.85,
            }}
          >
            <summary style={{ cursor: 'pointer', marginBottom: 8 }}>
              Technical details
            </summary>
            <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: 11 }}>
              {error.message}
            </pre>
          </details>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
            <button
              onClick={this.reset}
              style={{
                padding: '10px 18px',
                borderRadius: 10,
                border: '1px solid rgba(255,255,255,0.12)',
                background: 'transparent',
                color: 'inherit',
                cursor: 'pointer',
              }}
            >
              Try again
            </button>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: '10px 18px',
                borderRadius: 10,
                border: 'none',
                background: 'var(--accent, #f5b400)',
                color: '#000',
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              Reload page
            </button>
          </div>
        </div>
      </div>
    )
  }
}
