// Bi-directional Mermaid Flowchart Parser and Hierarchical Layout Engine

export interface CanonicalNode {
  id: string;
  label: string;
  type: 'client' | 'service' | 'database' | 'cloud' | 'queue' | 'gatekeeper' | 'default';
  shape?: 'box' | 'cylinder' | 'rhombus' | 'circle' | 'stadium' | 'subroutine';
  x?: number;
  y?: number;
}

export interface CanonicalEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  style?: 'solid' | 'dotted' | 'thick';
}

export interface CanonicalGraph {
  nodes: CanonicalNode[];
  edges: CanonicalEdge[];
  metadata: {
    direction: 'TD' | 'LR' | 'TB' | 'RL' | 'BT';
    title?: string;
  };
}

/**
 * Parses a standard Mermaid flowchart into a CanonicalGraph structure.
 */
export function parseMermaidToGraph(mermaid: string): CanonicalGraph {
  const nodesMap = new Map<string, CanonicalNode>();
  const edges: CanonicalEdge[] = [];
  let direction: 'TD' | 'LR' | 'TB' | 'RL' | 'BT' = 'TD';

  if (!mermaid) {
    return { nodes: [], edges: [], metadata: { direction } };
  }

  // Pre-process lines: ignore comments, empty lines, and trim whitespace
  const lines = mermaid
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(line => line.length > 0 && !line.startsWith('%%'));

  // 1. Detect Flowchart direction (flowchart TD, flowchart LR, graph TD, etc.)
  const dirMatch = mermaid.match(/(?:flowchart|graph)\s+(TD|LR|TB|RL|BT)/i);
  if (dirMatch) {
    direction = dirMatch[1].toUpperCase() as any;
  }

  // Helper to register a node with its ID and label + shape
  const registerNode = (id: string, label?: string, rawBrackets?: string) => {
    id = id.trim();
    if (!id) return;

    let shape: CanonicalNode['shape'] = 'box';
    let type: CanonicalNode['type'] = 'default';

    if (rawBrackets) {
      const open = rawBrackets.slice(0, 2);
      const close = rawBrackets.slice(-2);

      if (open.startsWith('[(') && close.endsWith(')]')) {
        shape = 'cylinder';
        type = 'database';
      } else if (open.startsWith('{') && close.endsWith('}')) {
        shape = 'rhombus';
      } else if (open.startsWith('((') && close.endsWith('))')) {
        shape = 'circle';
      } else if (open.startsWith('([') && close.endsWith('])')) {
        shape = 'stadium';
      } else if (open.startsWith('[[') && close.endsWith(']]')) {
        shape = 'subroutine';
      }
    }

    // Infer type from label keywords if not defined
    const cleanLabel = (label || id).replace(/^["']|["']$/g, '').trim();
    if (type === 'default') {
      const lower = cleanLabel.toLowerCase();
      if (lower.includes('db') || lower.includes('database') || lower.includes('postgres') || lower.includes('mysql') || lower.includes('redis') || lower.includes('sql') || lower.includes('cache') || lower.includes('store')) {
        type = 'database';
        shape = 'cylinder';
      } else if (lower.includes('frontend') || lower.includes('app') || lower.includes('ui') || lower.includes('web') || lower.includes('client') || lower.includes('mobile') || lower.includes('dashboard')) {
        type = 'client';
      } else if (lower.includes('auth') || lower.includes('gateway') || lower.includes('security') || lower.includes('gatekeeper') || lower.includes('proxy') || lower.includes('nginx') || lower.includes('firewall') || lower.includes('load balancer') || lower.includes('lb')) {
        type = 'gatekeeper';
      } else if (lower.includes('queue') || lower.includes('kafka') || lower.includes('rabbitmq') || lower.includes('pubsub') || lower.includes('broker') || lower.includes('sqs')) {
        type = 'queue';
      } else if (lower.includes('aws') || lower.includes('stripe') || lower.includes('cloud') || lower.includes('external') || lower.includes('mail') || lower.includes('api.t') || lower.includes('third-party')) {
        type = 'cloud';
      } else {
        type = 'service'; // Default to generic service container
      }
    }

    if (nodesMap.has(id)) {
      const existing = nodesMap.get(id)!;
      // Merge: only overwrite label and shape if they are explicitly parsed
      nodesMap.set(id, {
        ...existing,
        label: label ? cleanLabel : existing.label,
        shape: rawBrackets ? shape : existing.shape,
        type: (type as string) !== 'default' ? type : existing.type,
      });
    } else {
      nodesMap.set(id, {
        id,
        label: cleanLabel,
        type,
        shape,
      });
    }
  };

  // Regex to match inline node label assignments: ID[Label Text], ID(Label Text), etc.
  const inlineNodeRegex = /^([a-zA-Z0-9_\-]+)\s*(\[[\(\[]|\[|\([\(\[]|\(|\{\{|\{|\(\(|\(\[|\[\[)\s*["']?([^"']+)["']?\s*(\]\]|\]\)|\]|\}\}|\}|\)\)|\)\]|\)\])\s*$/;

  for (const line of lines) {
    // Skip line if it's the diagram declaration
    if (line.match(/^(?:flowchart|graph)/i)) continue;

    // Check for inline node definition e.g. A["Node Text"] or DB[(SQL Server)]
    const nodeInline = line.match(inlineNodeRegex);
    if (nodeInline) {
      const [_, id, openBracket, label, closeBracket] = nodeInline;
      const rawBrackets = openBracket + closeBracket;
      registerNode(id, label, rawBrackets);
      continue;
    }

    // Try to parse links (e.g. A --> B or A -->|API Request| B)
    // To support complex syntax, we parse recursively or line by line.
    // Standard link match:
    const linkMatch = line.match(/^([a-zA-Z0-9_\-]+)(.*?)(-->|---|==>|-\.-\.?)\s*(?:\|([^|]+)\|)?\s*([a-zA-Z0-9_\-]+)(.*)$/);
    if (linkMatch) {
      let [_, srcId, srcRest, linkType, linkLabel, destId, destRest] = linkMatch;
      
      srcId = srcId.trim();
      destId = destId.trim();
      linkLabel = linkLabel ? linkLabel.trim() : '';

      // Check if source node has inline text definition e.g., A["label"]
      const srcInline = srcId + srcRest;
      const srcNodeDetails = srcInline.match(/^([a-zA-Z0-9_\-]+)\s*([\[\(\{]+)\s*["']?([^"']+)["']?\s*([\]\)\}]+)/);
      if (srcNodeDetails) {
        registerNode(srcNodeDetails[1], srcNodeDetails[3], srcNodeDetails[2] + srcNodeDetails[4]);
        srcId = srcNodeDetails[1];
      } else {
        registerNode(srcId);
      }

      // Check if destination node has inline text definition e.g., B["label"]
      const destInline = destId + destRest;
      const destNodeDetails = destInline.match(/^([a-zA-Z0-9_\-]+)\s*([\[\(\{]+)\s*["']?([^"']+)["']?\s*([\]\)\}]+)/);
      if (destNodeDetails) {
        registerNode(destNodeDetails[1], destNodeDetails[3], destNodeDetails[2] + destNodeDetails[4]);
        destId = destNodeDetails[1];
      } else {
        registerNode(destId);
      }

      // Determine edge style
      let style: CanonicalEdge['style'] = 'solid';
      if (linkType.includes('==>')) {
        style = 'thick';
      } else if (linkType.includes('-.') || linkType.includes('-.-')) {
        style = 'dotted';
      }

      edges.push({
        id: `e-${srcId}-${destId}-${Date.now().toString(36).slice(-3)}`,
        source: srcId,
        target: destId,
        label: linkLabel || undefined,
        style,
      });

      continue;
    }

    // Try a simpler node label matcher e.g., A[label] or A(label)
    const simpleNodeMatch = line.match(/^([a-zA-Z0-9_\-]+)\s*(\[|\(|\{)\s*["']?([^"']+)["']?\s*(\]|\)|\})/);
    if (simpleNodeMatch) {
      const [_, id, open, label, close] = simpleNodeMatch;
      registerNode(id, label, open + close);
    }
  }

  return {
    nodes: Array.from(nodesMap.values()),
    edges,
    metadata: { direction },
  };
}

/**
 * Converts a CanonicalGraph structure back into valid, structured Mermaid flowchart code.
 */
export function graphToMermaid(graph: CanonicalGraph): string {
  const { nodes, edges, metadata } = graph;
  const dir = metadata.direction || 'TD';
  
  let lines: string[] = [`flowchart ${dir}`];

  // Helper to get brackets for shape
  const getBrackets = (shape?: CanonicalNode['shape']) => {
    switch (shape) {
      case 'cylinder': return ['[(', ')]'];
      case 'rhombus': return ['{', '}'];
      case 'circle': return ['((', '))'];
      case 'stadium': return ['([', '])'];
      case 'subroutine': return ['[[', ']]'];
      default: return ['[', ']'];
    }
  };

  // 1. Output Node Definitions (makes rendering uniform and clean)
  nodes.forEach(node => {
    const [open, close] = getBrackets(node.shape);
    // Sanitize label to prevent syntax errors
    const safeLabel = node.label.replace(/"/g, '\\"');
    lines.push(`    ${node.id}${open}"${safeLabel}"${close}`);
  });

  // 2. Output Edges
  edges.forEach(edge => {
    let arrow = '-->';
    if (edge.style === 'thick') {
      arrow = '==>';
    } else if (edge.style === 'dotted') {
      arrow = '-.->';
    }

    if (edge.label) {
      // Escape label
      const safeLabel = edge.label.replace(/"/g, '\\"');
      lines.push(`    ${edge.source} ${arrow}|${safeLabel}| ${edge.target}`);
    } else {
      lines.push(`    ${edge.source} ${arrow} ${edge.target}`);
    }
  });

  return lines.join('\n');
}

/**
 * Applies a custom layered BFS hierarchy to assign coordinate positioning to nodes automatically.
 */
export function applyHierarchicalLayout(
  graph: CanonicalGraph,
  orientation: 'TD' | 'LR' | 'TB' | 'BT' | 'RL' = 'TD'
): CanonicalGraph {
  const { nodes, edges, metadata } = graph;
  if (nodes.length === 0) return graph;

  // 1. Build Adjacency list and compute in-degrees
  const adj = new Map<string, string[]>();
  const inDegree = new Map<string, number>();

  nodes.forEach(n => {
    adj.set(n.id, []);
    inDegree.set(n.id, 0);
  });

  edges.forEach(e => {
    if (adj.has(e.source) && adj.has(e.target)) {
      adj.get(e.source)!.push(e.target);
      inDegree.set(e.target, inDegree.get(e.target)! + 1);
    }
  });

  // 2. Assign level ranks via BFS starting at root nodes (inDegree = 0)
  const nodeLevels = new Map<string, number>();
  const visited = new Set<string>();
  const queue: string[] = [];

  // Find all roots
  nodes.forEach(n => {
    if (inDegree.get(n.id) === 0) {
      queue.push(n.id);
      nodeLevels.set(n.id, 0);
      visited.add(n.id);
    }
  });

  // If the graph has cycles or no obvious root, take the first node as root
  if (queue.length === 0 && nodes.length > 0) {
    const firstNodeId = nodes[0].id;
    queue.push(firstNodeId);
    nodeLevels.set(firstNodeId, 0);
    visited.add(firstNodeId);
  }

  // BFS traversal to assign rank levels
  while (queue.length > 0) {
    const current = queue.shift()!;
    const currentLevel = nodeLevels.get(current) || 0;

    const neighbors = adj.get(current) || [];
    for (const neighbor of neighbors) {
      if (!visited.has(neighbor)) {
        visited.add(neighbor);
        nodeLevels.set(neighbor, currentLevel + 1);
        queue.push(neighbor);
      } else {
        // If already visited, promote its level if this path is deeper
        const existingLevel = nodeLevels.get(neighbor) || 0;
        if (currentLevel + 1 > existingLevel) {
          nodeLevels.set(neighbor, currentLevel + 1);
        }
      }
    }
  }

  // Handle any orphan nodes that BFS didn't reach (e.g. disconnected nodes)
  nodes.forEach(n => {
    if (!visited.has(n.id)) {
      nodeLevels.set(n.id, 0);
      visited.add(n.id);
      
      // BFS from this disconnected orphan root
      const orphanQueue = [n.id];
      while (orphanQueue.length > 0) {
        const curr = orphanQueue.shift()!;
        const currLvl = nodeLevels.get(curr) || 0;
        const neighbors = adj.get(curr) || [];
        for (const neigh of neighbors) {
          if (!visited.has(neigh)) {
            visited.add(neigh);
            nodeLevels.set(neigh, currLvl + 1);
            orphanQueue.push(neigh);
          }
        }
      }
    }
  });

  // 3. Group nodes by their ranks/levels to position symmetrically
  const levelGroups = new Map<number, string[]>();
  nodeLevels.forEach((level, nodeId) => {
    if (!levelGroups.has(level)) {
      levelGroups.set(level, []);
    }
    levelGroups.get(level)!.push(nodeId);
  });

  // Layout Constants
  const xSpacing = 240;
  const ySpacing = 160;
  const layoutNodes: CanonicalNode[] = [];

  // Assign x, y coordinates
  levelGroups.forEach((nodeIds, level) => {
    const numNodes = nodeIds.length;
    nodeIds.forEach((nodeId, index) => {
      const node = nodes.find(n => n.id === nodeId)!;
      
      let x = 0;
      let y = 0;

      if (orientation === 'TD' || orientation === 'TB') {
        // Top-Down: y changes per level, x is distributed symmetric around 0
        y = level * ySpacing + 50;
        x = (index - (numNodes - 1) / 2) * xSpacing + 400; // Center offset around 400px
      } else {
        // Left-to-Right: x changes per level, y is distributed symmetric around 0
        x = level * xSpacing + 100;
        y = (index - (numNodes - 1) / 2) * ySpacing + 250; // Center offset around 250px
      }

      layoutNodes.push({
        ...node,
        x: Math.round(x),
        y: Math.round(y),
      });
    });
  });

  return {
    nodes: layoutNodes,
    edges,
    metadata: {
      ...metadata,
      direction: orientation as any,
    },
  };
}
