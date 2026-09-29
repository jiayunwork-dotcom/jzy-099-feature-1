import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GraphCanvas, type ToolMode } from "./components/GraphCanvas";
import { AdjacencyMatrix } from "./components/AdjacencyMatrix";
import { DistanceTable } from "./components/DistanceTable";
import { DemoControls } from "./components/DemoControls";
import { ExperimentPanel } from "./components/ExperimentPanel";
import {
  runAlgorithm,
  fetchPresets,
  createExperiment,
  submitExperimentEdit,
  fetchExperimentVersion,
  deleteExperiment,
  ApiError,
} from "./api";
import type {
  Algorithm,
  ExperimentResult,
  ExperimentSummary,
  GraphData,
  PresetMap,
  RunResult,
} from "./types";
import { experimentToRunResult } from "./experimentAdapter";
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

  // ---- 动态实验状态 ----
  const [experimentActive, setExperimentActive] = useState(false);
  const [experimentId, setExperimentId] = useState<string | null>(null);
  const [experimentResult, setExperimentResult] =
    useState<ExperimentResult | null>(null);
  const [experimentSummary, setExperimentSummary] =
    useState<ExperimentSummary | null>(null);
  /** 正在回看的历史版本号；null 表示停在当前版本 */
  const [viewingVersion, setViewingVersion] = useState<number | null>(null);
  const [experimentBusy, setExperimentBusy] = useState(false);

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

  // 实验中正在回看历史版本（只读）
  const isViewingHistory =
    experimentActive &&
    viewingVersion !== null &&
    experimentResult !== null &&
    viewingVersion !== experimentResult.version;

  // ---- 普通模式：图编辑（作废演示） ------------------------------------

  const invalidateDemo = useCallback(() => {
    setResult(null);
    setPlaying(false);
    setStepIndex(0);
  }, []);

  const addNode = useCallback(
    (x: number, y: number) => {
      if (experimentActive && experimentId) {
        if (isViewingHistory) {
          setError("正在回看历史版本（只读）：请先回到当前版本再编辑。");
          return;
        }
        // 实验模式：加节点也作为一次编辑提交
        const nodeId = nextNodeId(graph);
        void submitExperimentAction({
          kind: "add_node",
          node_id: nodeId,
          x,
          y,
        });
        return;
      }
      setGraph((g) => {
        const id = nextNodeId(g);
        return { ...g, nodes: [...g.nodes, { id, x, y }] };
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [experimentActive, experimentId, isViewingHistory, graph],
  );

  const handleMoveNode = useCallback((id: string, x: number, y: number) => {
    // 坐标只用于画布布点，不参与任何距离计算，也不作为实验编辑
    setGraph((g) => ({
      ...g,
      nodes: g.nodes.map((n) => (n.id === id ? { ...n, x, y } : n)),
    }));
  }, []);

  const createEdge = useCallback(
    (u: string, v: string) => {
      if (experimentActive && experimentId) {
        if (isViewingHistory) {
          setError("正在回看历史版本（只读）：请先回到当前版本再编辑。");
          return;
        }
        if (findEdge(graph, u, v)) return;
        void submitExperimentAction({
          kind: "add_edge",
          source: u,
          target: v,
          weight: 1,
        });
        return;
      }
      setGraph((g) => {
        if (findEdge(g, u, v)) return g;
        return { ...g, edges: [...g.edges, { source: u, target: v, weight: 1 }] };
      });
      invalidateDemo();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [experimentActive, experimentId, isViewingHistory, graph, invalidateDemo],
  );

  const setEdgeWeight = useCallback(
    (u: string, v: string, weight: number) => {
      if (experimentActive && experimentId) {
        if (isViewingHistory) {
          setError("正在回看历史版本（只读）：请先回到当前版本再编辑。");
          return;
        }
        const exists = findEdge(graph, u, v);
        void submitExperimentAction(
          exists
            ? { kind: "set_weight", source: u, target: v, weight }
            : { kind: "add_edge", source: u, target: v, weight },
        );
        return;
      }
      setGraph((g) => upsertEdge(g, u, v, weight));
      invalidateDemo();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [experimentActive, experimentId, isViewingHistory, graph, invalidateDemo],
  );

  const deleteSelected = useCallback(() => {
    if (experimentActive && experimentId) {
      if (isViewingHistory) {
        setError("正在回看历史版本（只读）：请先回到当前版本再编辑。");
        return;
      }
      if (selectedNode) {
        void submitExperimentAction({ kind: "delete_node", node_id: selectedNode });
        setSelectedNode(null);
      } else if (selectedEdge) {
        void submitExperimentAction({
          kind: "delete_edge",
          source: selectedEdge[0],
          target: selectedEdge[1],
        });
        setSelectedEdge(null);
      }
      return;
    }
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    selectedNode, selectedEdge, source, target, invalidateDemo,
    experimentActive, experimentId, isViewingHistory,
  ]);

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
    // 载入新图一律退出实验（不同图 / 不同源，旧实验不再适用）
    exitExperimentInternal(false);
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
    exitExperimentInternal(false);
    setGraph({ nodes: [], edges: [] });
    setSource(null);
    setTarget(null);
    invalidateDemo();
  };

  // ---- 普通运行（全部由后端计算） --------------------------------------

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
    if (experimentActive) return;
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

  // ---- 动态实验：开 / 提交编辑 / 回看 / 退出 ---------------------------

  const applyExperimentResult = useCallback((r: ExperimentResult) => {
    setExperimentResult(r);
    setExperimentSummary((s) =>
      s
        ? {
            ...s,
            current_version: r.version,
            has_negative_cycle: r.has_negative_cycle,
            versions: s.versions.includes(r.version)
              ? s.versions
              : [...s.versions, r.version],
          }
        : s,
    );
    setGraph(r.graph);
    setResult(experimentToRunResult(r));
    setViewingVersion(null);
    // 先展示修复完成的末帧（能直接看到最终着色），学生可用 ⏮ 从头播放修复过程
    setStepIndex(Math.max(0, r.steps.length - 1));
    setPlaying(false);
  }, []);

  const startExperiment = useCallback(async () => {
    if (!source) return;
    setExperimentBusy(true);
    setError(null);
    try {
      const created = await createExperiment(graph, source);
      setExperimentId(created.experiment_id);
      setExperimentSummary({
        experiment_id: created.experiment_id,
        source,
        current_version: 0,
        has_negative_cycle: created.result.has_negative_cycle,
        created_at: Date.now() / 1000,
        last_accessed_at: Date.now() / 1000,
        versions: [0],
      });
      setExperimentActive(true);
      setViewingVersion(null);
      applyExperimentResult(created.result);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `开实验失败：${String(e)}`);
    } finally {
      setExperimentBusy(false);
    }
  }, [graph, source, applyExperimentResult]);

  // 用 ref 始终拿到最新版本号，避免回调闭包过期
  const experimentResultRef = useRef<ExperimentResult | null>(null);
  experimentResultRef.current = experimentResult;
  const experimentIdRef = useRef<string | null>(null);
  experimentIdRef.current = experimentId;

  const submitExperimentAction = useCallback(
    async (edit: import("./types").ExperimentEdit) => {
      const eid = experimentIdRef.current;
      const current = experimentResultRef.current;
      if (!eid || !current) return;
      // 回看历史时不允许编辑（先回到当前）
      setExperimentBusy(true);
      setError(null);
      try {
        const payload = { ...edit, base_version: current.version };
        const r = await submitExperimentEdit(eid, payload);
        applyExperimentResult(r);
      } catch (e) {
        if (e instanceof ApiError) setError(e.message);
        else setError(`编辑失败：${String(e)}`);
      } finally {
        setExperimentBusy(false);
      }
    },
    [applyExperimentResult],
  );

  const selectVersion = useCallback(
    async (version: number) => {
      const eid = experimentIdRef.current;
      const current = experimentResultRef.current;
      if (!eid || !current) return;
      if (version === current.version && viewingVersion === null) return;
      setExperimentBusy(true);
      setError(null);
      try {
        const r = await fetchExperimentVersion(eid, version);
        setExperimentResult(r);
        setGraph(r.graph);
        setResult(experimentToRunResult(r));
        setViewingVersion(version);
        setStepIndex(Math.max(0, r.steps.length - 1));
        setPlaying(false);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : `取版本失败：${String(e)}`);
      } finally {
        setExperimentBusy(false);
      }
    },
    [viewingVersion],
  );

  const exitExperimentInternal = useCallback((remoteDelete: boolean) => {
    const eid = experimentIdRef.current;
    setExperimentActive(false);
    setExperimentId(null);
    setExperimentResult(null);
    setExperimentSummary(null);
    setViewingVersion(null);
    setResult(null);
    setPlaying(false);
    setStepIndex(0);
    if (remoteDelete && eid) {
      void deleteExperiment(eid).catch(() => {
        /* 实验可能已被后端淘汰，忽略即可 */
      });
    }
  }, []);

  const exitExperiment = useCallback(() => {
    exitExperimentInternal(true);
  }, [exitExperimentInternal]);

  // 切换源点：实验绑定了源，直接退出实验
  const handleSetSource = useCallback(
    (id: string) => {
      if (experimentActive) exitExperimentInternal(true);
      setSource(id);
      invalidateDemo();
    },
    [experimentActive, exitExperimentInternal, invalidateDemo],
  );

  // 实验中被后端拒绝（如版本落后）时，把画布对齐回当前版本图
  useEffect(() => {
    if (
      experimentActive &&
      experimentResult &&
      !isViewingHistory &&
      error &&
      (error.includes("版本") || error.includes("不存在") || error.includes("已存在"))
    ) {
      setGraph(experimentResult.graph);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);

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
          {experimentActive && " · 🧪 动态实验（增量修复）"}
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
      {experimentActive && experimentResult?.mode === "full" &&
        experimentResult.version > 0 && (
          <div className="banner banner-warn">
            🔁 第 {experimentResult.version} 版退回了全量重算：
            {experimentResult.reason}
          </div>
        )}
      {isViewingHistory && (
        <div className="banner banner-info">
          🕘 正在回看历史版本 v{viewingVersion}（只读）；在画布上编辑或点
          v{experimentResult?.version} 回到当前。
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
            onSetSource={handleSetSource}
            onSetTarget={setTarget}
            experimentMode={experimentActive}
          />
          <div className="legend">
            <span><i className="lg lg-source" />源点（右键节点设置）</span>
            <span><i className="lg lg-target" />目标</span>
            {experimentActive ? (
              <>
                <span><i className="lg lg-invalidated" />作废重算</span>
                <span><i className="lg lg-reprocessed" />重新处理</span>
                <span><i className="lg lg-untouched" />没被碰到</span>
              </>
            ) : (
              <>
                <span><i className="lg lg-settled" />已确定</span>
                <span><i className="lg lg-active" />当前松弛边</span>
              </>
            )}
            <span><i className="lg lg-cycle" />负权环</span>
            <span><i className="lg lg-path" />最短路径</span>
            <span className="legend-tip">
              双击边改权重（可负）· 拖节点移动 · 从节点左上角小方块拉线建边
            </span>
          </div>
        </section>

        <aside className="sidebar">
          <ExperimentPanel
            active={experimentActive}
            source={source}
            loading={experimentBusy}
            experimentId={experimentId}
            summary={experimentSummary}
            currentResult={experimentResult}
            viewingVersion={viewingVersion}
            onStart={startExperiment}
            onExit={exitExperiment}
            onSelectVersion={selectVersion}
          />

          {!experimentActive && (
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
          )}

          {experimentActive && result && (
            <div className="panel controls-panel experiment-playback">
              <div className="panel-title">
                修复过程演示
                <span className="panel-sub">
                  {experimentResult?.mode === "incremental"
                    ? "作废 → 边界播种 / 种子扩散 → 收敛"
                    : "本版为全量 Bellman–Ford 逐轮演示"}
                </span>
              </div>
              <div className="playback-row">
                <button className="pb" onClick={() => step(-1)} title="上一步">⏮</button>
                <button
                  className="pb pb-play"
                  onClick={() => {
                    if (atEnd) setStepIndex(0);
                    setPlaying((p) => !p);
                  }}
                >
                  {playing ? "⏸ 暂停" : "▶ 播放"}
                </button>
                <button className="pb" onClick={() => step(1)} title="下一步">⏭</button>
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
                <button className="pb" onClick={reset} title="回到第一步">⟲</button>
              </div>
              <div className="speed-row">
                <span>速度</span>
                <button className="speed-btn" onClick={() => changeSpeed(1 / 1.6)}>
                  减速 −
                </button>
                <span className="speed-val">{speed.toFixed(2)}s/步</span>
                <button className="speed-btn" onClick={() => changeSpeed(1.6)}>
                  加速 +
                </button>
              </div>
            </div>
          )}

          <DistanceTable
            nodeIds={nodeIds}
            result={result}
            step={currentStep}
            source={source}
            target={target}
            playing={playing}
            experimentMode={experimentActive}
            changed={experimentResult?.changed ?? []}
            reprocessed={experimentResult?.reprocessed ?? []}
          />

          {finalPathText && !experimentActive && (
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
          onSetSource={handleSetSource}
        />
      </section>

      <footer className="footer">
        算法（Dijkstra / Bellman–Ford / 负权环检测 / 路径回溯 / 动态增量修复）
        均由 FastAPI 后端计算并保证正确性；前端只渲染后端返回的逐步状态，不自行重算。
        {hasNegativeEdge(graph) && algorithm === "dijkstra" && !experimentActive && (
          <strong className="footer-warn"> 当前图含负权边，请改用 Bellman–Ford。</strong>
        )}
        {experimentActive && (
          <strong className="footer-exp">
            {" "}动态实验中：每次改边都是一次带版本号的编辑，后端在上一版结果上增量修复。
          </strong>
        )}
      </footer>
    </div>
  );
}
