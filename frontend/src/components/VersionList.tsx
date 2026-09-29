import type { ExperimentHistory, ExperimentVersion } from "../types";

interface VersionListProps {
  history: ExperimentHistory | null;
  current: ExperimentVersion | null;
  viewingVersion: number | null;
  onSelect: (version: number) => void;
}

const MODE_LABEL: Record<string, string> = {
  initial: "初始全量",
  incremental: "增量",
  full: "全量重算",
};

/** 实验版本列表：回看任一历史版本的图与结果。 */
export function VersionList({
  history,
  current,
  viewingVersion,
  onSelect,
}: VersionListProps) {
  if (!history) return null;
  const activeVersion = viewingVersion ?? current?.version ?? 0;
  return (
    <div className="panel version-panel">
      <div className="panel-title">
        实验版本历史
        <span className="panel-sub">
          点击任一版本回看当时的图与距离表（回看为只读）
        </span>
      </div>
      <div className="version-scroll">
        {history.versions.map((v) => {
          const isActive = v.version === activeVersion;
          const isCurrent = v.version === history.current_version;
          return (
            <button
              key={v.version}
              className={[
                "version-item",
                isActive ? "version-active" : "",
                v.mode === "full" ? "version-full" : "",
                v.has_negative_cycle ? "version-cycle" : "",
              ].join(" ")}
              onClick={() => onSelect(v.version)}
              title={v.edit?.description ?? "版本 0：全量初始化"}
            >
              <span className="version-no">v{v.version}</span>
              <span className="version-mode">{MODE_LABEL[v.mode] ?? v.mode}</span>
              <span className="version-edit">
                {v.edit ? v.edit.description : "初始化"}
              </span>
              <span className="version-meta">
                {v.has_negative_cycle ? (
                  <em className="version-cycle-tag">负环</em>
                ) : v.version === 0 ? null : (
                  <em>{v.changed_count} 节点变化</em>
                )}
                {isCurrent && <em className="version-current-tag">最新</em>}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
