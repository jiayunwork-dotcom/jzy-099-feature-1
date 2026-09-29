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
  | DynamicStepType;

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
  /** 仅动态修复帧携带：本帧已作废、待重新计算的节点 */
  invalidated?: string[];
}

export type DynamicStepType =
  | "repair_edit"
  | "repair_noop"
  | "repair_invalidate_plan"
  | "repair_invalidated"
  | "repair_boundary"
  | "repair_relax"
  | "repair_wave_start"
  | "repair_detect_start"
  | "repair_detect"
  | "repair_negative_cycle"
  | "repair_full"
  | "repair_finished";

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

// ---- 动态实验 ----------------------------------------------------------

export type EditKind = "update_weight" | "add_edge" | "delete_edge";

export interface EdgeEditRequest {
  base_version: number;
  kind: EditKind;
  source: string;
  target: string;
  weight?: number | null;
  positions?: Record<string, { x: number; y: number }> | null;
}

export interface ChangedDistance {
  node: string;
  before: number | null;
  after: number | null;
}

export interface EditInfo {
  kind: EditKind;
  source: string;
  target: string;
  weight: number | null;
  description: string | null;
}

/** 一次实验版本（版本 0 的全量初始结果，或某次编辑后的修复结果）。 */
export interface ExperimentVersion {
  experiment_id: string;
  source: string;
  version: number;
  current_version: number;
  /** initial = 版本 0 全量；incremental = 增量修复；full = 退回全量 */
  mode: "initial" | "incremental" | "full";
  reason: string;
  graph: GraphData;
  dist: Record<string, number | null>;
  pred: Record<string, string | null>;
  has_negative_cycle: boolean;
  cycle: CycleInfo | null;
  affected: string[];
  reachable: string[];
  changed: ChangedDistance[];
  reprocessed: string[];
  invalidated: string[];
  /** 本次修复实际检查的边数 / 同图从头跑 BF 要检查的边数 */
  relax_count: number;
  full_relax_count: number;
  steps: Step[];
  edit: EditInfo | null;
}

export interface VersionSummary {
  version: number;
  mode: "initial" | "incremental" | "full";
  has_negative_cycle: boolean;
  changed_count: number;
  relax_count: number;
  full_relax_count: number;
  edit: EditInfo | null;
}

export interface ExperimentHistory {
  experiment_id: string;
  source: string;
  current_version: number;
  versions: VersionSummary[];
}
