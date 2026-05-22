import React, { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';
import { Check, Copy, PencilLine, Warning } from '@phosphor-icons/react';
import { useDiagramStore } from '../store/diagramStore';
import { useNavigate } from 'react-router-dom';

interface MermaidRendererProps {
  code: string;
  inline?: boolean;
}

// Initialize mermaid globally
try {
  mermaid.initialize({
    startOnLoad: false,
    theme: 'base',
    securityLevel: 'loose',
    themeVariables: {
      primaryColor: '#b8864f',
      primaryTextColor: '#f5f2e9',
      primaryBorderColor: 'rgba(255,255,255,0.06)',
      lineColor: '#8c8a82',
      secondaryColor: '#141416',
      tertiaryColor: '#0a0a0a',
    }
  });
} catch (e) {
  console.error("Mermaid initialization failed", e);
}

export const MermaidRenderer: React.FC<MermaidRendererProps> = ({ code, inline = false }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svgHtml, setSvgHtml] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'visual' | 'source'>('visual');
  const [copied, setCopied] = useState(false);
  const navigate = useNavigate();
  const store = useDiagramStore();

  const cleanCode = code.trim();

  useEffect(() => {
    let isMounted = true;
    if (viewMode !== 'visual') return;

    setError(null);
    setSvgHtml('');

    const renderId = `mermaid-svg-${Math.random().toString(36).slice(2, 9)}`;

    const renderDiagram = async () => {
      try {
        // Detect dark mode from document context
        const isDark = document.documentElement.classList.contains('dark') || document.body.classList.contains('dark');
        
        mermaid.initialize({
          startOnLoad: false,
          theme: isDark ? 'dark' : 'default',
          securityLevel: 'loose',
        });

        // Run validation check before compile to prevent infinite lock or console spam
        const { svg } = await mermaid.render(renderId, cleanCode);
        if (isMounted) {
          setSvgHtml(svg);
        }
      } catch (err: any) {
        console.error("Inline Mermaid compilation error:", err);
        if (isMounted) {
          setError(err?.message || "Syntax error parsing Mermaid code flow.");
        }
      }
    };

    void renderDiagram();

    return () => {
      isMounted = false;
    };
  }, [cleanCode, viewMode]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(cleanCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      // silent fail
    }
  };

  const handleOpenInStudio = () => {
    // Generate a beautiful title from diagram content or generic
    const title = "Chat Blueprint " + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    store.createDiagramFromMermaid(title, cleanCode);
    navigate('/architect');
  };

  if (inline) {
    return (
      <div 
        className="relative group w-full flex items-center justify-center p-4 rounded-xl border bg-[var(--bg-elevated)] overflow-hidden transition-all shadow-sm"
        style={{ borderColor: 'var(--border-strong)' }}
      >
        {/* Floating actions on hover */}
        <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity duration-200 z-10 flex items-center gap-1.5">
          <button
            onClick={handleCopy}
            className="p-1 rounded border bg-[var(--bg-sunken)] text-[var(--text-muted)] hover:text-[var(--text)] transition-all flex items-center gap-1 text-[10px] px-2 py-0.5 shadow-sm"
            style={{ borderColor: 'var(--border)' }}
            title="Copy Mermaid Code"
          >
            {copied ? <Check size={10} className="text-green-500" /> : <Copy size={10} />}
            <span>{copied ? 'Copied!' : 'Copy'}</span>
          </button>
          
          <button
            onClick={handleOpenInStudio}
            className="p-1 rounded border bg-[var(--accent)] hover:bg-[var(--accent-strong)] text-white font-medium transition-all flex items-center gap-1 text-[10px] px-2.5 py-0.5 shadow-sm"
            style={{ borderColor: 'var(--border-strong)' }}
            title="Open in Architecture Studio Canvas"
          >
            <PencilLine size={11} weight="bold" />
            <span>Edit in Studio</span>
          </button>
        </div>

        {error ? (
          <div className="text-center p-4 max-w-md w-full">
            <Warning size={28} className="text-amber-500 mx-auto mb-2" />
            <div className="text-xs font-semibold mb-1 text-[var(--text)]">Visual Render Failed</div>
            <div className="text-[10px] text-red-400 font-mono leading-tight bg-red-500/10 p-2.5 rounded border border-red-500/20 text-left max-h-40 overflow-y-auto w-full select-text">
              {error}
            </div>
          </div>
        ) : svgHtml ? (
          <div 
            ref={containerRef}
            className="w-full flex items-center justify-center overflow-x-auto p-1"
            dangerouslySetInnerHTML={{ __html: svgHtml }}
          />
        ) : (
          <div className="flex flex-col items-center gap-2 text-[var(--text-muted)] py-6 text-xs font-medium">
            <div className="w-5 h-5 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
            <span>Compiling structural system view...</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <div 
      className="my-4 rounded-xl border overflow-hidden bg-[var(--bg-elevated)] max-w-full shadow-sm text-left"
      style={{ borderColor: 'var(--border-strong)' }}
    >
      {/* Header bar */}
      <div 
        className="h-10 px-4 border-b flex items-center justify-between bg-[var(--bg-sunken)] text-xs font-mono select-none"
        style={{ borderColor: 'var(--border)' }}
      >
        <div className="flex items-center gap-2">
          <button
            onClick={() => setViewMode('visual')}
            className={`py-1 px-2.5 rounded-md font-semibold transition-colors ${viewMode === 'visual' ? 'bg-[var(--bg-elevated)] text-[var(--accent)] border border-[var(--border)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]'}`}
          >
            Visual Diagram
          </button>
          <button
            onClick={() => setViewMode('source')}
            className={`py-1 px-2.5 rounded-md font-semibold transition-colors ${viewMode === 'source' ? 'bg-[var(--bg-elevated)] text-[var(--accent)] border border-[var(--border)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]'}`}
          >
            Source Code
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="p-1 rounded-md border bg-[var(--bg-elevated)] text-[var(--text-muted)] hover:text-[var(--text)] transition-all flex items-center gap-1 px-2 py-0.5 hover:shadow-sm"
            style={{ borderColor: 'var(--border)' }}
            title="Copy Mermaid Code"
          >
            {copied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
            <span>{copied ? 'Copied!' : 'Copy'}</span>
          </button>
          
          <button
            onClick={handleOpenInStudio}
            className="p-1 rounded-md border bg-[var(--accent)] hover:bg-[var(--accent-strong)] text-white font-medium transition-all flex items-center gap-1.5 px-2.5 py-0.5 shadow-sm"
            title="Open in Architecture Studio Canvas"
          >
            <PencilLine size={13} weight="bold" />
            <span>Edit in Studio</span>
          </button>
        </div>
      </div>

      {/* Content pane */}
      <div className="p-4 overflow-x-auto min-h-[120px] flex items-center justify-center relative bg-[var(--bg-elevated)]">
        {viewMode === 'visual' ? (
          error ? (
            <div className="text-center p-4 max-w-md w-full">
              <Warning size={32} className="text-amber-500 mx-auto mb-2" />
              <div className="text-xs font-semibold mb-1 text-[var(--text)]">Visual Render Failed</div>
              <div className="text-[10px] text-red-400 font-mono leading-tight bg-red-500/10 p-2.5 rounded border border-red-500/20 text-left max-h-40 overflow-y-auto w-full select-text">
                {error}
              </div>
              <button 
                onClick={() => setViewMode('source')}
                className="mt-3 text-[10px] font-semibold text-[var(--accent)] hover:underline"
              >
                Inspect Mermaid Syntax
              </button>
            </div>
          ) : svgHtml ? (
            <div 
              ref={containerRef}
              className="w-full flex items-center justify-center p-2 rounded-lg bg-[var(--bg-elevated)] overflow-x-auto"
              dangerouslySetInnerHTML={{ __html: svgHtml }}
            />
          ) : (
            <div className="flex flex-col items-center gap-2 text-[var(--text-muted)] py-6 text-xs font-medium">
              <div className="w-5 h-5 rounded-full border-2 border-[var(--accent)] border-t-transparent animate-spin" />
              <span>Compiling structural system view...</span>
            </div>
          )
        ) : (
          <pre className="w-full text-[12px] font-mono leading-relaxed p-4 rounded-lg bg-[var(--bg-sunken)] border text-[var(--text)] select-text overflow-x-auto" style={{ borderColor: 'var(--border)' }}>
            <code>{cleanCode}</code>
          </pre>
        )}
      </div>
    </div>
  );
};

export default MermaidRenderer;
