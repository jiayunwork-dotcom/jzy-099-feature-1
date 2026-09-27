import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GraphCanvas, type ToolMode } from "./components/GraphCanvas";
import { AdjacencyMatrix } from "./components/AdjacencyMatrix";
import { DistanceTable } from "./components/DistanceTable";
import { DemoControls } from "./components/DemoControls";
import { runAlgorithm, fetchPresets, ApiError } from "./api";
import type {
  Algorithm,
  GraphData,
  PresetMap,
  RunResult,
} from "./types";
import {
  findEdge,
  hasNegativeEdge,
  nextNodeId,
  removeEdge,
  removeNode,
  upsertEdge,
} from "./graphUtils";

const START_GRAPH: GraphData = {
  nodes: [],
  edges: [],
};

export default function App() {
  const [graph, setGraph] = useState<GraphData>(START_GRAPH);
  const [mode, setMode] = useState<ToolMode>("move");
  const [source, setSource] = useState<string | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [algorithm, setAlgorithm] = useState<Algorithm>("dijkstra");
  const [allowNegative, setAllowNegative] = useState(false);

  const [result, setResult] = useState<RunResult | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(0.9); // 每步秒数
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<[string, string] | null>(null);
  const [presets, setPresets] = useState<PresetMap>({});

  const timerRef = useRef<number | null>(null);
  // 记录上次随算法结果一起请求的目标，用于区分「需要重新回溯路径」
  const lastTarget = useRef<string | null>(target);

  useEffect(() => {
    fetchPresets()
      .then(setPresets)
      .catch((e) => setError(`载入示例图失败：${String(e)}`));
  }, []);

  const stepCount = result?.steps.length ?? 0;
  const currentStep =
    result && stepIndex < result.steps.length ? result.steps[stepIndex] : null;
  const atEnd = result != null && stepIndex >= stepCount - 1;

  // ---- 图编辑 ----------------------------------------------------------

  const invalidateDemo = useCallback(() => {
    setResult(null);
    setPlaying(false);
    setStepIndex(0);
  }, []);

  const addNode = useCallback(
    (x: number, y: number) => {
      setGraph((g) => {
        const id = nextNodeId(g);
        return { ...g, nodes: [...g.nodes, { id, x, y }] };
      });
    },
    [],
  );

  const handleMoveNode = useCallback((id: string, x: number, y: number) => {
    setGraph((g) => ({
      ...g,
      nodes: g.nodes.map((n) => (n.id === id ? { ...n, x, y } : n)),
    }));
  }, []);

  const createEdge = useCallback(
    (u: string, v: string) => {
      setGraph((g) => {
        if (findEdge(g, u, v)) return g;
        return { ...g, edges: [...g.edges, { source: u, target: v, weight: 1 }] };
      });
      invalidateDemo();
    },
    [invalidateDemo],
  );

  const setEdgeWeight = useCallback(
    (u: string, v: string, weight: number) => {
      setGraph((g) => upsertEdge(g, u, v, weight));
      invalidateDemo();
    },
    [invalidateDemo],
  );

  const deleteSelected = useCallback(() => {
    if (selectedNode) {
      setGraph((g) => removeNode(g, selectedNode));
      if (source === selectedNode) setSource(null);
      if (target === selectedNode) setTarget(null);
      setSelectedNode(null);
      invalidateDemo();
    } else if (selectedEdge) {
      setGraph((g) => removeEdge(g, selectedEdge[0], selectedEdge[1]));
      setSelectedEdge(null);
      invalidateDemo();
    }
  }, [selectedNode, selectedEdge, source, target, invalidateDemo]);

  // Delete / Backspace 删除选中元素
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if (e.key === "Delete" || e.key === "Backspace") {
        if (selectedNode || selectedEdge) {
          e.preventDefault();
          deleteSelected();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deleteSelected, selectedNode, selectedEdge]);

  const loadPreset = (key: string) => {
    const preset = presets[key];
    if (!preset) return;
    setGraph(structuredClone(preset.graph));
    setSource(preset.source);
    setTarget(preset.target ?? null);
    setResult(null);
    setPlaying(false);
    setStepIndex(0);
    setError(null);
    setMode("move");
    lastTarget.current = preset.target ?? null;
  };

  const clearGraph = () => {
    setGraph({ nodes: [], edges: [] });
    setSource(null);
    setTarget(null);
    invalidateDemo();
  };

  // ---- 运行算法（全部由后端计算） --------------------------------------

  const run = useCallback(async () => {
    if (!source) return;
    setLoading(true);
    setError(null);
    try {
      const res = await runAlgorithm(graph, source, algorithm, {
        target,
        allowNegative,
      });
      setResult(res);
      setStepIndex(0);
      setPlaying(true);
      lastTarget.current = target;
    } catch (e) {
      setResult(null);
      setPlaying(false);
      if (e instanceof ApiError) {
        setError(e.message);
      } else {
        setError(`请求失败：${String(e)}`);
      }
    } finally {
      setLoading(false);
    }
  }, [graph, source, target, algorithm, allowNegative]);

  // 跑完后若切换目标节点，带上已算好的参数向后端重新请求路径回溯
  const stateRef = useRef({ graph, source });
  stateRef.current = { graph, source };
  useEffect(() => {
    if (!result || !source) return;
    if (target === lastTarget.current) return;
    lastTarget.current = target;
    let cancelled = false;
    (async () => {
      try {
        const { graph: latestGraph, source: latestSource } = stateRef.current;
        if (!latestSource) return;
        const res = await runAlgorithm(
          latestGraph,
          latestSource,
          result.algorithm,
          { target, allowNegative: result.warning != null },
        );
        if (!cancelled) {
          // 只替换 path，不打断当前播放
          setResult((prev) => (prev ? { ...prev, path: res.path } : prev));
        }
      } catch {
        /* 目标路径回溯失败时保持现状 */
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  // ---- 播放控制 --------------------------------------------------------

  const step = useCallback(
    (delta: number) => {
      if (!result) return;
      setPlaying(false);
      setStepIndex((i) => Math.min(result.steps.length - 1, Math.max(0, i + delta)));
    },
    [result],
  );

  const reset = () => {
    setPlaying(false);
    setStepIndex(0);
  };

  useEffect(() => {
    if (!playing || !result) return;
    if (stepIndex >= result.steps.length - 1) {
      setPlaying(false);
      return;
    }
    timerRef.current = window.setTimeout(() => {
      setStepIndex((i) => Math.min(result.steps.length - 1, i + 1));
    }, speed * 1000);
    return () => {
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
    };
  }, [playing, stepIndex, speed, result]);

  const changeSpeed = (factor: number) => {
    setSpeed((s) => Math.min(4, Math.max(0.1, +(s * factor).toFixed(2))));
  };

  // 图被改动后源点失效的保护
  useEffect(() => {
    if (source && !graph.nodes.some((n) => n.id === source)) setSource(null);
    if (target && !graph.nodes.some((n) => n.id === target)) setTarget(null);
  }, [graph.nodes, source, target]);

  const finalPathText = useMemo(() => {
    if (!result?.path) return null;
    const p = result.path;
    if (!p.exists) return `到 ${p.target}：${p.reason}`;
    return `最短路径 ${p.nodes.join(" → ")}，总权重 ${p.total_weight}`;
  }, [result]);

  const nodeIds = graph.nodes.map((n) => n.id);

  return (
    <div className="app">
      <header className="topbar">
        <h1>最短路径算法教学看板</h1>
        <div className="subtitle">
          带权有向图 · 单源最短路 · Dijkstra（非负权）对照 Bellman–Ford（负权 / 负权环检测）
        </div>
      </header>

      <div className="toolbar">
        <div className="tool-group">
          <button
            className={mode === "move" ? "tool tool-active" : "tool"}
            onClick={() => setMode("move")}
            title="拖动节点调整位置；从节点左上角小方块拖出可建立有向边"
          >
            ✥ 移动 / 连线
          </button>
          <button
            className={mode === "add-node" ? "tool tool-active" : "tool"}
            onClick={() => setMode("add-node")}
            title="在画布空白处单击添加节点"
          >
            ＋ 添加节点
          </button>
          <button
            className="tool tool-danger"
            onClick={deleteSelected}
            disabled={!selectedNode && !selectedEdge}
            title="删除选中的节点或边（Delete 键）"
          >
            🗑 删除选中
          </button>
          <button className="tool" onClick={clearGraph}>
            清空
          </button>
        </div>
        <div className="tool-group presets">
          <span className="presets-label">载入经典图：</span>
          {Object.entries(presets).map(([key, p]) => (
            <button key={key} className="preset-btn" onClick={() => loadPreset(key)}>
              {p.name}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="banner banner-error" onClick={() => setError(null)}>
          ⚠ {error}（点击关闭）
        </div>
      )}
      {result?.warning && (
        <div className="banner banner-warn">⚠ {result.warning}</div>
      )}
      {result?.has_negative_cycle && (
        <div className="banner banner-danger">
          ❗ 存在负权环，最短路不存在：环{" "}
          {result.cycle?.nodes.join(" → ") +
            " → " +
            result.cycle?.nodes[0]}
          （环权 {result.cycle?.weight}），环上及其可达节点距离为 −∞。
        </div>
      )}

      <main className="layout">
        <section className="canvas-wrap">
          <GraphCanvas
            graph={graph}
            mode={mode}
            result={result}
            currentStep={currentStep}
            source={source}
            target={target}
            selectedNode={selectedNode}
            selectedEdge={selectedEdge}
            onCanvasClickAddNode={addNode}
            onMoveNode={handleMoveNode}
            onCreateEdge={createEdge}
            onSelectNode={setSelectedNode}
            onSelectEdge={setSelectedEdge}
            onEditEdgeWeight={setEdgeWeight}
            onSetSource={(id) => {
              setSource(id);
              invalidateDemo();
            }}
            onSetTarget={setTarget}
          />
          <div className="legend">
            <span><i className="lg lg-source" />源点（右键节点设置）</span>
            <span><i className="lg lg-target" />目标</span>
            <span><i className="lg lg-settled" />已确定</span>
            <span><i className="lg lg-active" />当前松弛边</span>
            <span><i className="lg lg-cycle" />负权环</span>
            <span><i className="lg lg-path" />最短路径</span>
            <span className="legend-tip">
              双击边改权重（可负）· 拖节点移动 · 从节点左上角小方块拉线建边
            </span>
          </div>
        </section>

        <aside className="sidebar">
          <DemoControls
            graph={graph}
            source={source}
            target={target}
            algorithm={algorithm}
            allowNegative={allowNegative}
            result={result}
            stepIndex={stepIndex}
            stepCount={stepCount}
            playing={playing}
            speed={speed}
            loading={loading}
            onAlgorithmChange={(a) => {
              setAlgorithm(a);
              invalidateDemo();
            }}
            onAllowNegativeChange={setAllowNegative}
            onTargetChange={setTarget}
            onRun={run}
            onPlayPause={() => {
              if (!result) return;
              if (atEnd) setStepIndex(0);
              setPlaying((p) => !p);
            }}
            onStep={step}
            onReset={reset}
            onSpeed={changeSpeed}
          />

          <DistanceTable
            nodeIds={nodeIds}
            result={result}
            step={currentStep}
            source={source}
            target={target}
            playing={playing}
          />

          {finalPathText && (
            <div
              className={`banner ${
                result?.path?.exists ? "banner-good" : "banner-danger"
              } path-banner`}
            >
              {result?.path?.exists ? "✅ " : "⛔ "}
              {finalPathText}
            </div>
          )}
        </aside>
      </main>

      <section className="matrix-wrap">
        <AdjacencyMatrix
          graph={graph}
          source={source}
          onSetWeight={setEdgeWeight}
          onSetSource={(id) => {
            setSource(id);
            invalidateDemo();
          }}
        />
      </section>

      <footer className="footer">
        算法（Dijkstra / Bellman–Ford / 负权环检测 / 路径回溯）均由 FastAPI
        后端计算并保证正确性；前端只渲染后端返回的逐步状态，不自行重算。
        {hasNegativeEdge(graph) && algorithm === "dijkstra" && (
          <strong className="footer-warn"> 当前图含负权边，请改用 Bellman–Ford。</strong>
        )}
      </footer>
    </div>
  );
}
