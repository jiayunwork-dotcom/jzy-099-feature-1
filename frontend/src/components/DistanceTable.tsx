import type { ChangeEntry, RunResult, Step } from "../types";

interface DistanceTableProps {
  nodeIds: string[];
  result: RunResult | null;
  step: Step | null;
  source: string | null;
  target: string | null;
  playing: boolean;
  /** 动态实验：本次修复中距离真正变化的节点（改动前→改动后） */
  changed?: ChangeEntry[];
  /** 动态实验：本次修复实际被重新处理过的节点集合 */
  reprocessed?: string[];
  /** 动态实验：是否处于实验模式（用于着色与图例） */
  experimentMode?: boolean;
}

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return "∞";
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

/** 最短路径算法教学看板 —— 距离表 + 优先队列（Dijkstra）/ 轮次（Bellman–Ford）+ 逐步讲解。 */
export function DistanceTable({
  nodeIds,
  result,
  step,
  source,
  target,
  playing,
  changed = [],
  reprocessed = [],
  experimentMode = false,
}: DistanceTableProps) {
  const dist = step?.dist ?? result?.dist ?? {};
  const pred = step?.pred ?? result?.pred ?? {};
  const settled = new Set(step?.settled ?? result?.settled ?? []);
  const affected = new Set<string>(
    step?.affected?.length ? step.affected : result?.affected ?? [],
  );
  // 动态修复：当前帧为止被作废 / 被重新处理的节点（累计集合）
  const frameInvalidated = new Set<string>(step?.invalidated ?? []);
  const frameReprocessed = new Set<string>(
    step?.reprocessed?.length ? step.reprocessed : reprocessed,
  );
  const changedMap = new Map(changed.map((c) => [c.node, c]));

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
          {experimentMode
            ? "作废重算 / 被重新处理 / 未被碰到 三类一眼分开；变化格显示 旧值→新值"
            : "已确定 = 最短距离锁定；∞ = 不可达；−∞ = 负权环影响"}
        </span>
      </div>

      {experimentMode && (
        <div className="exp-legend">
          <span><i className="elg elg-invalid" />作废后重算</span>
          <span><i className="elg elg-repro" />重新处理</span>
          <span><i className="elg elg-untouched" />始终没碰</span>
          <span><i className="elg elg-changed" />距离变化</span>
        </div>
      )}

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
            const change = changedMap.get(id);
            const isInvalid = frameInvalidated.has(id);
            const isRepro = frameReprocessed.has(id);
            const isChanged = change !== undefined;
            let status = isAffected
              ? "−∞ 负权环"
              : settled.has(id)
                ? "✓ 已确定"
                : d !== undefined && d !== null
                  ? "待松弛"
                  : initialized
                    ? "∞ 不可达"
                    : "未初始化";
            if (experimentMode) {
              if (isAffected) status = "−∞ 负权环";
              else if (isInvalid) status = "↺ 已作废重算";
              else if (isRepro) status = "↻ 被重新处理";
              else status = "— 未被碰到";
            }
            return (
              <tr
                key={id}
                className={[
                  step?.current_node === id ? "row-current" : "",
                  settled.has(id) ? "row-settled" : "",
                  isAffected ? "row-affected" : "",
                  experimentMode && isInvalid ? "row-invalidated" : "",
                  experimentMode && !isInvalid && isRepro ? "row-reprocessed" : "",
                  experimentMode && !isRepro && !isAffected ? "row-untouched" : "",
                  experimentMode && isChanged ? "row-changed" : "",
                  target === id ? "row-target" : "",
                ].join(" ")}
              >
                <td className="cell-node">
                  {source === id && <span className="src-tag" title="源点">源</span>}
                  {target === id && <span className="tgt-tag" title="目标">终</span>}
                  {id}
                </td>
                <td className="cell-dist">
                  {isAffected ? (
                    <span className="dist-neginf">−∞</span>
                  ) : isChanged ? (
                    <span className="dist-change" title={`${fmt(change!.old)} → ${fmt(change!.new)}`}>
                      <span className="dist-old">{fmt(change!.old)}</span>
                      <span className="dist-arrow">→</span>
                      <span className="dist-new">{fmt(change!.new)}</span>
                    </span>
                  ) : (
                    fmt(d)
                  )}
                </td>
                <td className="cell-pred">{pred[id] ?? "—"}</td>
                <td className="cell-status">
                  <span
                    className={
                      isAffected
                        ? "status status-bad"
                        : experimentMode
                          ? isInvalid
                            ? "status status-invalid"
                            : isRepro
                              ? "status status-repro"
                              : "status status-untouched"
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
      return type;
  }
}
