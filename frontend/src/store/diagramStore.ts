import { create } from 'zustand';
import { diagramApi, DiagramResponse } from '../lib/api';
import {
  parseMermaidToGraph,
  graphToMermaid,
  applyHierarchicalLayout,
  CanonicalNode,
  CanonicalEdge
} from '../lib/diagramParser';

export interface ArchitectureAnalysis {
  architecture_score: number;
  bottlenecks: string[];
  cyclic_dependencies: string[];
  suggestions: string[];
}

interface HistorySnapshot {
  nodes: CanonicalNode[];
  edges: CanonicalEdge[];
  mermaidCode: string;
  title: string;
  diagramType: string;
  analysis: ArchitectureAnalysis | null;
}

interface DiagramState {
  diagrams: Record<string, DiagramResponse>;
  order: string[];
  activeId: string | null;
  loaded: boolean;

  // Active diagram working variables
  title: string;
  diagramType: string;
  nodes: CanonicalNode[];
  edges: CanonicalEdge[];
  mermaidCode: string;
  analysis: ArchitectureAnalysis | null;

  // AI Loading indicators
  isGenerating: boolean;
  isAnalyzing: boolean;
  parsingLogs: string;

  // Undo/Redo stack
  historyStack: HistorySnapshot[];
  historyIndex: number;

  // Core Actions
  loadFromApi: () => Promise<void>;
  setActive: (id: string | null) => void;
  createDiagram: (title?: string, type?: string, templateKey?: string) => string;
  createDiagramFromMermaid: (title: string, mermaidCode: string) => string;
  deleteDiagram: (id: string) => Promise<void>;
  saveActiveDiagram: (immediate?: boolean) => Promise<void>;

  // Interactive Canvas Canvas Updates
  setNodes: (nodes: CanonicalNode[]) => void;
  setEdges: (edges: CanonicalEdge[]) => void;
  updateNodeLabel: (id: string, label: string) => void;
  addNode: (type: CanonicalNode['type'], label: string, x?: number, y?: number) => void;
  deleteNode: (id: string) => void;
  addEdge: (edge: Omit<CanonicalEdge, 'id'>) => void;
  deleteEdge: (id: string) => void;
  autoArrange: (orientation?: 'TD' | 'LR') => void;
  syncMermaidToGraph: (mermaidCode: string) => void;

  // Undo / Redo
  pushHistory: () => void;
  undo: () => void;
  redo: () => void;

  // AI Generation & Analysis Actions
  triggerAIGeneration: (prompt: string) => Promise<void>;
  importFromCode: (fileContent: string, fileName: string) => Promise<void>;
  triggerAIAnalysis: () => Promise<void>;
}

const uid = () => Math.random().toString(36).slice(2) + Date.now().toString(36);

// Premium Architectural Templates
const TEMPLATES: Record<string, string> = {
  mern: `flowchart TD
    SPA["React SPA (Client)"]
    Gateway["Nginx Load Balancer (Gatekeeper)"]
    AuthService["Auth API Service (Service)"]
    CoreAPI["Node Core API (Service)"]
    Cache["Redis Cache (Database)"]
    Postgres["PostgreSQL Database (Database)"]
    CloudStorage["S3 Media bucket (Cloud)"]

    SPA --> Gateway
    Gateway --> AuthService
    Gateway --> CoreAPI
    CoreAPI --> Cache
    CoreAPI --> Postgres
    CoreAPI --> CloudStorage`,

  microservices: `flowchart LR
    WebClient["Next.js Web Client (Client)"]
    Gateway["Spring Cloud Gateway (Gatekeeper)"]
    AuthServer["OAuth Auth Server (Gatekeeper)"]
    UserService["User Profile Service (Service)"]
    ProductService["Product Catalog Service (Service)"]
    OrderService["Order Checkout Service (Service)"]
    UserDB[("MongoDB (Database)")]
    ProductDB[("MySQL Database (Database)")]
    Broker["Kafka Message Broker (Queue)"]
    NotificationService["Notification Worker (Service)"]

    WebClient --> Gateway
    Gateway --> AuthServer
    Gateway --> UserService
    Gateway --> ProductService
    Gateway --> OrderService
    
    UserService --> UserDB
    ProductService --> ProductDB
    OrderService --> Broker
    Broker --> NotificationService`,

  event_driven: `flowchart TD
    Producer["Webhook Publisher (Client)"]
    Gateway["AWS API Gateway (Gatekeeper)"]
    Broker["Kafka Event Stream (Queue)"]
    IngestWorker["Ingestion lambda (Service)"]
    AnalyticsWorker["Clickstream Processor (Service)"]
    Storage[("DynamoDB (Database)")]
    Telemetry["Grafana Dashboard (Cloud)"]

    Producer --> Gateway
    Gateway --> Broker
    Broker --> IngestWorker
    Broker --> AnalyticsWorker
    IngestWorker --> Storage
    AnalyticsWorker --> Telemetry`,

  ci_cd: `flowchart LR
    Dev["Developer Laptop (Client)"]
    GitHub["GitHub Repo (Cloud)"]
    Runner["GitHub Action Runner (Service)"]
    DockerBuild["Docker Build Pipeline (Service)"]
    Registry["Docker Hub Registry (Cloud)"]
    K8sCluster["Kubernetes Production Cluster (Gatekeeper)"]

    Dev -->|git push| GitHub
    GitHub -->|Webhook trigger| Runner
    Runner --> DockerBuild
    DockerBuild -->|push image| Registry
    Registry -->|deploy rolling update| K8sCluster`,

  clean_arch: `flowchart TD
    UI["Vue Frontend UI (Client)"]
    Controllers["HTTP Presenters & Controllers (Service)"]
    UseCases["Domain Application Use Cases (Service)"]
    Entities["Core Pure Business Entities (Service)"]
    DBRepository["Postgres DB Repository Interface (Database)"]

    UI --> Controllers
    Controllers --> UseCases
    UseCases --> Entities
    UseCases -.-> DBRepository`
};

const SYNC_DEBOUNCE_MS = 1200;
let pendingSaveTimer: ReturnType<typeof setTimeout> | null = null;

export const useDiagramStore = create<DiagramState>((set, get) => {
  
  // Internal helper to sync graph state instantly into Mermaid string
  const _rebuildMermaid = () => {
    const { nodes, edges, diagramType } = get();
    const mermaidCode = graphToMermaid({
      nodes,
      edges,
      metadata: { direction: (diagramType === 'flowchart-lr' ? 'LR' : 'TD') }
    });
    set({ mermaidCode, parsingLogs: 'Synced canvas to source successfully.' });
    get().saveActiveDiagram();
  };

  return {
    diagrams: {},
    order: [],
    activeId: null,
    loaded: false,

    // Active state working variables
    title: 'Untitled Diagram',
    diagramType: 'flowchart',
    nodes: [],
    edges: [],
    mermaidCode: '',
    analysis: null,

    // Loaders
    isGenerating: false,
    isAnalyzing: false,
    parsingLogs: '',

    // Undo/Redo parameters
    historyStack: [],
    historyIndex: -1,

    loadFromApi: async () => {
      try {
        const { data } = await diagramApi.history.list();
        const diagramsMap: Record<string, DiagramResponse> = {};
        const order: string[] = [];
        
        data.forEach(d => {
          diagramsMap[d.id] = d;
          order.push(d.id);
        });

        set({ diagrams: diagramsMap, order, loaded: true });
      } catch {
        set({ loaded: true });
      }
    },

    setActive: (id) => {
      if (id === null) {
        set({
          activeId: null,
          title: 'Untitled Diagram',
          diagramType: 'flowchart',
          nodes: [],
          edges: [],
          mermaidCode: '',
          analysis: null,
          historyStack: [],
          historyIndex: -1
        });
        return;
      }

      const diag = get().diagrams[id];
      if (!diag) return;

      set({
        activeId: id,
        title: diag.title,
        diagramType: diag.diagramType,
        nodes: diag.nodes,
        edges: diag.edges,
        mermaidCode: diag.mermaidCode,
        analysis: diag.metadata?.analysis || null,
        historyStack: [{
          nodes: diag.nodes,
          edges: diag.edges,
          mermaidCode: diag.mermaidCode,
          title: diag.title,
          diagramType: diag.diagramType,
          analysis: diag.metadata?.analysis || null
        }],
        historyIndex: 0
      });
    },

    createDiagram: (title, type, templateKey) => {
      const id = uid();
      const now = Date.now();
      const cleanTitle = title || 'Untitled Diagram';
      const cleanType = type || 'flowchart';

      let baseMermaid = `flowchart TD\n    A["Client"] --> B["Service"]`;
      if (templateKey && TEMPLATES[templateKey]) {
        baseMermaid = TEMPLATES[templateKey];
      }

      // Parse code and run auto layout
      const graph = parseMermaidToGraph(baseMermaid);
      const isLR = templateKey === 'microservices' || templateKey === 'ci_cd';
      const layoutGraph = applyHierarchicalLayout(graph, isLR ? 'LR' : 'TD');
      
      const newDiagram: DiagramResponse = {
        id,
        title: cleanTitle,
        diagramType: isLR ? 'flowchart-lr' : cleanType,
        createdAt: now,
        updatedAt: now,
        nodes: layoutGraph.nodes,
        edges: layoutGraph.edges,
        mermaidCode: baseMermaid,
        metadata: {
          analysis: null
        }
      };

      set(s => ({
        diagrams: { ...s.diagrams, [id]: newDiagram },
        order: [id, ...s.order],
        activeId: id,
        title: newDiagram.title,
        diagramType: newDiagram.diagramType,
        nodes: newDiagram.nodes,
        edges: newDiagram.edges,
        mermaidCode: newDiagram.mermaidCode,
        analysis: null,
        historyStack: [{
          nodes: newDiagram.nodes,
          edges: newDiagram.edges,
          mermaidCode: newDiagram.mermaidCode,
          title: newDiagram.title,
          diagramType: newDiagram.diagramType,
          analysis: null
        }],
        historyIndex: 0
      }));

      // Immediate Sync to server
      void diagramApi.history.save(newDiagram);

      return id;
    },

    createDiagramFromMermaid: (title, mermaidCode) => {
      const id = uid();
      const now = Date.now();
      const cleanTitle = title || 'Imported Diagram';

      let nodes: CanonicalNode[] = [];
      let edges: CanonicalEdge[] = [];
      const isLR = mermaidCode.includes('flowchart LR') || mermaidCode.includes('graph LR');
      
      try {
        const graph = parseMermaidToGraph(mermaidCode);
        const layoutGraph = applyHierarchicalLayout(graph, isLR ? 'LR' : 'TD');
        nodes = layoutGraph.nodes;
        edges = layoutGraph.edges;
      } catch (err) {
        console.error('Failed to parse incoming mermaid for canvas layout:', err);
      }

      const newDiagram: DiagramResponse = {
        id,
        title: cleanTitle,
        diagramType: isLR ? 'flowchart-lr' : 'flowchart',
        createdAt: now,
        updatedAt: now,
        nodes: nodes as any,
        edges: edges as any,
        mermaidCode: mermaidCode,
        metadata: {
          analysis: null
        }
      };

      set(s => ({
        diagrams: { ...s.diagrams, [id]: newDiagram },
        order: [id, ...s.order],
        activeId: id,
        title: newDiagram.title,
        diagramType: newDiagram.diagramType,
        nodes: newDiagram.nodes,
        edges: newDiagram.edges,
        mermaidCode: newDiagram.mermaidCode,
        analysis: null,
        historyStack: [{
          nodes: newDiagram.nodes,
          edges: newDiagram.edges,
          mermaidCode: newDiagram.mermaidCode,
          title: newDiagram.title,
          diagramType: newDiagram.diagramType,
          analysis: null
        }],
        historyIndex: 0
      }));

      // Immediate Sync to server
      void diagramApi.history.save(newDiagram);

      return id;
    },

    deleteDiagram: async (id) => {
      const prev = get();
      const order = prev.order.filter(x => x !== id);
      const activeId = prev.activeId === id ? (order[0] || null) : prev.activeId;

      set(s => {
        const { [id]: _, ...rest } = s.diagrams;
        return { diagrams: rest, order, activeId };
      });

      if (activeId) {
        get().setActive(activeId);
      } else {
        get().setActive(null);
      }

      try {
        await diagramApi.history.delete(id);
      } catch (err) {
        // Rollback state on network error
        set({
          diagrams: prev.diagrams,
          order: prev.order,
          activeId: prev.activeId
        });
        get().setActive(prev.activeId);
        throw err;
      }
    },

    saveActiveDiagram: async (immediate = false) => {
      const { activeId, title, diagramType, nodes, edges, mermaidCode, analysis } = get();
      if (!activeId) return;

      if (pendingSaveTimer) {
        clearTimeout(pendingSaveTimer);
        pendingSaveTimer = null;
      }

      const syncPayload: DiagramResponse = {
        id: activeId,
        title,
        diagramType,
        createdAt: get().diagrams[activeId]?.createdAt || Date.now(),
        updatedAt: Date.now(),
        nodes,
        edges,
        mermaidCode,
        metadata: {
          analysis
        }
      };

      // Optimistic locally updated cache entry
      set(s => ({
        diagrams: { ...s.diagrams, [activeId]: syncPayload }
      }));

      if (immediate) {
        try {
          await diagramApi.history.save(syncPayload);
        } catch {
          // Fail silent, retry later
        }
        return;
      }

      pendingSaveTimer = setTimeout(async () => {
        try {
          await diagramApi.history.save(syncPayload);
        } catch {
          // fail silent
        }
      }, SYNC_DEBOUNCE_MS);
    },

    // ── Canvas Interactive Updaters ──────────────────────────────────────────

    setNodes: (newNodes) => {
      set({ nodes: newNodes });
      // When coordinates are updated via dragging, save changes without instantly regenerating mermaid code
      get().saveActiveDiagram();
    },

    setEdges: (newEdges) => {
      set({ edges: newEdges });
      get().saveActiveDiagram();
    },

    updateNodeLabel: (id, label) => {
      get().pushHistory();
      set(s => ({
        nodes: s.nodes.map(n => n.id === id ? { ...n, label: label.trim() || n.label } : n)
      }));
      _rebuildMermaid();
    },

    addNode: (type, label, x, y) => {
      get().pushHistory();
      const nodeId = `node_${uid().slice(-4)}`;
      const newNode: CanonicalNode = {
        id: nodeId,
        label,
        type,
        shape: type === 'database' ? 'cylinder' : (type === 'gatekeeper' ? 'stadium' : 'box'),
        x: x ?? (100 + Math.random() * 200),
        y: y ?? (100 + Math.random() * 200)
      };

      set(s => ({
        nodes: [...s.nodes, newNode]
      }));
      _rebuildMermaid();
    },

    deleteNode: (id) => {
      get().pushHistory();
      set(s => ({
        nodes: s.nodes.filter(n => n.id !== id),
        edges: s.edges.filter(e => e.source !== id && e.target !== id)
      }));
      _rebuildMermaid();
    },

    addEdge: (edge) => {
      get().pushHistory();
      const edgeId = `e-${edge.source}-${edge.target}-${uid().slice(-3)}`;
      const newEdge: CanonicalEdge = {
        id: edgeId,
        source: edge.source,
        target: edge.target,
        label: edge.label,
        style: edge.style || 'solid'
      };

      set(s => ({
        edges: [...s.edges, newEdge]
      }));
      _rebuildMermaid();
    },

    deleteEdge: (id) => {
      get().pushHistory();
      set(s => ({
        edges: s.edges.filter(e => e.id !== id)
      }));
      _rebuildMermaid();
    },

    autoArrange: (orientation) => {
      get().pushHistory();
      const { nodes, edges, diagramType } = get();
      const dir = orientation || (diagramType === 'flowchart-lr' ? 'LR' : 'TD');
      const arranged = applyHierarchicalLayout({
        nodes,
        edges,
        metadata: { direction: dir }
      }, dir);

      set({
        nodes: arranged.nodes,
        diagramType: dir === 'LR' ? 'flowchart-lr' : 'flowchart'
      });
      _rebuildMermaid();
    },

    syncMermaidToGraph: (code) => {
      if (!code.trim()) return;

      try {
        const parsed = parseMermaidToGraph(code);
        
        // Find if coordinates already exist for matching IDs to prevent visual jumpiness
        const currentNodes = get().nodes;
        const mappedNodes = parsed.nodes.map(n => {
          const matched = currentNodes.find(curr => curr.id === n.id);
          if (matched) {
            return { ...n, x: matched.x, y: matched.y };
          }
          return n;
        });

        // For any nodes that do NOT have coordinates, run auto-arrange
        const needsLayout = mappedNodes.some(n => n.x === undefined || n.y === undefined);
        let finalNodes = mappedNodes;
        if (needsLayout) {
          const arranged = applyHierarchicalLayout({
            nodes: mappedNodes,
            edges: parsed.edges,
            metadata: parsed.metadata
          }, parsed.metadata.direction === 'LR' ? 'LR' : 'TD');
          finalNodes = arranged.nodes;
        }

        set({
          nodes: finalNodes as any,
          edges: parsed.edges,
          mermaidCode: code,
          diagramType: parsed.metadata.direction === 'LR' ? 'flowchart-lr' : 'flowchart',
          parsingLogs: 'Successfully compiled Mermaid source'
        });
        
        get().saveActiveDiagram();
      } catch (err: any) {
        set({ parsingLogs: `Syntax Error: ${err?.message || 'failed to parse'}` });
      }
    },

    // ── Undo / Redo Actions ──────────────────────────────────────────────────

    pushHistory: () => {
      const { nodes, edges, mermaidCode, title, diagramType, analysis, historyStack, historyIndex } = get();
      
      const newSnapshot: HistorySnapshot = {
        nodes: JSON.parse(JSON.stringify(nodes)),
        edges: JSON.parse(JSON.stringify(edges)),
        mermaidCode,
        title,
        diagramType,
        analysis
      };

      // Discard future states if we perform a new action after undoing
      const trimmedStack = historyStack.slice(0, historyIndex + 1);

      set({
        historyStack: [...trimmedStack, newSnapshot],
        historyIndex: trimmedStack.length
      });
    },

    undo: () => {
      const { historyIndex, historyStack } = get();
      if (historyIndex <= 0) return; // Cannot undo past base state

      const prevIdx = historyIndex - 1;
      const snap = historyStack[prevIdx];

      set({
        historyIndex: prevIdx,
        nodes: snap.nodes,
        edges: snap.edges,
        mermaidCode: snap.mermaidCode,
        title: snap.title,
        diagramType: snap.diagramType,
        analysis: snap.analysis
      });

      get().saveActiveDiagram();
    },

    redo: () => {
      const { historyIndex, historyStack } = get();
      if (historyIndex >= historyStack.length - 1) return; // End of redos

      const nextIdx = historyIndex + 1;
      const snap = historyStack[nextIdx];

      set({
        historyIndex: nextIdx,
        nodes: snap.nodes,
        edges: snap.edges,
        mermaidCode: snap.mermaidCode,
        title: snap.title,
        diagramType: snap.diagramType,
        analysis: snap.analysis
      });

      get().saveActiveDiagram();
    },

    // ── AI Capabilities ──────────────────────────────────────────────────────

    triggerAIGeneration: async (prompt) => {
      const { diagramType, activeId, mermaidCode } = get();
      if (!activeId) return;

      set({ isGenerating: true, parsingLogs: 'Generating diagram through AI...' });
      get().pushHistory();

      try {
        const { data } = await diagramApi.generate({
          prompt,
          diagram_type: diagramType === 'flowchart-lr' ? 'LR' : 'TD',
          existing_mermaid: mermaidCode || undefined
        });

        // Run auto arrange on newly AI generated structures
        const rawGraph = {
          nodes: data.nodes || [],
          edges: data.edges || [],
          metadata: { direction: (diagramType === 'flowchart-lr' ? 'LR' : 'TD') as 'LR' | 'TD' }
        };
        const arranged = applyHierarchicalLayout(rawGraph, (diagramType === 'flowchart-lr' ? 'LR' : 'TD') as 'LR' | 'TD');

        set({
          nodes: arranged.nodes,
          edges: arranged.edges,
          mermaidCode: data.mermaid_code || graphToMermaid(arranged),
          analysis: data.analysis || null,
          parsingLogs: 'Successfully drafted diagram through AI Architect'
        });

        get().saveActiveDiagram(true);
      } catch (err: any) {
        set({ parsingLogs: `AI Generation Error: ${err?.response?.data?.detail || err?.message || 'internal server error'}` });
      } finally {
        set({ isGenerating: false });
      }
    },

    importFromCode: async (fileContent, fileName) => {
      const { activeId, diagramType } = get();
      if (!activeId) return;

      set({ isGenerating: true, parsingLogs: 'Analyzing uploaded codebase assets...' });
      get().pushHistory();

      try {
        const { data } = await diagramApi.generate({
          prompt: `Create a dependency and flow architectural diagram that maps out the relationships, services, modules, or structures defined in the uploaded file content.`,
          diagram_type: diagramType === 'flowchart-lr' ? 'LR' : 'TD',
          file_content: fileContent,
          file_name: fileName
        });

        const rawGraph = {
          nodes: data.nodes || [],
          edges: data.edges || [],
          metadata: { direction: (diagramType === 'flowchart-lr' ? 'LR' : 'TD') as 'LR' | 'TD' }
        };
        const arranged = applyHierarchicalLayout(rawGraph, (diagramType === 'flowchart-lr' ? 'LR' : 'TD') as 'LR' | 'TD');

        set({
          title: `Architecture: ${fileName.split('.')[0]}`,
          nodes: arranged.nodes,
          edges: arranged.edges,
          mermaidCode: data.mermaid_code || graphToMermaid(arranged),
          analysis: data.analysis || null,
          parsingLogs: `Successfully modeled architecture from ${fileName}`
        });

        get().saveActiveDiagram(true);
      } catch (err: any) {
        set({ parsingLogs: `Code import failed: ${err?.response?.data?.detail || err?.message}` });
      } finally {
        set({ isGenerating: false });
      }
    },

    triggerAIAnalysis: async () => {
      const { mermaidCode, nodes, edges, activeId } = get();
      if (!activeId) return;

      set({ isAnalyzing: true });
      try {
        const { data } = await diagramApi.analyze({
          mermaid_code: mermaidCode,
          nodes,
          edges
        });

        set({ analysis: data });
        get().saveActiveDiagram(true);
      } catch (err: any) {
        set({ parsingLogs: `AI analysis failed: ${err?.response?.data?.detail || err?.message}` });
      } finally {
        set({ isAnalyzing: false });
      }
    }
  };
});
