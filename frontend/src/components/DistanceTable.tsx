import type { ExperimentVersion, RunResult, Step } from "../types";

interface DistanceTableProps {
  nodeIds: string[];
  result: RunResult | null;
  step: Step | null;
  source: string | null;
  target: string | null;
  playing: boolean;
  /** 实验态：提供当前版本（含 changed/reprocessed/invalidated）与播放帧 */
  experiment?: ExperimentVersion | null;
  expStep?: Step | null;
}

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return "∞";
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

/** 距离表 + 优先队列（Dijkstra）/ 轮次（Bellman–Ford）/ 修复讲解。 */
export function DistanceTable({
  nodeIds,
  result,
  step,
  source,
  target,
  playing,
  experiment,
  expStep,
}: DistanceTableProps) {
  // ---- 实验态优先 ----
  if (experiment) {
    return <ExperimentDistanceTable
      nodeIds={nodeIds}
      experiment={experiment}
      step={expStep ?? null}
      source={source}
      playing={playing}
    />;
  }

  const dist = step?.dist ?? result?.dist ?? {};
  const pred = step?.pred ?? result?.pred ?? {};
  const settled = new Set(step?.settled ?? result?.settled ?? []);
  const affected = new Set<string>(
    step?.affected?.length ? step.affected : result?.affected ?? [],
  );

  const isDijkstra = result?.algorithm === "dijkstra";
  const queue = step?.queue ?? [];
  const passLabel =
    step?.pass != null
      ? isDijkstra
        ? ""
        : step.type.startsWith("detect")
          ? `第 ${step.pass} 轮 · 负权环检测`
          : `第 ${step.pass} 轮`
      : "";

  return (
    <div className="panel distance-panel">
      <div className="panel-title">
        距离表（后端每一步返回快照）
        <span className="panel-sub">
          已确定 = 最短距离锁定；∞ = 不可达；−∞ = 负权环影响
        </span>
      </div>

      {/* 优先队列 / 轮次信息 */}
      <div className="meta-strip">
        {isDijkstra ? (
          <div className="queue-strip" title="Dijkstra 优先队列中各节点的当前已知距离">
            <span className="meta-label">优先队列</span>
            {queue.length === 0 ? (
              <span className="meta-empty">∅</span>
            ) : (
              queue.map(([node, d]) => (
                <span key={node} className="queue-item">
                  {node}
                  <em>{fmt(d)}</em>
                </span>
              ))
            )}
          </div>
        ) : (
          <div className="queue-strip" title="Bellman–Ford 逐轮松弛所有边">
            <span className="meta-label">轮次</span>
            <span className="pass-badge">{passLabel || "—"}</span>
          </div>
        )}
      </div>

      {distanceRows(nodeIds, { dist, pred, source, target, step, settled, affected })}

      {/* 逐步讲解 */}
      {step && (
        <div className={`step-message step-${step.type}`}>
          <div className="step-message-head">
            <span className="step-index">
              {playing ? "● 演示中" : "步骤"}
            </span>
            <span className="step-type">{stepTypeLabel(step.type, isDijkstra)}</span>
          </div>
          <p>{step.message}</p>
        </div>
      )}
    </div>
  );
}

// ---- 实验态距离表 ------------------------------------------------------

function ExperimentDistanceTable({
  nodeIds,
  experiment,
  step,
  source,
  playing,
}: {
  nodeIds: string[];
  experiment: ExperimentVersion;
  step: Step | null;
  source: string | null;
  playing: boolean;
}) {
  // 播放帧优先；停在最后一帧时即最终距离表
  const dist = step?.dist ?? experiment.dist;
  const pred = step?.pred ?? experiment.pred;
  const changedMap = new Map(experiment.changed.map((c) => [c.node, c]));
  const reprocessed = new Set(experiment.reprocessed);
  const invalidatedNow = new Set(step?.invalidated ?? []);
  const affectedFinal = new Set(
    step?.affected?.length ? step.affected : experiment.affected,
  );

  return (
    <div className="panel distance-panel exp-distance-panel">
      <div className="panel-title">
        距离表 · 动态修复 v{experiment.version}
        <span className="panel-sub">
          旧值 → 新值；红色 = 被作废重算，蓝色 = 距离改变，灰色 = 没被碰过
        </span>
      </div>

      <div className="meta-strip">
        <div className="queue-strip" title="本次修复中待重新处理/已重处理的节点">
          <span className="meta-label">重处理</span>
          {experiment.reprocessed.length === 0 ? (
            <span className="meta-empty">∅（本次没有节点被重新处理）</span>
          ) : (
            experiment.reprocessed.map((node) => (
              <span key={node} className="queue-item exp-reprocessed-item">
                {node}
              </span>
            ))
          )}
          {step?.pass != null && step.type?.startsWith("repair_wave") && (
            <span className="pass-badge">扩散第 {step.pass} 层</span>
          )}
        </div>
      </div>

      <table className="dist-table">
        <thead>
          <tr>
            <th>节点</th>
            <th>修复前</th>
            <th>当前距离</th>
            <th>前驱</th>
            <th>本次状态</th>
          </tr>
        </thead>
        <tbody>
          {nodeIds.map((id) => {
            const change = changedMap.get(id);
            const before = change ? change.before : null;
            const hasChanged = !!change;
            const isRepro = reprocessed.has(id);
            const isInvalidNow = invalidatedNow.has(id);
            const isAffected = affectedFinal.has(id);
            const d = dist[id];
            const showBefore = hasChanged;
            let status: string;
            let cls: string;
            if (isInvalidNow) {
              status = "✖ 已作废，重算中";
              cls = "row-exp-invalidated";
            } else if (isAffected) {
              status = "−∞ 负权环";
              cls = "row-affected";
            } else if (isRepro || hasChanged) {
              status = "↻ 重新处理过";
              cls = "row-exp-changed";
            } else {
              status = "· 未触碰";
              cls = "row-exp-untouched";
            }
            return (
              <tr key={id} className={[
                cls,
                step?.current_node === id ? "row-current" : "",
              ].join(" ")}>
                <td className="cell-node">
                  {source === id && <span className="src-tag" title="源点">源</span>}
                  {id}
                </td>
                <td className="cell-before">
                  {showBefore && change ? (
                    <span className="dist-old">{fmt(before)}</span>
                  ) : (
                    <span className="dist-before-na">—</span>
                  )}
                </td>
                <td className="cell-dist">
                  {isInvalidNow ? (
                    <span className="dist-pending">∞?</span>
                  ) : isAffected ? (
                    <span className="dist-neginf">−∞</span>
                  ) : (
                    fmt(d)
                  )}
                  {hasChanged && !isInvalidNow && (
                    <span className="dist-arrow"> ←</span>
                  )}
                </td>
                <td className="cell-pred">{pred[id] ?? "—"}</td>
                <td className="cell-status">
                  <span className={`status ${
                    isInvalidNow ? "status-bad"
                      : isAffected ? "status-bad"
                      : isRepro || hasChanged ? "status-exp-changed"
                      : "status-exp-untouched"
                  }`}>{status}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {step && (
        <div className={`step-message step-${step.type}`}>
          <div className="step-message-head">
            <span className="step-index">
              {playing ? "● 修复演示中" : "修复帧"}
            </span>
            <span className="step-type">{repairStepLabel(step.type)}</span>
          </div>
          <p>{step.message}</p>
        </div>
      )}
    </div>
  );
}

function distanceRows(
  nodeIds: string[],
  ctx: {
    dist: Record<string, number | null | undefined>;
    pred: Record<string, string | null | undefined>;
    source: string | null;
    target: string | null;
    step: Step | null;
    settled: Set<string>;
    affected: Set<string>;
  },
) {
  const { dist, pred, source, target, step, settled, affected } = ctx;
  return (
    <table className="dist-table">
      <thead>
        <tr>
          <th>节点</th>
          <th>距离 d</th>
          <th>前驱</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        {nodeIds.map((id) => {
          const d = dist[id];
          const isAffected = affected.has(id);
          const initialized = id in dist;
          const status = isAffected
            ? "−∞ 负权环"
            : settled.has(id)
              ? "✓ 已确定"
              : d !== undefined && d !== null
                ? "待松弛"
                : initialized
                  ? "∞ 不可达"
                  : "未初始化";
          return (
            <tr
              key={id}
              className={[
                step?.current_node === id ? "row-current" : "",
                settled.has(id) ? "row-settled" : "",
                isAffected ? "row-affected" : "",
                target === id ? "row-target" : "",
              ].join(" ")}
            >
              <td className="cell-node">
                {source === id && <span className="src-tag" title="源点">源</span>}
                {target === id && <span className="tgt-tag" title="目标">终</span>}
                {id}
              </td>
              <td className="cell-dist">
                {isAffected ? <span className="dist-neginf">−∞</span> : fmt(d)}
              </td>
              <td className="cell-pred">{pred[id] ?? "—"}</td>
              <td className="cell-status">
                <span
                  className={
                    isAffected
                      ? "status status-bad"
                      : settled.has(id)
                        ? "status status-ok"
                        : "status"
                  }
                >
                  {status}
                </span>
                {!isAffected && initialized && d === null && id !== source && (
                  <span className="unreachable-note">不可达</span>
                )}
              </td>
            </tr>
          );
        })}
        {nodeIds.length === 0 && (
          <tr>
            <td colSpan={4} className="empty-hint">
              选择算法并运行后，这里显示每一步的距离表
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

function stepTypeLabel(type: Step["type"], isDijkstra: boolean): string {
  switch (type) {
    case "init":
      return "初始化";
    case "settle":
      return "确定节点";
    case "relax":
      return isDijkstra ? "松弛（出边）" : "松弛边";
    case "pass_start":
      return "新一轮开始";
    case "pass_end":
      return "本轮结束";
    case "detect_start":
      return "检测轮开始";
    case "detect":
      return "检测松弛";
    case "negative_cycle":
      return "发现负权环";
    case "finished":
      return "算法结束";
    default:
      return repairStepLabel(type);
  }
}

export function repairStepLabel(type: Step["type"]): string {
  switch (type) {
    case "repair_edit":
      return "本次编辑";
    case "repair_noop":
      return "无需修复";
    case "repair_invalidate_plan":
      return "确定作废子树";
    case "repair_invalidated":
      return "子树已作废";
    case "repair_boundary":
      return "边界边重灌";
    case "repair_relax":
      return "重新松弛";
    case "repair_wave_start":
      return "扩散一层";
    case "repair_detect_start":
      return "收敛后检测轮";
    case "repair_detect":
      return "检测松弛";
    case "repair_negative_cycle":
      return "发现负权环";
    case "repair_full":
      return "退回全量";
    case "repair_finished":
      return "修复结束";
    default:
      return type;
  }
}
