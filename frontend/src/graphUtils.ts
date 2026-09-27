import type { GraphData, GEdge, GNode } from "./types";

/** 新建节点 id：找最小的未被占用字母/数字组合 */
export function nextNodeId(graph: GraphData): string {
  const used = new Set(graph.nodes.map((n) => n.id));
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  for (const ch of letters) {
    if (!used.has(ch)) return ch;
  }
  let i = 1;
  while (used.has(`N${i}`)) i += 1;
  return `N${i}`;
}

export function edgeKey(u: string, v: string): string {
  return `${u}→${v}`;
}

export function findEdge(
  graph: GraphData,
  u: string,
  v: string,
): GEdge | undefined {
  return graph.edges.find((e) => e.source === u && e.target === v);
}

export function upsertEdge(
  graph: GraphData,
  source: string,
  target: string,
  weight: number,
): GraphData {
  const existing = findEdge(graph, source, target);
  if (existing) {
    return {
      ...graph,
      edges: graph.edges.map((e) =>
        e.source === source && e.target === target ? { ...e, weight } : e,
      ),
    };
  }
  return {
    ...graph,
    edges: [...graph.edges, { source, target, weight }],
  };
}

export function removeNode(graph: GraphData, id: string): GraphData {
  return {
    nodes: graph.nodes.filter((n) => n.id !== id),
    edges: graph.edges.filter((e) => e.source !== id && e.target !== id),
  };
}

export function removeEdge(graph: GraphData, u: string, v: string): GraphData {
  return {
    ...graph,
    edges: graph.edges.filter((e) => !(e.source === u && e.target === v)),
  };
}

export function moveNode(graph: GraphData, id: string, x: number, y: number): GraphData {
  return {
    ...graph,
    nodes: graph.nodes.map((n) => (n.id === id ? { ...n, x, y } : n)),
  };
}

export function nodeMap(graph: GraphData): Map<string, GNode> {
  return new Map(graph.nodes.map((n) => [n.id, n]));
}

export function hasNegativeEdge(graph: GraphData): boolean {
  return graph.edges.some((e) => e.weight < 0);
}

/** 图内容是否实质相同（忽略坐标），用于矩阵编辑后避免无谓重置演示 */
export function graphTopologyKey(graph: GraphData): string {
  return JSON.stringify({
    n: graph.nodes.map((n) => n.id),
    e: graph.edges
      .map((e) => [e.source, e.target, e.weight])
      .sort((a, b) => String(a).localeCompare(String(b))),
  });
}
