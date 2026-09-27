import type { Algorithm, RunResult } from "../types";
import { hasNegativeEdge } from "../graphUtils";
import type { GraphData } from "../types";

interface DemoControlsProps {
  graph: GraphData;
  source: string | null;
  target: string | null;
  algorithm: Algorithm;
  allowNegative: boolean;
  result: RunResult | null;
  stepIndex: number;
  stepCount: number;
  playing: boolean;
  speed: number;
  loading: boolean;
  onAlgorithmChange: (a: Algorithm) => void;
  onAllowNegativeChange: (v: boolean) => void;
  onTargetChange: (id: string | null) => void;
  onRun: () => void;
  onPlayPause: () => void;
  onStep: (delta: number) => void;
  onReset: () => void;
  onSpeed: (factor: number) => void;
}

export function DemoControls(props: DemoControlsProps) {
  const {
    graph,
    source,
    target,
    algorithm,
    allowNegative,
    result,
    stepIndex,
    stepCount,
    playing,
    speed,
    loading,
  } = props;

  const neg = hasNegativeEdge(graph);
  const dijkstraBlocked = algorithm === "dijkstra" && neg && !allowNegative;

  return (
    <div className="panel controls-panel">
      <div className="panel-title">
        算法演示
        <span className="panel-sub">所有中间状态由后端逐步返回</span>
      </div>

      <div className="control-row algo-toggle">
        <button
          className={algorithm === "dijkstra" ? "seg seg-active" : "seg"}
          onClick={() => props.onAlgorithmChange("dijkstra")}
        >
          Dijkstra
        </button>
        <button
          className={algorithm === "bellman_ford" ? "seg seg-active" : "seg"}
          onClick={() => props.onAlgorithmChange("bellman_ford")}
        >
          Bellman–Ford
        </button>
      </div>

      <div className="control-row source-row">
        <div className="field">
          <label>源点（右键画布节点也可设置）</label>
          <div className="fake-select">{source ?? "未选择"}</div>
        </div>
        <div className="field">
          <label>目标节点（跑完高亮整条路径）</label>
          <select
            value={target ?? ""}
            onChange={(e) => props.onTargetChange(e.target.value || null)}
          >
            <option value="">（不选目标）</option>
            {graph.nodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.id}
              </option>
            ))}
          </select>
        </div>
      </div>

      {algorithm === "dijkstra" && neg && (
        <div className="warning-box">
          <strong>当前图含负权边，Dijkstra 不适用。</strong>
          <label className="check-line">
            <input
              type="checkbox"
              checked={allowNegative}
              onChange={(e) => props.onAllowNegativeChange(e.target.checked)}
            />
            仍然执行（结果不可信，仅用于对照观察错误）
          </label>
        </div>
      )}

      <button
        className="run-btn"
        disabled={!source || loading || dijkstraBlocked}
        onClick={props.onRun}
        title={
          !source
            ? "请先设置源点"
            : dijkstraBlocked
              ? "Dijkstra 不能处理负权边"
              : "运行算法"
        }
      >
        {loading ? "计算中…" : `▶ 运行 ${algorithm === "dijkstra" ? "Dijkstra" : "Bellman–Ford"}`}
      </button>

      {result && (
        <>
          <div className="playback-row">
            <button className="pb" onClick={() => props.onStep(-1)} title="上一步">
              ⏮
            </button>
            <button className="pb pb-play" onClick={props.onPlayPause}>
              {playing ? "⏸ 暂停" : "▶ 播放"}
            </button>
            <button className="pb" onClick={() => props.onStep(1)} title="下一步">
              ⏭
            </button>
            <div className="progress">
              <div
                className="progress-bar"
                style={{
                  width: `${stepCount ? ((stepIndex + 1) / stepCount) * 100 : 0}%`,
                }}
              />
            </div>
            <span className="step-counter">
              {stepIndex + 1}/{stepCount}
            </span>
            <button className="pb" onClick={props.onReset} title="回到第一步">
              ⟲
            </button>
          </div>

          <div className="speed-row">
            <span>速度</span>
            <button className="speed-btn" onClick={() => props.onSpeed(1 / 1.6)}>
              减速 −
            </button>
            <span className="speed-val">{speed.toFixed(2)}s/步</span>
            <button className="speed-btn" onClick={() => props.onSpeed(1.6)}>
              加速 +
            </button>
          </div>
        </>
      )}
    </div>
  );
}
