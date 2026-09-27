import { useState } from "react";
import type { GraphData } from "../types";
import { findEdge } from "../graphUtils";

interface AdjacencyMatrixProps {
  graph: GraphData;
  source: string | null;
  onSetWeight: (u: string, v: string, weight: number) => void;
  onSetSource: (id: string) => void;
}

/** 邻接矩阵：行=起点，列=终点；与画布实时同步，单元格可直接编辑/新建边。 */
export function AdjacencyMatrix({
  graph,
  source,
  onSetWeight,
  onSetSource,
}: AdjacencyMatrixProps) {
  const [editing, setEditing] = useState<{ u: string; v: string; value: string } | null>(
    null,
  );
  const ids = graph.nodes.map((n) => n.id);

  const commit = () => {
    if (!editing) return;
    const w = Number(editing.value);
    if (Number.isFinite(w)) onSetWeight(editing.u, editing.v, w);
    setEditing(null);
  };

  return (
    <div className="panel matrix-panel">
      <div className="panel-title">
        邻接矩阵
        <span className="panel-sub">行→列，点击单元格建边/改权（可负）；点行首「源」设源点</span>
      </div>
      <div className="matrix-scroll">
        <table className="matrix-table">
          <thead>
            <tr>
              <th className="matrix-corner">源 \ 到</th>
              {ids.map((id) => (
                <th key={id} className={source === id ? "th-source" : ""}>
                  {id}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ids.map((u) => (
              <tr key={u}>
                <th
                  className={`row-head ${source === u ? "th-source" : ""}`}
                  onClick={() => onSetSource(u)}
                  title="点击设为源点"
                >
                  <span className="source-dot">{source === u ? "●" : "○"}</span>
                  {u}
                </th>
                {ids.map((v) => {
                  const edge = findEdge(graph, u, v);
                  const isEditing = editing?.u === u && editing?.v === v;
                  return (
                    <td
                      key={v}
                      className={[
                        edge ? "cell-edge" : "cell-empty",
                        edge && edge.weight < 0 ? "cell-neg" : "",
                      ].join(" ")}
                      onClick={() => {
                        if (!isEditing) {
                          setEditing({ u, v, value: String(edge?.weight ?? 1) });
                        }
                      }}
                      title={
                        edge
                          ? `${u}→${v} 权 ${edge.weight}（点击改权）`
                          : `点击新建边 ${u}→${v}`
                      }
                    >
                      {isEditing ? (
                        <input
                          autoFocus
                          className="matrix-input"
                          value={editing!.value}
                          onChange={(e) =>
                            setEditing({ u, v, value: e.target.value })
                          }
                          onBlur={commit}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") commit();
                            if (e.key === "Escape") setEditing(null);
                          }}
                          type="number"
                        />
                      ) : edge ? (
                        edge.weight
                      ) : (
                        <span className="matrix-dot">·</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {ids.length === 0 && <div className="empty-hint">图为空，请先添加节点</div>}
      </div>
    </div>
  );
}
