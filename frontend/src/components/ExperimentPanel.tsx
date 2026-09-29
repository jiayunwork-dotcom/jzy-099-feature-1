import type { ExperimentResult, ExperimentSummary } from "../types";

interface ExperimentPanelProps {
  active: boolean;
  source: string | null;
  loading: boolean;
  experimentId: string | null;
  summary: ExperimentSummary | null;
  currentResult: ExperimentResult | null;
  viewingVersion: number | null;
  onStart: () => void;
  onExit: () => void;
  onSelectVersion: (version: number) => void;
}

/** 动态实验面板：开 / 退实验、本次修复统计、历史版本回看。 */
export function ExperimentPanel(props: ExperimentPanelProps) {
  const {
    active,
    source,
    loading,
    experimentId,
    currentResult,
    viewingVersion,
    onStart,
    onExit,
    onSelectVersion,
  } = props;

  if (!active) {
    return (
      <div className="panel experiment-panel">
        <div className="panel-title">
          动态实验（局部增量修复）
          <span className="panel-sub">
            改一条边，只把受影响的一片距离修回来，并演示「修了哪里、为什么只修这里」
          </span>
        </div>
        <button
          className="run-btn"
          disabled={!source || loading}
          onClick={onStart}
          title={!source ? "请先右键设置源点" : "对当前图与源点开一个动态实验"}
        >
          {loading ? "创建中…" : "🧪 对当前图开实验"}
        </button>
        <p className="experiment-hint">
          开实验后，双击边改权重、矩阵改单元格、拖出新边或删除边都作为一次「编辑」
          提交，后端在上一版结果上做增量修复，不再整图重跑。
        </p>
      </div>
    );
  }

  const modeFull = currentResult?.mode === "full";
  const isHistory =
    viewingVersion !== null &&
    currentResult !== null &&
    viewingVersion !== currentResult.version;

  return (
    <div className="panel experiment-panel experiment-active">
      <div className="panel-title">
        动态实验进行中
        <span className="panel-sub">
          {experimentId ? `实验 ${experimentId}` : ""}
        </span>
      </div>

      {currentResult && (
        <>
          <div
            className={`exp-state ${
              currentResult.has_negative_cycle
                ? "exp-state-cycle"
                : modeFull
                  ? "exp-state-full"
                  : "exp-state-inc"
            }`}
          >
            {currentResult.has_negative_cycle
              ? "❗ 含源点可达的负权环：环上及下游距离为 −∞"
              : modeFull
                ? "🔁 本版走了全量重算"
                : "✨ 本版为增量修复"}
            <span className="exp-version">
              版本 {currentResult.version}
            </span>
          </div>

          {modeFull && currentResult.reason && (
            <div className="exp-reason" title={currentResult.reason}>
              为什么走全量：{currentResult.reason}
            </div>
          )}

          <div className="relax-counts" title="按「检查过的边」计数，不论是否更新成功">
            <div
              className={
                currentResult.incremental_relax_count <=
                currentResult.full_relax_count / 10
                  ? "relax-box relax-good"
                  : "relax-box"
              }
            >
              <span className="relax-num">
                {currentResult.incremental_relax_count}
              </span>
              <span className="relax-label">本次松弛</span>
            </div>
            <div className="relax-sep">/</div>
            <div className="relax-box">
              <span className="relax-num">
                {currentResult.full_relax_count}
              </span>
              <span className="relax-label">同图全量 BF</span>
            </div>
          </div>

          <div className="exp-diff-summary">
            <span>
              距离变化节点：
              <strong>{currentResult.changed.length}</strong>
            </span>
            <span>
              被重新处理：<strong>{currentResult.reprocessed.length}</strong>
            </span>
          </div>

          {isHistory && (
            <div className="banner banner-warn exp-history-banner">
              正在回看历史版本 v{viewingVersion}（只读）。点「回到当前」或在
              画布上继续编辑即可退出回看。
            </div>
          )}

          <div className="version-list-wrap">
            <div className="version-list-head">版本历史（点击回看该版图与结果）</div>
            <div className="version-list">
              {(props.summary?.versions ??
                Array.from(
                  { length: currentResult.version + 1 },
                  (_, i) => i,
                )
              )
                .slice()
                .reverse()
                .map((v) => (
                  <button
                    key={v}
                    className={
                      "version-item" +
                      (v === currentResult.version ? " v-current" : "") +
                      (v === viewingVersion ? " v-viewing" : "")
                    }
                    onClick={() => onSelectVersion(v)}
                  >
                    v{v}
                    {v === 0 ? " · 初始全量" : ""}
                  </button>
                ))}
            </div>
          </div>
        </>
      )}

      <button className="tool tool-danger exp-exit" onClick={onExit}>
        ✕ 退出实验（回到整图运行）
      </button>
    </div>
  );
}
