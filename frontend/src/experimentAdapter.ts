// 把动态实验的 ExperimentResult 适配成现有的 RunResult 形状，
// 让 GraphCanvas / DistanceTable / DemoControls 无需区分数据来源。
// 所有距离仍由后端计算，前端只做渲染层字段映射。

import type {
  ExperimentResult,
  RunResult,
} from "./types";

export function experimentToRunResult(r: ExperimentResult): RunResult {
  return {
    algorithm: "bellman_ford",
    source: r.source,
    dist: r.dist,
    pred: r.pred,
    settled: [],
    reachable: r.reachable,
    steps: r.steps as RunResult["steps"],
    warning: null,
    has_negative_cycle: r.has_negative_cycle,
    cycle: r.cycle,
    affected: r.affected,
  };
}
