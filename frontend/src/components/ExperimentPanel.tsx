import type { ExperimentVersion } from "../types";

interface ExperimentPanelProps {
  current: ExperimentVersion;
  viewingVersion: number | null;
  stepIndex: number;
  stepCount: number;
  playing: boolean;
  speed: number;
  loading: boolean;
  onPlayPause: () => void;
  onStep: (delta: number) => void;
  onReset: () => void;
  onSpeed: (factor: number) => void;
  onExit: () => void;
  onBackToLatest: () => void;
}

function modeBadge(mode: ExperimentVersion["mode"]) {
  if (mode === "initial") return <span className="exp-badge exp-badge-initial">初始 · 全量 BF</span>;
  if (mode === "incremental") return <span className="exp-badge exp-badge-inc">增量修复</span>;
  return <span className="exp-badge exp-badge-full">全量重算</span>;
}

/** 动态实验的状态条：版本、修复模式与原因、本次松弛 / 全量松弛并排对比。 */
export function ExperimentPanel(props: ExperimentPanelProps) {
  const { current: cur, viewingVersion, loading } = props;
  const isPast = viewingVersion !== null && viewingVersion !== cur.version;
  const ratio =
    cur.full_relax_count > 0 ? cur.relax_count / cur.full_relax_count : 0;

  return (
    <div className="panel experiment-panel">
      <div className="panel-title exp-title-row">
        <span>
          动态实验 · v{cur.version}
          {isPast && <span className="exp-viewing">（正在回看 v{viewingVersion}，只读）</span>}
        </span>
        <div className="exp-head-actions">
          {isPast && (
            <button className="exp-btn" onClick={props.onBackToLatest}>
              ↤ 回到最新 v{cur.version}
            </button>
          )}
          <button className="exp-btn exp-exit" onClick={props.onExit}>
            ✕ 退出实验
          </button>
        </div>
      </div>

      <div className="exp-mode-line">
        {modeBadge(cur.mode)}
        <span className="exp-reason" title={cur.reason}>{cur.reason}</span>
      </div>

      {cur.has_negative_cycle && (
        <div className="banner banner-danger exp-cycle-banner">
          ❗ 当前版本存在源点可达的负权环：环{" "}
          {cur.cycle?.nodes.join(" → ") + " → " + cur.cycle?.nodes[0]}
          （环权 {cur.cycle?.weight}），环上及下游距离标为 −∞。
          之后若有编辑把环打破，将自动全量恢复。
        </div>
      )}

      {/* 松弛计数并排对比 */}
      <div className="relax-compare">
        <div className="relax-box relax-inc">
          <div className="relax-num">{cur.relax_count}</div>
          <div className="relax-label">本次修复检查的边</div>
        </div>
        <div className="relax-vs">/</div>
        <div className="relax-box relax-full">
          <div className="relax-num">{cur.full_relax_count}</div>
          <div className="relax-label">从头跑 BF 检查的边</div>
        </div>
        <div
          className="relax-ratio"
          title="本次 / 全量 的比例，越小越能体现局部性"
        >
          比例 {(ratio * 100).toFixed(1)}%
        </div>
      </div>

      <div className="exp-change-line">
        {cur.mode === "initial" ? (
          <span>实验初始版本：整图全量 Bellman–Ford。之后每次改边只做增量修复。</span>
        ) : cur.changed.length === 0 ? (
          <span className="exp-nochange">本次距离变化：无（图的改动不在关键处，纹丝不动）</span>
        ) : (
          <span>
            距离变化节点（{cur.changed.length}）：
            {cur.changed.map((c) => (
              <span key={c.node} className="exp-change-chip">
                {c.node}: {c.before ?? "∞"}→{c.after ?? (cur.has_negative_cycle ? "−∞" : "∞")}
              </span>
            ))}
          </span>
        )}
      </div>

      {cur.steps.length > 1 && (
        <>
          <div className="playback-row">
            <button className="pb" onClick={() => props.onStep(-1)} title="上一步">⏮</button>
            <button className="pb pb-play" onClick={props.onPlayPause}>
              {props.playing ? "⏸ 暂停" : "▶ 播放修复"}
            </button>
            <button className="pb" onClick={() => props.onStep(1)} title="下一步">⏭</button>
            <div className="progress">
              <div
                className="progress-bar"
                style={{
                  width: `${props.stepCount ? ((props.stepIndex + 1) / props.stepCount) * 100 : 0}%`,
                }}
              />
            </div>
            <span className="step-counter">
              {props.stepIndex + 1}/{props.stepCount}
            </span>
            <button className="pb" onClick={props.onReset} title="回到第一步">⟲</button>
          </div>
          <div className="speed-row">
            <span>速度</span>
            <button className="speed-btn" onClick={() => props.onSpeed(1 / 1.6)}>减速 −</button>
            <span className="speed-val">{props.speed.toFixed(2)}s/帧</span>
            <button className="speed-btn" onClick={() => props.onSpeed(1.6)}>加速 +</button>
          </div>
        </>
      )}
      {loading && <div className="exp-loading">提交编辑中…</div>}
    </div>
  );
}
