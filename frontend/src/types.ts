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
  | "finished"
  // 动态实验增量修复帧
  | "invalidate_plan"
  | "invalidate"
  | "boundary_scan"
  | "boundary"
  | "reprocess"
  | "decrease_plan"
  | "seed"
  | "noop";

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
  /** 动态实验：本帧为止被作废的节点（累计） */
  invalidated?: string[];
  /** 动态实验：本帧为止被重新处理过的节点（累计） */
  reprocessed?: string[];
  /** full = 全量重算（Bellman–Ford 逐轮）；incremental = 增量修复 */
  phase?: "full" | "incremental";
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

// ---- 动态实验 -----------------------------------------------------------

export type EditKind =
  | "set_weight"
  | "add_edge"
  | "delete_edge"
  | "add_node"
  | "delete_node";

export interface ExperimentEdit {
  kind: EditKind;
  /** 提交时由 api 层注入；本地构造编辑时不用填 */
  base_version?: number;
  source?: string;
  target?: string;
  weight?: number;
  node_id?: string;
  x?: number;
  y?: number;
}

export interface ChangeEntry {
  node: string;
  old: number | null;
  new: number | null;
}

/** 一次版本结果（初始版本或一次编辑后的修复结果），结构上是 RunResult 的超集 */
export interface ExperimentResult {
  mode: "full" | "incremental";
  reason: string | null;
  version: number;
  source: string;
  graph: GraphData;
  dist: Record<string, number | null>;
  pred: Record<string, string | null>;
  has_negative_cycle: boolean;
  cycle: CycleInfo | null;
  affected: string[];
  reachable: string[];
  changed: ChangeEntry[];
  reprocessed: string[];
  steps: Step[];
  incremental_relax_count: number;
  full_relax_count: number;
  edit: Record<string, unknown> | null;
}

export interface ExperimentCreated {
  experiment_id: string;
  version: number;
  result: ExperimentResult;
}

export interface ExperimentSummary {
  experiment_id: string;
  source: string;
  current_version: number;
  has_negative_cycle: boolean;
  created_at: number;
  last_accessed_at: number;
  versions: number[];
}
