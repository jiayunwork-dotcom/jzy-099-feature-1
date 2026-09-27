import { useCallback, useRef, useState } from "react";
import type { GraphData, GNode, RunResult, Step } from "../types";
import { edgeKey, findEdge, nodeMap } from "../graphUtils";

export type ToolMode = "move" | "add-node";

interface GraphCanvasProps {
  graph: GraphData;
  mode: ToolMode;
  result: RunResult | null;
  currentStep: Step | null;
  source: string | null;
  target: string | null;
  selectedNode: string | null;
  selectedEdge: [string, string] | null;
  onCanvasClickAddNode: (x: number, y: number) => void;
  onMoveNode: (id: string, x: number, y: number) => void;
  onCreateEdge: (u: string, v: string) => void;
  onSelectNode: (id: string | null) => void;
  onSelectEdge: (edge: [string, string] | null) => void;
  onEditEdgeWeight: (u: string, v: string, weight: number) => void;
  onSetSource: (id: string) => void;
  onSetTarget: (id: string) => void;
}

const NODE_R = 26;
const PORT_R = 7;

interface DragState {
  kind: "node" | "edge";
  id: string;
  offsetX: number;
  offsetY: number;
  moved: boolean;
  cursor: { x: number; y: number };
}

interface EdgeGeom {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  selfLoop: boolean;
  curved: boolean;
}

function edgeGeometry(
  u: GNode,
  v: GNode,
  reverseExists: boolean,
): EdgeGeom {
  if (u.id === v.id) {
    return { x1: u.x, y1: u.y, x2: v.x, y2: v.y, selfLoop: true, curved: false };
  }
  if (reverseExists) {
    // 双向边：向两侧弯曲，避免与反向边重叠
    const dx = v.x - u.x;
    const dy = v.y - u.y;
    const len = Math.hypot(dx, dy) || 1;
    const off = 18;
    const nx = (-dy / len) * off;
    const ny = (dx / len) * off;
    return {
      x1: u.x + (dx / len) * NODE_R + nx,
      y1: u.y + (dy / len) * NODE_R + ny,
      x2: v.x - (dx / len) * NODE_R + nx,
      y2: v.y - (dy / len) * NODE_R + ny,
      selfLoop: false,
      curved: true,
    };
  }
  const dx = v.x - u.x;
  const dy = v.y - u.y;
  const len = Math.hypot(dx, dy) || 1;
  return {
    x1: u.x + (dx / len) * NODE_R,
    y1: u.y + (dy / len) * NODE_R,
    x2: v.x - (dx / len) * NODE_R,
    y2: v.y - (dy / len) * NODE_R,
    selfLoop: false,
    curved: false,
  };
}

export function GraphCanvas(props: GraphCanvasProps) {
  const {
    graph,
    mode,
    result,
    currentStep,
    source,
    target,
    selectedNode,
    selectedEdge,
  } = props;
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [editing, setEditing] = useState<[string, string] | null>(null);
  const [editValue, setEditValue] = useState("");

  const nodes = nodeMap(graph);

  const toSvg = useCallback((clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  }, []);

  const nodeAt = useCallback(
    (x: number, y: number): GNode | null => {
      // 从后往前，后画的节点优先命中
      for (let i = graph.nodes.length - 1; i >= 0; i--) {
        const n = graph.nodes[i];
        if (Math.hypot(n.x - x, n.y - y) <= NODE_R + 2) return n;
      }
      return null;
    },
    [graph.nodes],
  );

  const onNodePointerDown = (e: React.PointerEvent, n: GNode) => {
    if (e.button !== 0) return;
    // 从端口出发 = 拉线建边；点在圆上 = 选中/拖拽
    const targetEl = e.target as SVGElement;
    if (targetEl.dataset.port === "1") {
      e.stopPropagation();
      targetEl.setPointerCapture(e.pointerId);
      setDrag({
        kind: "edge",
        id: n.id,
        offsetX: 0,
        offsetY: 0,
        moved: false,
        cursor: { ...n },
      });
      return;
    }
    if (mode !== "move") return;
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    const p = toSvg(e.clientX, e.clientY);
    setDrag({
      kind: "node",
      id: n.id,
      offsetX: p.x - n.x,
      offsetY: p.y - n.y,
      moved: false,
      cursor: { x: n.x, y: n.y },
    });
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag) return;
    const p = toSvg(e.clientX, e.clientY);
    if (drag.kind === "node") {
      const nx = p.x - drag.offsetX;
      const ny = p.y - drag.offsetY;
      if (Math.hypot(nx - nodes.get(drag.id)!.x, ny - nodes.get(drag.id)!.y) > 2) {
        drag.moved = true;
      }
      props.onMoveNode(drag.id, Math.max(0, nx), Math.max(0, ny));
    } else {
      setDrag({ ...drag, cursor: p });
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (!drag) return;
    if (drag.kind === "edge") {
      const p = toSvg(e.clientX, e.clientY);
      const hit = nodeAt(p.x, p.y);
      if (hit && hit.id !== drag.id) {
        props.onCreateEdge(drag.id, hit.id);
      }
    } else if (!drag.moved) {
      props.onSelectNode(drag.id);
      props.onSelectEdge(null);
    }
    setDrag(null);
  };

  const onBackgroundClick = (e: React.MouseEvent) => {
    if (mode !== "add-node") {
      props.onSelectNode(null);
      props.onSelectEdge(null);
      return;
    }
    // 只有真正点在空白处才加节点（点击事件由背景 rect 触发）
    if (e.target !== e.currentTarget) return;
    const p = toSvg(e.clientX, e.clientY);
    props.onCanvasClickAddNode(p.x, p.y);
  };

  const startEdit = (u: string, v: string) => {
    const edge = findEdge(graph, u, v);
    setEditing([u, v]);
    setEditValue(String(edge?.weight ?? 1));
  };

  const commitEdit = () => {
    if (!editing) return;
    const w = Number(editValue);
    if (Number.isFinite(w)) {
      props.onEditEdgeWeight(editing[0], editing[1], w);
    }
    setEditing(null);
  };

  // ---- 高亮集合（来自后端 trace / 结果） ----
  const activeSet = new Set<string>();
  currentStep?.active_edges?.forEach((ae) => activeSet.add(edgeKey(ae.source, ae.target)));
  const cycleSet = new Set<string>();
  const cycleNodes = new Set<string>();
  const stepCycle = currentStep?.cycle ?? result?.cycle ?? null;
  stepCycle?.edges.forEach((ce) => cycleSet.add(edgeKey(ce.source, ce.target)));
  stepCycle?.nodes.forEach((id) => cycleNodes.add(id));
  const affectedNodes = new Set<string>(
    currentStep?.affected?.length ? currentStep.affected : result?.affected ?? [],
  );
  const settledNodes = new Set<string>(currentStep?.settled ?? []);
  const finalPathEdges = new Set<string>();
  const finalPathNodes = new Set<string>();
  if (!currentStep || currentStep.type === "finished" || currentStep.type === "negative_cycle") {
    result?.path?.edges.forEach((pe) => finalPathEdges.add(edgeKey(pe.source, pe.target)));
    result?.path?.nodes.forEach((id) => finalPathNodes.add(id));
  }

  return (
    <svg
      ref={svgRef}
      className="graph-canvas"
      viewBox="0 0 1000 600"
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onClick={onBackgroundClick}
    >
      <defs>
        <marker
          id="arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--edge)" />
        </marker>
        <marker
          id="arrow-active"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="8"
          markerHeight="8"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--accent)" />
        </marker>
        <marker
          id="arrow-cycle"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="8"
          markerHeight="8"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--danger)" />
        </marker>
        <marker
          id="arrow-path"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="8"
          markerHeight="8"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--good)" />
        </marker>
      </defs>

      <rect x={0} y={0} width={1000} height={600} className="canvas-bg" />
      {mode === "add-node" && (
        <text x={12} y={24} className="canvas-hint">
          空白处点击添加节点；完成后切回「移动/连线」
        </text>
      )}

      {/* ---- 边 ---- */}
      {graph.edges.map((e) => {
        const u = nodes.get(e.source)!;
        const v = nodes.get(e.target)!;
        const key = edgeKey(e.source, e.target);
        const reverseExists = !!findEdge(graph, e.target, e.source);
        const g = edgeGeometry(u, v, reverseExists);
        const isActive = activeSet.has(key);
        const isCycle = cycleSet.has(key);
        const isPath = finalPathEdges.has(key);
        const isSelected =
          selectedEdge?.[0] === e.source && selectedEdge?.[1] === e.target;
        const relaxed = isActive && currentStep?.relaxed === true;
        const failed = isActive && currentStep?.relaxed === false;

        let path: string;
        if (g.selfLoop) {
          path = `M ${u.x - 6} ${u.y - NODE_R + 2}
                  C ${u.x - 46} ${u.y - 58}, ${u.x + 46} ${u.y - 58},
                    ${u.x + 6} ${u.y - NODE_R + 2}`;
        } else if (g.curved) {
          const mx = (g.x1 + g.x2) / 2;
          const my = (g.y1 + g.y2) / 2;
          const dx = g.x2 - g.x1;
          const dy = g.y2 - g.y1;
          const len = Math.hypot(dx, dy) || 1;
          const bend = 26;
          const cx = mx + (-dy / len) * bend;
          const cy = my + (dx / len) * bend;
          path = `M ${g.x1} ${g.y1} Q ${cx} ${cy} ${g.x2} ${g.y2}`;
        } else {
          path = `M ${g.x1} ${g.y1} L ${g.x2} ${g.y2}`;
        }

        const stroke = isCycle
          ? "var(--danger)"
          : isPath
            ? "var(--good)"
            : isActive
              ? "var(--accent)"
              : "var(--edge)";
        const marker = isCycle
          ? "url(#arrow-cycle)"
          : isPath
            ? "url(#arrow-path)"
            : isActive
              ? "url(#arrow-active)"
              : "url(#arrow)";
        const cls = [
          "edge",
          isActive ? (relaxed ? "edge-relax" : failed ? "edge-check" : "") : "",
          isCycle ? "edge-cycle" : "",
          isPath ? "edge-path" : "",
          isSelected ? "edge-selected" : "",
        ].join(" ");

        // 标签位置
        let lx: number;
        let ly: number;
        if (g.selfLoop) {
          lx = u.x;
          ly = u.y - 64;
        } else if (g.curved) {
          const mx = (g.x1 + g.x2) / 2;
          const my = (g.y1 + g.y2) / 2;
          const dx = g.x2 - g.x1;
          const dy = g.y2 - g.y1;
          const len = Math.hypot(dx, dy) || 1;
          lx = mx + (-dy / len) * 26;
          ly = my + (dx / len) * 26;
        } else {
          lx = (g.x1 + g.x2) / 2;
          ly = (g.y1 + g.y2) / 2;
        }

        const isEditing = editing?.[0] === e.source && editing?.[1] === e.target;

        return (
          <g key={key} className="edge-group">
            <path
              d={path}
              className={cls}
              stroke={stroke}
              markerEnd={marker}
              onClick={(ev) => {
                ev.stopPropagation();
                props.onSelectEdge([e.source, e.target]);
                props.onSelectNode(null);
              }}
              onDoubleClick={(ev) => {
                ev.stopPropagation();
                startEdit(e.source, e.target);
              }}
            />
            {/* 加粗的透明命中区，方便点选 */}
            <path d={path} className="edge-hit" fill="none" />
            {isEditing ? (
              <foreignObject x={lx - 30} y={ly - 14} width={60} height={28}>
                <input
                  autoFocus
                  className="weight-input"
                  value={editValue}
                  onChange={(ev) => setEditValue(ev.target.value)}
                  onBlur={commitEdit}
                  onKeyDown={(ev) => {
                    if (ev.key === "Enter") commitEdit();
                    if (ev.key === "Escape") setEditing(null);
                  }}
                  type="number"
                />
              </foreignObject>
            ) : (
              <g
                className="weight-label"
                onDoubleClick={(ev) => {
                  ev.stopPropagation();
                  startEdit(e.source, e.target);
                }}
              >
                <rect x={lx - 15} y={ly - 11} width={30} height={22} rx={6} />
                <text
                  x={lx}
                  y={ly + 1}
                  textAnchor="middle"
                  className={e.weight < 0 ? "weight-neg" : ""}
                >
                  {e.weight}
                </text>
              </g>
            )}
          </g>
        );
      })}

      {/* ---- 拉线建边的预览 ---- */}
      {drag?.kind === "edge" && (() => {
        const u = nodes.get(drag.id)!;
        return (
          <line
            x1={u.x}
            y1={u.y}
            x2={drag.cursor.x}
            y2={drag.cursor.y}
            className="edge-preview"
          />
        );
      })()}

      {/* ---- 节点 ---- */}
      {graph.nodes.map((n) => {
        const isSource = source === n.id;
        const isTarget = target === n.id;
        const isSettled = settledNodes.has(n.id);
        const isCurrent = currentStep?.current_node === n.id;
        const isCycle = cycleNodes.has(n.id);
        const isAffected = affectedNodes.has(n.id) && !isCycle;
        const isPath = finalPathNodes.has(n.id);
        const isSelected = selectedNode === n.id;
        const cls = [
          "node",
          isSource ? "node-source" : "",
          isTarget ? "node-target" : "",
          isSettled && !isCycle ? "node-settled" : "",
          isCurrent ? "node-current" : "",
          isCycle ? "node-cycle" : "",
          isAffected ? "node-affected" : "",
          isPath ? "node-path" : "",
          isSelected ? "node-selected" : "",
          mode === "add-node" ? "node-no-drag" : "",
        ].join(" ");

        return (
          <g
            key={n.id}
            className={cls}
            transform={`translate(${n.x},${n.y})`}
            onPointerDown={(e) => onNodePointerDown(e, n)}
            onDoubleClick={(ev) => {
              ev.stopPropagation();
              props.onSelectNode(n.id);
            }}
            onContextMenu={(ev) => {
              ev.preventDefault();
              props.onSetSource(n.id);
            }}
          >
            <circle r={NODE_R} className="node-body" />
            <text textAnchor="middle" dy="0.35em" className="node-label">
              {n.id}
            </text>
            {isSource && <text y={-NODE_R - 8} textAnchor="middle" className="node-badge">源</text>}
            {isTarget && <text y={-NODE_R - 8} textAnchor="middle" className="node-badge">终</text>}
            {mode === "move" && (
              <circle
                r={PORT_R}
                cx={NODE_R - 2}
                cy={-NODE_R + 4}
                className="node-port"
                data-port="1"
              />
            )}
          </g>
        );
      })}
    </svg>
  );
}
