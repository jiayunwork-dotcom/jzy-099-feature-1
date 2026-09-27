// 与后端 /api/run 返回结构一一对应。前端只渲染这些后端算好的数据，不自行重算。

export interface GNode {
  id: string;
  x: number;
  y: number;
}

export interface GEdge {
  source: string;
  target: string;
  weight: number;
}

export interface GraphData {
  nodes: GNode[];
  edges: GEdge[];
}

export interface ActiveEdge {
  source: string;
  target: string;
}

export interface CycleEdge {
  source: string;
  target: string;
  weight: number;
}

export interface CycleInfo {
  nodes: string[];
  edges: CycleEdge[];
  weight: number | null;
}

export type StepType =
  | "init"
  | "settle"
  | "pass_start"
  | "relax"
  | "pass_end"
  | "detect_start"
  | "detect"
  | "negative_cycle"
  | "finished";

export interface Step {
  type: StepType;
  message: string;
  /** 距离快照：null 表示 ∞；负权环影响下也用 null（−∞） */
  dist: Record<string, number | null>;
  pred: Record<string, string | null>;
  settled: string[];
  current_node: string | null;
  active_edges: ActiveEdge[] | null;
  /** Dijkstra 优先队列 [[node, dist], ...]，Bellman–Ford 恒为空 */
  queue: [string, number][];
  pass: number | null;
  relaxed: boolean | null;
  cycle: { nodes: string[]; edges: CycleEdge[]; weight: number | null } | null;
  affected: string[];
}

export interface PathInfo {
  target: string;
  distance: number | null;
  nodes: string[];
  edges: CycleEdge[];
  exists: boolean;
  reason: string | null;
  total_weight: number | null;
}

export interface RunResult {
  algorithm: "dijkstra" | "bellman_ford";
  source: string;
  dist: Record<string, number | null>;
  pred: Record<string, string | null>;
  settled: string[];
  reachable: string[];
  steps: Step[];
  warning: string | null;
  has_negative_cycle: boolean;
  cycle: Step["cycle"];
  affected: string[];
  path?: PathInfo;
}

export type Algorithm = "dijkstra" | "bellman_ford";

export interface Preset {
  name: string;
  description: string;
  source: string;
  target: string | null;
  graph: GraphData;
}

export interface PresetMap {
  [key: string]: Preset;
}
