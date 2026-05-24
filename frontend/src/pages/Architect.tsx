import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import mermaid from 'mermaid';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  MarkerType,
  Position,
  Handle,
  Connection
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import {
  Laptop,
  Cpu,
  Database as DbIcon,
  Cloud,
  ListPlus,
  Lock,
  Plus,
  TrashSimple,
  ArrowClockwise,
  ArrowCounterClockwise,
  UploadSimple,
  DownloadSimple,
  X,
  CaretDown,
  CaretUp,
  CaretLeft,
  CaretRight,
  Terminal,
  Warning,
  Sparkle,
  TreeStructure,
  Export,
  FloppyDiskBack,
  FileCode,
  Compass,
  Hand,
  CursorClick,
  Images,
} from '@phosphor-icons/react';

import { useDiagramStore } from '../store/diagramStore';
import { useThemeStore } from '../store/themeStore';
import { CanonicalNode } from '../lib/diagramParser';
import useIsMobile from '../hooks/useIsMobile';

// ── Custom Node Configuration ────────────────────────────────────────────────

interface NodeConfig {
  color: string;
  icon: React.ComponentType<any>;
}

const getNodeConfig = (type: string): NodeConfig => {
  switch (type) {
    case 'client':
      return { color: '#3b82f6', icon: Laptop }; // Blue
    case 'service':
      return { color: '#10b981', icon: Cpu };    // Green
    case 'database':
      return { color: '#8b5cf6', icon: DbIcon }; // Purple
    case 'cloud':
      return { color: '#f59e0b', icon: Cloud };  // Amber
    case 'queue':
      return { color: '#14b8a6', icon: ListPlus }; // Teal
    case 'gatekeeper':
      return { color: '#ef4444', icon: Lock };   // Red
    default:
      return { color: '#64748b', icon: Cpu };    // Slate
  }
};

// ── Custom Canvas Node Component ─────────────────────────────────────────────

const CustomNodeComponent = ({ data }: any) => {
  const { id, label, type } = data;
  const isLR = useDiagramStore(s => s.diagramType === 'flowchart-lr');
  const config = getNodeConfig(type);
  const Icon = config.icon;

  return (
    <div
      className="relative flex items-center gap-3 px-3 py-2.5 rounded-lg border shadow-md min-w-[210px] bg-[var(--bg-elevated)] border-[var(--border-strong)] hover:shadow-lg transition-shadow cursor-grab active:cursor-grabbing"
      style={{ borderLeft: `5px solid ${config.color}` }}
    >
      <Handle
        type="target"
        position={isLR ? Position.Left : Position.Top}
        style={{ background: 'var(--border-strong)', width: 8, height: 8 }}
      />

      <div
        className="flex items-center justify-center p-2 rounded-md shrink-0"
        style={{ background: `${config.color}20`, color: config.color }}
      >
        <Icon size={16} weight="duotone" />
      </div>

      <div className="flex-1 min-w-0 pr-4">
        <div className="text-[10px] uppercase font-bold tracking-wider opacity-60 leading-none mb-0.5" style={{ color: config.color }}>
          {type}
        </div>
        <input
          defaultValue={label}
          onBlur={(e) => {
            const val = e.target.value.trim();
            if (val && val !== label) {
              useDiagramStore.getState().updateNodeLabel(id, val);
            }
          }}
          className="w-full bg-transparent border-0 outline-none text-[13px] font-medium leading-none focus:bg-[var(--bg)] px-0.5 rounded"
          style={{ color: 'var(--text)' }}
        />
      </div>

      {/* Delete Trigger */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          useDiagramStore.getState().deleteNode(id);
        }}
        className="absolute top-1 right-1 p-0.5 rounded hover:bg-[var(--danger-soft)] hover:text-[var(--danger)] text-[var(--text-muted)]"
        title="Delete Node"
      >
        <X size={10} weight="bold" />
      </button>

      <Handle
        type="source"
        position={isLR ? Position.Right : Position.Bottom}
        style={{ background: 'var(--border-strong)', width: 8, height: 8 }}
      />
    </div>
  );
};

const nodeTypes = {
  customNode: CustomNodeComponent
};

// ── Master Page View ─────────────────────────────────────────────────────────

export default function Architect() {
  const store = useDiagramStore();
  const theme = useThemeStore(s => s.theme);
  const isMobile = useIsMobile();

  const [activeTab, setActiveTab] = useState<'templates' | 'saves' | 'import'>('templates');
  const [rightTab, setRightTab] = useState<'copilot' | 'audit'>('copilot');
  const [bottomTab, setBottomTab] = useState<'source' | 'json' | 'logs'>('source');
  const [promptInput, setPromptInput] = useState('');
  const [bottomExpanded, setBottomExpanded] = useState(false);
  const [sourceCodeInput, setSourceCodeInput] = useState('');
  const [importFileName, setImportFileName] = useState('');

  // Floating adding node parameters
  const [nodeAddingType, setNodeAddingType] = useState<CanonicalNode['type']>('service');
  const [nodeAddingLabel, setNodeAddingLabel] = useState('');
  
  // Workspace Layout States
  const [leftSidebarOpen, setLeftSidebarOpen] = useState(false);
  const [rightSidebarOpen, setRightSidebarOpen] = useState(false);
  const [showDeveloperConsole, setShowDeveloperConsole] = useState(false);
  const [nodeAddingOpen, setNodeAddingOpen] = useState(false);

  // Box Selection and Pan Canvas Drag Modes
  const [dragMode, setDragMode] = useState<'pan' | 'select'>('pan');

  // Local file loader ref
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load user diagrams on mount
  useEffect(() => {
    void store.loadFromApi();
    // Default open a new diagram if none selected
    if (store.order.length > 0 && !store.activeId) {
      store.setActive(store.order[0]);
    }
  }, []);

  // Map canonical graph items in Zustand to React Flow compatible formats
  const reactFlowNodes = useMemo(() => {
    return store.nodes.map(n => ({
      id: n.id,
      type: 'customNode',
      position: { x: n.x ?? 0, y: n.y ?? 0 },
      data: {
        id: n.id,
        label: n.label,
        type: n.type,
        shape: n.shape
      }
    }));
  }, [store.nodes]);

  const reactFlowEdges = useMemo(() => {
    return store.edges
      .filter(e => store.nodes.some(n => n.id === e.source) && store.nodes.some(n => n.id === e.target))
      .map(e => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        type: 'smoothstep',
        animated: e.style === 'dotted',
        style: {
          stroke: e.style === 'thick' ? 'var(--accent)' : 'var(--border-strong)',
          strokeWidth: e.style === 'thick' ? 3 : 1.5
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: 'var(--border-strong)',
          width: 16,
          height: 16
        }
      }));
  }, [store.edges, store.nodes]);

  // Canvas callbacks
  const onNodesChange = useCallback((changes: any) => {
    const currentNodes = useDiagramStore.getState().nodes;
    const nextNodes = currentNodes.map(n => {
      const positionChange = changes.find((c: any) => c.id === n.id && c.type === 'position');
      if (positionChange && positionChange.position) {
        return {
          ...n,
          x: Math.round(positionChange.position.x),
          y: Math.round(positionChange.position.y)
        };
      }
      return n;
    });

    // Check if dragging truly modified coordinate parameters before updating store
    const hasCoordinatesChanged = nextNodes.some((n, i) => n.x !== currentNodes[i].x || n.y !== currentNodes[i].y);
    if (hasCoordinatesChanged) {
      useDiagramStore.getState().setNodes(nextNodes);
    }
  }, []);

  const onConnect = useCallback((connection: Connection) => {
    if (connection.source && connection.target) {
      store.addEdge({
        source: connection.source,
        target: connection.target,
        style: 'solid'
      });
    }
  }, [store]);

  const handleCreateNew = () => {
    const id = store.createDiagram('New Architecture', 'flowchart');
    store.setActive(id);
    setActiveTab('saves');
    if (isMobile) setLeftSidebarOpen(false);
  };

  const handlePromptSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!promptInput.trim()) return;
    void store.triggerAIGeneration(promptInput);
    setPromptInput('');
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      setSourceCodeInput(text);
      setImportFileName(file.name);
    };
    reader.readAsText(file);
  };

  const handleImportSubmit = () => {
    if (!sourceCodeInput.trim()) return;
    void store.importFromCode(sourceCodeInput, importFileName || 'source_code.txt');
    setSourceCodeInput('');
    setImportFileName('');
    if (isMobile) setLeftSidebarOpen(false);
  };

  // Standalone SVG export via Mermaid (inlines all styles so it never opens blank)
  const exportSvgFile = async () => {
    const code = store.mermaidCode?.trim();
    if (!code) return;

    try {
      mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' });
      const renderId = `svg-export-${Math.random().toString(36).slice(2, 9)}`;
      const { svg } = await mermaid.render(renderId, code);

      // Ensure standalone compatibility: add XML prolog and guarantee xmlns
      let standalone = svg;
      if (!standalone.includes('xmlns="http://www.w3.org/2000/svg"')) {
        standalone = standalone.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
      }
      const xml = `<?xml version="1.0" encoding="UTF-8"?>\n${standalone}`;

      const blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${store.title.toLowerCase().replace(/\s+/g, '_')}_architecture.svg`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('SVG export failed:', err);
      alert('Failed to export SVG. Make sure the diagram has valid Mermaid code.');
    }
  };

  // HD PNG export: render Mermaid SVG to canvas at 3x scale
  const exportPngFile = async () => {
    const code = store.mermaidCode?.trim();
    if (!code) return;

    try {
      mermaid.initialize({
        startOnLoad: false,
        theme: 'default',
        securityLevel: 'loose',
        flowchart: { htmlLabels: false, useMaxWidth: true },
      });

      const renderId = `png-export-${Math.random().toString(36).slice(2, 9)}`;
      const { svg } = await mermaid.render(renderId, code);

      // Sanitize: strip foreignObject / external references that taint canvas
      let standalone = svg
        .replace(/<foreignObject[\s\S]*?<\/foreignObject>/gi, '')
        .replace(/@import\s+url\([^)]+\);?/gi, '');

      if (!standalone.includes('xmlns="http://www.w3.org/2000/svg"')) {
        standalone = standalone.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
      }

      // Parse viewBox to set explicit width/height so the <img> doesn't
      // default to 300x150 and clip the diagram.
      const parser = new DOMParser();
      const svgDoc = parser.parseFromString(standalone, 'image/svg+xml');
      const svgEl = svgDoc.querySelector('svg');
      let svgW = 0;
      let svgH = 0;
      const vb = svgEl?.getAttribute('viewBox');
      if (vb) {
        const parts = vb.split(/\s+/).map(Number);
        svgW = parts[2];
        svgH = parts[3];
      } else {
        svgW = parseFloat(svgEl?.getAttribute('width') || '0');
        svgH = parseFloat(svgEl?.getAttribute('height') || '0');
      }
      if (svgW > 0 && svgH > 0) {
        svgEl?.setAttribute('width', String(svgW));
        svgEl?.setAttribute('height', String(svgH));
      }
      const serialized = new XMLSerializer().serializeToString(svgDoc);

      const xml = `<?xml version="1.0" encoding="UTF-8"?>\n${serialized}`;
      const svgBlob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' });
      const svgUrl = URL.createObjectURL(svgBlob);

      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        const scale = 3;
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth * scale;
        canvas.height = img.naturalHeight * scale;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.scale(scale, scale);
        ctx.drawImage(img, 0, 0);

        canvas.toBlob((blob) => {
          if (!blob) return;
          const pngUrl = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = pngUrl;
          link.download = `${store.title.toLowerCase().replace(/\s+/g, '_')}_architecture_hd.png`;
          link.click();
          URL.revokeObjectURL(pngUrl);
          URL.revokeObjectURL(svgUrl);
        }, 'image/png');
      };
      img.onerror = () => {
        URL.revokeObjectURL(svgUrl);
        alert('Failed to rasterize diagram for PNG export.');
      };
      img.src = svgUrl;
    } catch (err) {
      console.error('PNG export failed:', err);
      alert('Failed to export PNG. Make sure the diagram has valid Mermaid code.');
    }
  };

  // JSON Downloader
  const exportJsonFile = () => {
    const canonicalGraph = {
      nodes: store.nodes,
      edges: store.edges,
      metadata: {
        title: store.title,
        diagramType: store.diagramType,
        updatedAt: Date.now()
      }
    };

    const blob = new Blob([JSON.stringify(canonicalGraph, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${store.title.toLowerCase().replace(/\s+/g, '_')}_graph.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  // Sidebar styles for mobile: fixed overlays that slide in/out via
  // transform (GPU-composited, 60fps) instead of width animation.
  const leftSidebarStyle: React.CSSProperties = isMobile
    ? {
        position: 'fixed',
        top: 0,
        bottom: 0,
        left: 0,
        width: 'min(88vw, 340px)',
        zIndex: 50,
        boxShadow: '0 24px 48px rgba(0,0,0,0.35)',
        willChange: 'transform',
        transform: leftSidebarOpen ? 'translateX(0)' : 'translateX(-101%)',
      }
    : {
        width: 320,
        borderRight: '1px solid var(--border)',
      };

  const rightSidebarStyle: React.CSSProperties = isMobile
    ? {
        position: 'fixed',
        top: 0,
        bottom: 0,
        right: 0,
        width: 'min(88vw, 340px)',
        zIndex: 50,
        boxShadow: '0 24px 48px rgba(0,0,0,0.35)',
        willChange: 'transform',
        transform: rightSidebarOpen ? 'translateX(0)' : 'translateX(101%)',
      }
    : {
        width: 320,
        borderLeft: '1px solid var(--border)',
      };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] overflow-hidden relative" style={{ background: 'var(--bg)', color: 'var(--text)' }}>

      {/* Mobile backdrops */}
      {isMobile && leftSidebarOpen && (
        <div
          onClick={() => setLeftSidebarOpen(false)}
          className="fixed inset-0 bg-black/50 backdrop-blur-[2px]"
          style={{ zIndex: 40 }}
          aria-hidden="true"
        />
      )}
      {isMobile && rightSidebarOpen && (
        <div
          onClick={() => setRightSidebarOpen(false)}
          className="fixed inset-0 bg-black/50 backdrop-blur-[2px]"
          style={{ zIndex: 40 }}
          aria-hidden="true"
        />
      )}

      {/* ── LEFT SIDEBAR (Templates, Saved, File Context) ── */}
      {(leftSidebarOpen || isMobile) && (
        <aside
          className="border-r flex flex-col shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] overflow-hidden"
          style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)', ...leftSidebarStyle }}
        >
          
          {/* Tabs selector */}
          <div className="flex border-b text-[12px] font-medium relative items-center" style={{ borderColor: 'var(--border)' }}>
            <button
              onClick={() => setActiveTab('templates')}
              className="flex-1 py-3 text-center border-b-2 transition-colors flex items-center justify-center gap-1.5"
              style={{
                borderColor: activeTab === 'templates' ? 'var(--accent)' : 'transparent',
                color: activeTab === 'templates' ? 'var(--accent)' : 'var(--text-muted)'
              }}
            >
              <Compass size={14} /> Blueprints
            </button>
            <button
              onClick={() => setActiveTab('saves')}
              className="flex-1 py-3 text-center border-b-2 transition-colors flex items-center justify-center gap-1.5"
              style={{
                borderColor: activeTab === 'saves' ? 'var(--accent)' : 'transparent',
                color: activeTab === 'saves' ? 'var(--accent)' : 'var(--text-muted)'
              }}
            >
              <FloppyDiskBack size={14} /> Workspace
            </button>
            <button
              onClick={() => setActiveTab('import')}
              className="flex-1 py-3 text-center border-b-2 transition-colors flex items-center justify-center gap-1.5"
              style={{
                borderColor: activeTab === 'import' ? 'var(--accent)' : 'transparent',
                color: activeTab === 'import' ? 'var(--accent)' : 'var(--text-muted)'
              }}
            >
              <FileCode size={14} /> Code Import
            </button>
            {/* Mobile close button */}
            <button
              onClick={() => setLeftSidebarOpen(false)}
              className="md:hidden absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--bg)]"
              aria-label="Close sidebar"
            >
              <X size={16} weight="bold" />
            </button>
          </div>

          {/* Tab content panel */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            
            {/* TAB 1: BLUEPRINTS */}
            {activeTab === 'templates' && (
              <div className="space-y-3">
                <p className="text-[11px] uppercase tracking-wider opacity-60">Architectural Templates</p>
                
                <button
                  onClick={() => {
                    store.createDiagram('MERN App', 'flowchart', 'mern');
                    if (isMobile) setLeftSidebarOpen(false);
                  }}
                  className="w-full text-left p-3 rounded-lg border transition-all hover:bg-[var(--bg)]"
                  style={{ borderColor: 'var(--border-strong)' }}
                >
                  <div className="font-semibold text-xs mb-0.5 text-[var(--accent)]">MERN Stack Architecture</div>
                  <div className="text-[10px] text-[var(--text-muted)]">Single Page React client feeding NodeJS services and a Mongo DB.</div>
                </button>

                <button
                  onClick={() => {
                    store.createDiagram('Microservices App', 'flowchart-lr', 'microservices');
                    if (isMobile) setLeftSidebarOpen(false);
                  }}
                  className="w-full text-left p-3 rounded-lg border transition-all hover:bg-[var(--bg)]"
                  style={{ borderColor: 'var(--border-strong)' }}
                >
                  <div className="font-semibold text-xs mb-0.5 text-emerald-500">Spring Cloud Microservices</div>
                  <div className="text-[10px] text-[var(--text-muted)]">Spring Cloud Gateway, Auth servers, independent databases and Kafka queues.</div>
                </button>

                <button
                  onClick={() => {
                    store.createDiagram('Event Driven App', 'flowchart', 'event_driven');
                    if (isMobile) setLeftSidebarOpen(false);
                  }}
                  className="w-full text-left p-3 rounded-lg border transition-all hover:bg-[var(--bg)]"
                  style={{ borderColor: 'var(--border-strong)' }}
                >
                  <div className="font-semibold text-xs mb-0.5 text-amber-500">Event Driven Pipeline</div>
                  <div className="text-[10px] text-[var(--text-muted)]">API Ingestion webhook pumping messaging queues for parallel cloud analytics.</div>
                </button>

                <button
                  onClick={() => {
                    store.createDiagram('CI/CD Pipeline', 'flowchart-lr', 'ci_cd');
                    if (isMobile) setLeftSidebarOpen(false);
                  }}
                  className="w-full text-left p-3 rounded-lg border transition-all hover:bg-[var(--bg)]"
                  style={{ borderColor: 'var(--border-strong)' }}
                >
                  <div className="font-semibold text-xs mb-0.5 text-purple-500">CI/CD Deploy Flow</div>
                  <div className="text-[10px] text-[var(--text-muted)]">Mapping GitHub triggers, docker build automation, registries and k8s rolling updates.</div>
                </button>

                <button
                  onClick={() => {
                    store.createDiagram('Clean Domain Arch', 'flowchart', 'clean_arch');
                    if (isMobile) setLeftSidebarOpen(false);
                  }}
                  className="w-full text-left p-3 rounded-lg border transition-all hover:bg-[var(--bg)]"
                  style={{ borderColor: 'var(--border-strong)' }}
                >
                  <div className="font-semibold text-xs mb-0.5 text-rose-500">Clean DDD Architecture</div>
                  <div className="text-[10px] text-[var(--text-muted)]">Decoupled system layering: UI views, Controllers, UseCases, core business Entities.</div>
                </button>
              </div>
            )}

          {/* TAB 2: SAVED WORKSPACE */}
          {activeTab === 'saves' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-[11px] uppercase tracking-wider opacity-60">Saved Diagrams</p>
                <button
                  onClick={handleCreateNew}
                  className="flex items-center gap-1 text-[11px] rounded-full px-2.5 py-1 transition-colors"
                  style={{ color: 'var(--accent)', border: '1px solid var(--accent-ring)' }}
                >
                  <Plus size={11} weight="bold" /> New Diagram
                </button>
              </div>

              {!store.loaded ? (
                <div className="text-[12px] opacity-60 italic py-6">Loading studio history...</div>
              ) : Object.keys(store.diagrams).length === 0 ? (
                <div className="text-[11px] opacity-60 italic py-6 text-center border rounded-lg border-dashed p-4" style={{ borderColor: 'var(--border)' }}>
                  No saved diagrams found. Click 'New Diagram' to begin your first canvas workspace!
                </div>
              ) : (
                <div className="space-y-1.5">
                  {store.order.map(id => {
                    const diag = store.diagrams[id];
                    if (!diag) return null;
                    const isActive = store.activeId === id;
                    
                    return (
                      <div
                        key={id}
                        onClick={() => {
                          store.setActive(id);
                          if (isMobile) setLeftSidebarOpen(false);
                        }}
                        className="group flex items-center justify-between p-2.5 rounded-lg cursor-pointer transition-colors"
                        style={{
                          background: isActive ? 'var(--accent-soft)' : 'transparent',
                          color: isActive ? 'var(--accent)' : 'var(--text-muted)'
                        }}
                      >
                        <div className="flex-1 min-w-0 pr-2">
                          <div className="text-[13px] font-semibold truncate" style={{ color: isActive ? 'var(--accent)' : 'var(--text)' }}>
                            {diag.title}
                          </div>
                          <div className="text-[10px] opacity-70">
                            {diag.nodes?.length || 0} nodes · {diag.diagramType}
                          </div>
                        </div>

                        {/* Delete diagram row */}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (window.confirm('Delete this diagram permanently?')) {
                              void store.deleteDiagram(id);
                            }
                          }}
                          className="p-1 rounded-md opacity-0 group-hover:opacity-100 hover:bg-[var(--danger-soft)] hover:text-[var(--danger)] transition-all"
                        >
                          <TrashSimple size={13} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* TAB 3: FILE IMPORT */}
          {activeTab === 'import' && (
            <div className="space-y-3.5">
              <p className="text-[11px] uppercase tracking-wider opacity-60">Source File Parsing</p>
              
              <div
                onClick={() => fileInputRef.current?.click()}
                className="border-2 border-dashed rounded-lg p-5 text-center cursor-pointer transition-colors hover:bg-[var(--bg)]"
                style={{ borderColor: 'var(--border)' }}
              >
                <UploadSimple size={24} className="mx-auto mb-2 opacity-70" />
                <div className="text-xs font-semibold">Upload Context Asset</div>
                <div className="text-[9px] text-[var(--text-muted)] mt-1">Accepts swagger files, markdown dependencies, class diagrams, .js, .py, or .ts</div>
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleFileUpload}
                  className="hidden"
                />
              </div>

              {importFileName && (
                <div className="p-2 border rounded-md text-[11px] flex items-center justify-between" style={{ borderColor: 'var(--border)' }}>
                  <span className="truncate pr-2 font-medium">{importFileName}</span>
                  <button onClick={() => { setImportFileName(''); setSourceCodeInput(''); }} className="text-red-500 hover:scale-105">
                    <X size={12} weight="bold" />
                  </button>
                </div>
              )}

              <div className="space-y-1.5">
                <label className="text-[11px] opacity-60 font-semibold">Or Paste Specifications Directly:</label>
                <textarea
                  value={sourceCodeInput}
                  onChange={(e) => setSourceCodeInput(e.target.value)}
                  placeholder="Paste OpenAPI spec, controller dependency files, or class specifications here..."
                  className="w-full h-40 rounded-lg p-2.5 text-[11px] font-mono outline-none border focus:ring-1 bg-[var(--bg)]"
                  style={{ borderColor: 'var(--border)' }}
                />
              </div>

              <button
                onClick={handleImportSubmit}
                disabled={!sourceCodeInput.trim() || store.isGenerating}
                className="w-full py-2 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50"
                style={{
                  background: 'var(--accent)',
                  color: 'white'
                }}
              >
                {store.isGenerating ? 'Analyzing...' : 'Parse & Visualize Architecture'}
              </button>
            </div>
          )}

        </div>
      </aside>
    )}

      {/* ── CENTER WORKSPACE CANVAS ── */}
      <section className="flex-1 flex flex-col overflow-hidden relative">
        
        {/* Canvas floating toolbar */}
        <header className="h-12 border-b flex items-center px-4 justify-between bg-[var(--bg-elevated)]" style={{ borderColor: 'var(--border)' }}>
          <div className="flex items-center gap-3">
            <input
              value={store.title}
              onChange={(e) => {
                const val = e.target.value;
                useDiagramStore.setState({ title: val });
                store.saveActiveDiagram();
              }}
              className="bg-transparent border-0 outline-none font-semibold text-sm w-28 sm:w-52 focus:bg-[var(--bg)] px-1 rounded truncate"
              style={{ color: 'var(--text)' }}
            />
            <span className="text-[10px] px-2 py-0.5 rounded border leading-none bg-[var(--bg)]" style={{ borderColor: 'var(--border)' }}>
              {store.diagramType}
            </span>
            <button
              onClick={() => setLeftSidebarOpen(!leftSidebarOpen)}
              className="p-1.5 rounded hover:bg-[var(--bg)] text-[var(--text-muted)] transition-colors ml-1"
              title={leftSidebarOpen ? "Collapse Left Sidebar" : "Expand Left Sidebar"}
            >
              {leftSidebarOpen ? <CaretLeft size={16} /> : <CaretRight size={16} />}
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => store.undo()}
              disabled={store.historyIndex <= 0}
              className="p-1.5 rounded hover:bg-[var(--bg)] text-[var(--text-muted)] disabled:opacity-30"
              title="Undo Action"
            >
              <ArrowCounterClockwise size={16} />
            </button>
            <button
              onClick={() => store.redo()}
              disabled={store.historyIndex >= store.historyStack.length - 1}
              className="p-1.5 rounded hover:bg-[var(--bg)] text-[var(--text-muted)] disabled:opacity-30"
              title="Redo Action"
            >
              <ArrowClockwise size={16} />
            </button>
            <div className="h-4 w-px bg-[var(--border)] mx-1" />

            {/* Canvas Interaction Modes (Pan / Multi-Select Toggle) */}
            <div className="flex items-center border rounded bg-[var(--bg)] p-0.5" style={{ borderColor: 'var(--border)' }}>
              <button
                onClick={() => setDragMode('pan')}
                className={`p-1 rounded transition-colors ${dragMode === 'pan' ? 'bg-[var(--accent)] text-white' : 'text-[var(--text-muted)] hover:bg-[var(--bg-elevated)]'}`}
                style={dragMode === 'pan' ? { color: 'var(--bg-elevated)' } : {}}
                title="Pan Mode (Drag canvas to move, hold Shift to select multiple)"
              >
                <Hand size={14} />
              </button>
              <button
                onClick={() => setDragMode('select')}
                className={`p-1 rounded transition-colors ${dragMode === 'select' ? 'bg-[var(--accent)] text-white' : 'text-[var(--text-muted)] hover:bg-[var(--bg-elevated)]'}`}
                style={dragMode === 'select' ? { color: 'var(--bg-elevated)' } : {}}
                title="Box Select Mode (Drag canvas to draw selection box and select multiple)"
              >
                <CursorClick size={14} />
              </button>
            </div>

            <div className="h-4 w-px bg-[var(--border)] mx-1 hidden sm:block" />

            {/* Align buttons - hidden on mobile to save space */}
            <button
              onClick={() => store.autoArrange('TD')}
              className="hidden sm:flex px-2 py-1 text-xs rounded hover:bg-[var(--bg)] items-center gap-1 border"
              style={{ borderColor: 'var(--border)' }}
              title="Auto Layout Top-to-Bottom"
            >
              <TreeStructure size={14} /> <span className="hidden sm:inline">Align TD</span>
            </button>
            <button
              onClick={() => store.autoArrange('LR')}
              className="hidden sm:flex px-2 py-1 text-xs rounded hover:bg-[var(--bg)] items-center gap-1 border"
              style={{ borderColor: 'var(--border)' }}
              title="Auto Layout Left-to-Right"
            >
              <TreeStructure size={14} className="rotate-90" /> <span className="hidden sm:inline">Align LR</span>
            </button>

            {/* Clear Canvas Action */}
            <button
              onClick={() => {
                if (window.confirm("Are you sure you want to clear the entire canvas? This will delete all nodes and edges from this draft workspace.")) {
                  store.clearCanvas();
                }
              }}
              className="px-2 py-1 text-xs rounded hover:bg-[var(--danger-soft)] text-[var(--danger)] hover:text-white flex items-center gap-1 border hover:bg-[var(--danger)] transition-all ml-1"
              style={{ borderColor: 'var(--border)' }}
              title="Delete all nodes and edges from active canvas"
            >
              <TrashSimple size={14} /> <span className="hidden sm:inline">Clear</span>
            </button>

            <div className="h-4 w-px bg-[var(--border)] mx-1 hidden sm:block" />

            {/* Developer console - hidden on mobile to save space */}
            <button
              onClick={() => {
                const val = !showDeveloperConsole;
                setShowDeveloperConsole(val);
                if (val) setBottomExpanded(true);
              }}
              className={`hidden sm:block p-1.5 rounded hover:bg-[var(--bg)] transition-colors ${showDeveloperConsole ? 'text-[var(--accent)] bg-[var(--bg)]' : 'text-[var(--text-muted)]'}`}
              title="Toggle Developer Console"
            >
              <Terminal size={16} />
            </button>

            <button
              onClick={() => setRightSidebarOpen(!rightSidebarOpen)}
              className="p-1.5 rounded hover:bg-[var(--bg)] text-[var(--text-muted)] transition-colors"
              title={rightSidebarOpen ? "Collapse Right Sidebar" : "Expand Right Sidebar"}
            >
              {rightSidebarOpen ? <CaretRight size={16} /> : <CaretLeft size={16} />}
            </button>
          </div>
        </header>

        {/* Floating Manual Node Addition Popover */}
        <div className="absolute top-16 left-4 z-10 flex flex-col gap-2 items-start">
          <button
            onClick={() => setNodeAddingOpen(!nodeAddingOpen)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold shadow-md transition-all hover:shadow-lg bg-[var(--accent)] text-white hover:bg-[var(--accent-ring)] animate-fade-in"
            title="Add Custom Element Node"
          >
            <Plus size={14} weight="bold" /> Add Element
          </button>

          {nodeAddingOpen && (
            <div className="p-3 rounded-lg border shadow-lg flex items-center gap-2 bg-[var(--bg-elevated)]" style={{ borderColor: 'var(--border-strong)' }}>
              <select
                value={nodeAddingType}
                onChange={(e) => setNodeAddingType(e.target.value as any)}
                className="text-xs border rounded p-1 outline-none font-semibold bg-[var(--bg-elevated)] text-[var(--text)] border-[var(--border)]"
              >
                <option value="client">UI / Client</option>
                <option value="service">Service Container</option>
                <option value="database">Database System</option>
                <option value="cloud">Cloud Boundary</option>
                <option value="queue">Event Queue</option>
                <option value="gatekeeper">Auth Gateway</option>
              </select>
              <input
                value={nodeAddingLabel}
                onChange={(e) => setNodeAddingLabel(e.target.value)}
                placeholder="Label e.g. Billing Worker"
                className="text-xs border rounded p-1 w-36 outline-none bg-[var(--bg)]"
                style={{ borderColor: 'var(--border)', color: 'var(--text)' }}
              />
              <button
                onClick={() => {
                  if (nodeAddingLabel.trim()) {
                    store.addNode(nodeAddingType, nodeAddingLabel.trim());
                    setNodeAddingLabel('');
                    setNodeAddingOpen(false);
                  }
                }}
                className="p-1 bg-[var(--accent)] hover:bg-[var(--accent-ring)] text-white rounded"
                title="Create Custom Node"
              >
                <Plus size={14} weight="bold" />
              </button>
            </div>
          )}
        </div>

        {/* canvas render viewport */}
        <div className="flex-1 min-h-0 bg-[var(--bg)] relative">
          {store.activeId ? (
            <ReactFlow
              nodes={reactFlowNodes}
              edges={reactFlowEdges}
              onNodesChange={onNodesChange}
              onConnect={onConnect}
              nodeTypes={nodeTypes}
              colorMode={theme}
              fitView
              snapToGrid
              snapGrid={[15, 15]}
              panOnDrag={dragMode === 'pan'}
              selectionOnDrag={dragMode === 'select'}
              selectionKeyCode={dragMode === 'select' ? null : 'Shift'}
            >
              <Background gap={15} size={1} color="var(--border-strong)" />
              <Controls className="!bg-[var(--bg-elevated)] !border-[var(--border)] !shadow-lg" />
              <MiniMap
                nodeColor={(n: any) => {
                  const nodeData = store.nodes.find(orig => orig.id === n.id);
                  return nodeData ? getNodeConfig(nodeData.type).color : 'var(--border)';
                }}
                className="!bg-[var(--bg-elevated)] !border-[var(--border)]"
                maskColor="rgba(var(--bg), 0.2)"
              />
            </ReactFlow>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center p-6">
              <TreeStructure size={48} className="opacity-40 mb-3" />
              <h2 className="text-sm font-semibold mb-1">Architecture Studio Canvas</h2>
              <p className="text-[11px] text-[var(--text-muted)] max-w-sm mb-4">
                Deploy templates from the blueprints explorer, select a workspace draft, or prompt the AI Architect to model complex systems on the visual interface.
              </p>
              <button
                onClick={handleCreateNew}
                className="px-4 py-2 bg-[var(--accent)] text-white font-medium rounded-lg text-xs hover:bg-[var(--accent-ring)] transition-colors"
              >
                Create Fresh Workspace
              </button>
            </div>
          )}
        </div>

        {/* ── BOTTOM EDITOR DRAWER (Mermaid Source & JSON Schema) ── */}
        <div
          className="border-t flex flex-col transition-all duration-300"
          style={{
            height: bottomExpanded ? (isMobile ? 160 : 260) : 36,
            borderColor: 'var(--border)',
            background: 'var(--bg-elevated)',
            display: showDeveloperConsole ? 'flex' : 'none'
          }}
        >
          {/* Drawer Header Toggle */}
          <div className="h-9 px-4 flex items-center justify-between border-b shrink-0 cursor-pointer" style={{ borderColor: 'var(--border)' }} onClick={() => setBottomExpanded(!bottomExpanded)}>
            <div className="flex items-center gap-4 text-xs font-semibold">
              <button
                onClick={(e) => { e.stopPropagation(); setBottomTab('source'); setBottomExpanded(true); }}
                className="transition-colors flex items-center gap-1.5"
                style={{ color: bottomTab === 'source' ? 'var(--accent)' : 'var(--text-muted)' }}
              >
                Mermaid Markup
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setBottomTab('json'); setBottomExpanded(true); }}
                className="transition-colors flex items-center gap-1.5"
                style={{ color: bottomTab === 'json' ? 'var(--accent)' : 'var(--text-muted)' }}
              >
                Canonical Graph Model
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); setBottomTab('logs'); setBottomExpanded(true); }}
                className="transition-colors flex items-center gap-1.5"
                style={{ color: bottomTab === 'logs' ? 'var(--accent)' : 'var(--text-muted)' }}
              >
                Console Logs
              </button>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-[10px] text-[var(--text-muted)] italic font-normal mr-2">
                {store.parsingLogs.slice(0, 48)}{store.parsingLogs.length > 48 ? '...' : ''}
              </span>
              {bottomExpanded ? <CaretDown size={14} /> : <CaretUp size={14} />}
            </div>
          </div>

          {/* Drawer tabs content */}
          {bottomExpanded && (
            <div className="flex-1 min-h-0 p-3">
              {bottomTab === 'source' && (
                <textarea
                  value={store.mermaidCode}
                  onChange={(e) => store.syncMermaidToGraph(e.target.value)}
                  placeholder="flowchart TD\n    A[Client] --> B[Server]"
                  className="w-full h-full font-mono text-[11px] p-3 rounded-lg border outline-none bg-[var(--bg)] resize-none"
                  style={{ borderColor: 'var(--border)', color: 'var(--text)' }}
                />
              )}

              {bottomTab === 'json' && (
                <pre className="w-full h-full font-mono text-[10px] p-3 rounded-lg border overflow-auto bg-[var(--bg)] resize-none" style={{ borderColor: 'var(--border)' }}>
                  {JSON.stringify(
                    {
                      nodes: store.nodes,
                      edges: store.edges,
                      metadata: { title: store.title, diagramType: store.diagramType }
                    },
                    null,
                    2
                  )}
                </pre>
              )}

              {bottomTab === 'logs' && (
                <div className="w-full h-full font-mono text-[11px] p-3 rounded-lg border overflow-y-auto bg-black text-green-400 border-neutral-800">
                  <div className="text-[9px] text-gray-500 mb-1">=== DIAGNOSTIC CONSOLE COMPILER ===</div>
                  <div>&gt; [Compiler Status]: Active</div>
                  <div>&gt; [System Timestamp]: {new Date().toISOString()}</div>
                  <div className="mt-1 font-semibold text-white">&gt; [Console Message]: {store.parsingLogs}</div>
                  <div className="mt-2 text-gray-400 font-sans text-[10px]">
                    Note: Manual node additions or drag position drops automatically updates coordinates inside your local graph models.
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* ── RIGHT SIDEBAR (AI Prompts & Architecture Analysis) ── */}
      {(rightSidebarOpen || isMobile) && (
        <aside
          className="border-l flex flex-col shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] overflow-hidden"
          style={{ background: 'var(--bg-elevated)', borderColor: 'var(--border)', ...rightSidebarStyle }}
        >
        
        {/* Sidebar Tab Selectors */}
        <div className="flex border-b text-[12px] font-medium shrink-0 relative items-center" style={{ borderColor: 'var(--border)' }}>
          <button
            onClick={() => setRightTab('copilot')}
            className="flex-1 py-3 text-center border-b-2 transition-colors flex items-center justify-center gap-1.5"
            style={{
              borderColor: rightTab === 'copilot' ? 'var(--accent)' : 'transparent',
              color: rightTab === 'copilot' ? 'var(--accent)' : 'var(--text-muted)'
            }}
          >
            <Sparkle size={14} weight={rightTab === 'copilot' ? 'fill' : 'regular'} /> Copilot
          </button>
          <button
            onClick={() => setRightTab('audit')}
            className="flex-1 py-3 text-center border-b-2 transition-colors flex items-center justify-center gap-1.5"
            style={{
              borderColor: rightTab === 'audit' ? 'var(--accent)' : 'transparent',
              color: rightTab === 'audit' ? 'var(--accent)' : 'var(--text-muted)'
            }}
          >
            <Warning size={14} weight={rightTab === 'audit' ? 'fill' : 'regular'} /> Audit
          </button>
          {/* Mobile close button */}
          <button
            onClick={() => setRightSidebarOpen(false)}
            className="md:hidden absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--bg)]"
            aria-label="Close sidebar"
          >
            <X size={16} weight="bold" />
          </button>
        </div>

        {/* Tab Content area */}
        <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
          
          {/* TAB 1: COPILOT & EXPORTS */}
          {rightTab === 'copilot' && (
            <div className="flex flex-col flex-1 divide-y divide-[var(--border)]">
              
              {/* Prompt form */}
              <div className="p-4 flex flex-col gap-3">
                <div className="flex items-center gap-2">
                  <Sparkle size={16} className="text-[var(--accent)]" weight="fill" />
                  <h3 className="text-xs font-semibold uppercase tracking-wider">AI Copilot Architect</h3>
                </div>

                <form onSubmit={handlePromptSubmit} className="flex flex-col gap-2">
                  <textarea
                    value={promptInput}
                    onChange={(e) => setPromptInput(e.target.value)}
                    placeholder="e.g. Add an AWS SQS queue between Core API and Billing Service, or redraw this system as LR..."
                    className="w-full h-28 rounded-lg p-2.5 text-xs outline-none border focus:ring-1 bg-[var(--bg)]"
                    style={{ borderColor: 'var(--border)', color: 'var(--text)' }}
                  />
                  <button
                    type="submit"
                    disabled={!promptInput.trim() || store.isGenerating}
                    className="w-full py-2.5 bg-[var(--accent)] hover:bg-[var(--accent-ring)] text-white text-xs font-semibold rounded-lg flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50"
                  >
                    {store.isGenerating ? (
                      <>Designing Workspace...</>
                    ) : (
                      <>
                        <Sparkle size={14} weight="fill" /> Generate / Evolve Diagram
                      </>
                    )}
                  </button>
                </form>
              </div>

              {/* Export details */}
              <div className="p-4 flex flex-col gap-3">
                <p className="text-[10px] uppercase font-bold tracking-wider opacity-60">Export Deliverables</p>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => void exportSvgFile()}
                    disabled={!store.activeId}
                    className="py-2 border rounded text-xs hover:bg-[var(--bg)] flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50 text-[var(--text)]"
                    style={{ borderColor: 'var(--border)' }}
                  >
                    <Export size={13} /> SVG File
                  </button>
                  <button
                    onClick={() => void exportPngFile()}
                    disabled={!store.activeId}
                    className="py-2 border rounded text-xs hover:bg-[var(--bg)] flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50 text-[var(--text)]"
                    style={{ borderColor: 'var(--border)' }}
                  >
                    <Images size={13} /> HD PNG
                  </button>
                </div>
                <button
                  onClick={exportJsonFile}
                  disabled={!store.activeId}
                  className="w-full py-2 text-xs rounded border hover:bg-[var(--bg)] transition-colors flex items-center justify-center gap-1.5 disabled:opacity-50 text-[var(--text)]"
                  style={{ borderColor: 'var(--border)' }}
                >
                  <DownloadSimple size={13} /> Graph JSON
                </button>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(store.mermaidCode);
                    alert('Copied Mermaid flowchart syntax to clipboard.');
                  }}
                  disabled={!store.activeId}
                  className="w-full py-2 text-xs rounded border hover:bg-[var(--bg)] transition-colors flex items-center justify-center gap-1.5 disabled:opacity-50 text-[var(--text)]"
                  style={{ borderColor: 'var(--border)' }}
                >
                  Copy Mermaid Syntax
                </button>
              </div>

            </div>
          )}

          {/* TAB 2: QUALITY AUDITS */}
          {rightTab === 'audit' && (
            <div className="p-4 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Warning size={16} className="text-amber-500" />
                  <h3 className="text-xs font-semibold uppercase tracking-wider">System Audit Report</h3>
                </div>
                
                <button
                  onClick={() => void store.triggerAIAnalysis()}
                  disabled={store.isAnalyzing || !store.activeId}
                  className="text-[10px] text-[var(--accent)] hover:underline disabled:opacity-40 font-semibold"
                >
                  {store.isAnalyzing ? 'Auditing...' : 'Run Audit'}
                </button>
              </div>

              {store.analysis ? (
                <div className="space-y-4">
                  {/* Score ring */}
                  <div className="flex items-center gap-3 p-3 rounded-lg border bg-[var(--bg)]" style={{ borderColor: 'var(--border)' }}>
                    <div
                      className="w-12 h-12 rounded-full border-4 flex items-center justify-center font-bold text-sm shrink-0"
                      style={{
                        borderColor: store.analysis.architecture_score >= 80 ? '#10b981' : (store.analysis.architecture_score >= 50 ? '#f59e0b' : '#ef4444'),
                        color: store.analysis.architecture_score >= 80 ? '#10b981' : (store.analysis.architecture_score >= 50 ? '#f59e0b' : '#ef4444'),
                      }}
                    >
                      {store.analysis.architecture_score}
                    </div>
                    <div>
                      <div className="text-xs font-semibold">Architecture Health Score</div>
                      <div className="text-[10px] opacity-75 leading-tight">Generated using contextual software model analyzers.</div>
                    </div>
                  </div>

                  {/* Cyclic dependencies */}
                  <div className="space-y-1">
                    <div className="text-[10px] uppercase font-bold tracking-wider opacity-60">Cycles & Cohesions</div>
                    {store.analysis.cyclic_dependencies?.length > 0 ? (
                      <div className="space-y-1">
                        {store.analysis.cyclic_dependencies.map((cycle, i) => (
                          <div key={i} className="text-[11px] p-2 rounded bg-red-500/10 border border-red-500/20 text-red-500 flex items-start gap-1.5">
                            <Warning size={12} className="shrink-0 mt-0.5" />
                            <span>{cycle}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-[10px] p-2 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 leading-tight">
                        No circular dependencies detected. Solid modular boundaries.
                      </div>
                    )}
                  </div>

                  {/* Single Points of Failure */}
                  <div className="space-y-1">
                    <div className="text-[10px] uppercase font-bold tracking-wider opacity-60">Security & Scale Bottlenecks</div>
                    {store.analysis.bottlenecks?.length > 0 ? (
                      <ul className="space-y-1 pl-0">
                        {store.analysis.bottlenecks.map((bottleneck, i) => (
                          <li key={i} className="text-[11px] p-2 rounded bg-amber-500/10 border border-amber-500/20 text-amber-600 dark:text-amber-400 flex items-start gap-1.5 list-none">
                            <Warning size={12} className="shrink-0 mt-0.5" />
                            <span>{bottleneck}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <div className="text-[10px] p-2 rounded bg-gray-500/10 text-gray-400 italic">No structural bottlenecks flagged.</div>
                    )}
                  </div>

                  {/* Suggestions */}
                  <div className="space-y-1">
                    <div className="text-[10px] uppercase font-bold tracking-wider opacity-60">Architectural Upgrades</div>
                    <div className="space-y-1">
                      {store.analysis.suggestions?.map((sug, i) => (
                        <div key={i} className="text-[11px] p-2.5 rounded bg-[var(--bg)] border text-[var(--text-muted)] leading-tight" style={{ borderColor: 'var(--border)' }}>
                          {sug}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-[11px] text-[var(--text-muted)] text-center py-8 italic border rounded-lg border-dashed p-4" style={{ borderColor: 'var(--border)' }}>
                  Click 'Run Audit' above to evaluate system cohesion, coupling coefficients, bottlenecks, and security.
                </div>
              )}
            </div>
          )}

        </div>
      </aside>
    )}

    </div>
  );
}
