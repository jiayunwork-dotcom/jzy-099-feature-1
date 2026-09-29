import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GraphCanvas, type ToolMode } from "./components/GraphCanvas";
import { AdjacencyMatrix } from "./components/AdjacencyMatrix";
import { DistanceTable } from "./components/DistanceTable";
import { DemoControls } from "./components/DemoControls";
import { ExperimentPanel } from "./components/ExperimentPanel";
import { VersionList } from "./components/VersionList";
import {
  runAlgorithm,
  fetchPresets,
  ApiError,
  createExperiment,
  submitExperimentEdit,
  fetchExperimentHistory,
  fetchExperimentVersion,
} from "./api";
import type {
  Algorithm,
  EditKind,
  ExperimentHistory,
  ExperimentVersion,
  GraphData,
  PresetMap,
  RunResult,
  Step,
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

interface ExperimentSession {
  id: string;
  /** 当前最新版本的完整结果（普通状态：非回看） */
  current: ExperimentVersion;
  history: ExperimentHistory;
  /** 非 null 表示正在回看这个历史版本（只读） */
  viewingVersion: ExperimentVersion | null;
}

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

  // 动态实验
  const [experiment, setExperiment] = useState<ExperimentSession | null>(null);
  const [expStepIndex, setExpStepIndex] = useState(0);
  const [expPlaying, setExpPlaying] = useState(false);

  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<[string, string] | null>(null);
  const [presets, setPresets] = useState<PresetMap>({});

  const timerRef = useRef<number | null>(null);
  // 防止在上一个编辑响应返回前叠加提交（否则后一个会因版本落后被 409）
  const editInFlight = useRef(false);
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

  // ---- 实验态派生 ----
  const inExperiment = experiment !== null;
  const viewedVersion = experiment?.viewingVersion ?? experiment?.current ?? null;
  const expSteps = viewedVersion?.steps ?? [];
  const expCurrentStep: Step | null =
    viewedVersion && expStepIndex < expSteps.length ? expSteps[expStepIndex] : null;
  const expReadOnly = experiment?.viewingVersion != null;

  // ---- 图编辑（普通模式） ----------------------------------------------

  const invalidateDemo = useCallback(() => {
    setResult(null);
    setPlaying(false);
    setStepIndex(0);
  }, []);

  const addNode = useCallback(
    (x: number, y: number) => {
      if (inExperiment) return; // 实验只支持边编辑
      setGraph((g) => {
        const id = nextNodeId(g);
        return { ...g, nodes: [...g.nodes, { id, x, y }] };
      });
    },
    [inExperiment],
  );

  const handleMoveNode = useCallback((id: string, x: number, y: number) => {
    setGraph((g) => ({
      ...g,
      nodes: g.nodes.map((n) => (n.id === id ? { ...n, x, y } : n)),
    }));
  }, []);

  const refreshHistory = useCallback(async (id: string) => {
    const history = await fetchExperimentHistory(id);
    setExperiment((s) => (s && s.id === id ? { ...s, history } : s));
  }, []);

  // ---- 实验态：把一次边编辑提交给后端做增量修复 ------------------------

  const submitEdgeEdit = useCallback(
    async (kind: EditKind, u: string, v: string, weight: number | null) => {
      if (!experiment || experiment.viewingVersion) return;
      if (editInFlight.current) return; // 上一个编辑还没回来，不叠加提交
      editInFlight.current = true;
      const session = experiment;
      setLoading(true);
      setError(null);
      try {
        const positions: Record<string, { x: number; y: number }> = {};
        graph.nodes.forEach((n) => {
          positions[n.id] = { x: n.x, y: n.y };
        });
        const next = await submitExperimentEdit(session.id, {
          base_version: session.current.version,
          kind,
          source: u,
          target: v,
          weight,
          positions,
        });
        setGraph(structuredClone(next.graph));
        setExperiment({
          id: session.id,
          current: next,
          history: session.history,
          viewingVersion: null,
        });
        setExpStepIndex(0);
        setExpPlaying(true);
        await refreshHistory(session.id);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : `请求失败：${String(e)}`);
      } finally {
        editInFlight.current = false;
        setLoading(false);
      }
    },
    [experiment, graph, refreshHistory],
  );

  const createEdge = useCallback(
    (u: string, v: string) => {
      if (inExperiment) {
        // 实验态：拉线即「新增边」编辑（默认权 1）
        if (findEdge(graph, u, v)) return;
        void submitEdgeEdit("add_edge", u, v, 1);
        return;
      }
      setGraph((g) => {
        if (findEdge(g, u, v)) return g;
        return { ...g, edges: [...g.edges, { source: u, target: v, weight: 1 }] };
      });
      invalidateDemo();
    },
    [inExperiment, graph, invalidateDemo, submitEdgeEdit],
  );

  const setEdgeWeight = useCallback(
    (u: string, v: string, weight: number) => {
      if (inExperiment) {
        if (!findEdge(graph, u, v)) {
          // 矩阵里在空格子上提交：作为新增边编辑
          void submitEdgeEdit("add_edge", u, v, weight);
        } else {
          void submitEdgeEdit("update_weight", u, v, weight);
        }
        return;
      }
      setGraph((g) => upsertEdge(g, u, v, weight));
      invalidateDemo();
    },
    [inExperiment, graph, invalidateDemo, submitEdgeEdit],
  );

  const deleteSelected = useCallback(() => {
    if (inExperiment) {
      // 实验只允许删边；删节点需要先退出实验
      if (selectedEdge) {
        const [u, v] = selectedEdge;
        setSelectedEdge(null);
        void submitEdgeEdit("delete_edge", u, v, null);
      } else if (selectedNode) {
        setError("动态实验只支持边编辑：请先退出实验再删除节点。");
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
  }, [
    inExperiment, selectedNode, selectedEdge, source, target,
    invalidateDemo, submitEdgeEdit,
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
    setExperiment(null); // 换图即退出实验
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
    setExperiment(null);
    setGraph({ nodes: [], edges: [] });
    setSource(null);
    setTarget(null);
    invalidateDemo();
  };

  // ---- 动态实验开关 ----------------------------------------------------

  const startExperiment = useCallback(async () => {
    if (!source) {
      setError("开实验前请先设置源点。");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const v0 = await createExperiment(graph, source);
      // 以版本 0 的图为准（坐标不变）
      setGraph(structuredClone(v0.graph));
      setResult(null);
      setPlaying(false);
      setStepIndex(0);
      const history = await fetchExperimentHistory(v0.experiment_id);
      setExperiment({
        id: v0.experiment_id,
        current: v0,
        history,
        viewingVersion: null,
      });
      setExpStepIndex(0);
      setExpPlaying(false);
      setSelectedNode(null);
      setSelectedEdge(null);
      setMode("move");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `开实验失败：${String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [graph, source]);

  const exitExperiment = useCallback(() => {
    setExperiment(null);
    setExpPlaying(false);
    setExpStepIndex(0);
  }, []);

  const viewVersion = useCallback(async (version: number) => {
    if (!experiment) return;
    if (version === experiment.current.version) {
      setExperiment({ ...experiment, viewingVersion: null });
      setExpStepIndex(0);
      setExpPlaying(false);
      return;
    }
    setLoading(true);
    try {
      const past = await fetchExperimentVersion(experiment.id, version);
      setGraph(structuredClone(past.graph));
      setExperiment({ ...experiment, viewingVersion: past });
      setExpStepIndex(0);
      setExpPlaying(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `取回版本失败：${String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [experiment]);

  const backToLatest = useCallback(() => {
    if (!experiment) return;
    setGraph(structuredClone(experiment.current.graph));
    setExperiment({ ...experiment, viewingVersion: null });
    setExpStepIndex(0);
    setExpPlaying(false);
  }, [experiment]);

  // 实验帧自动播放
  useEffect(() => {
    if (!expPlaying || !viewedVersion) return;
    if (expStepIndex >= expSteps.length - 1) {
      setExpPlaying(false);
      return;
    }
    timerRef.current = window.setTimeout(() => {
      setExpStepIndex((i) => Math.min(expSteps.length - 1, i + 1));
    }, speed * 1000);
    return () => {
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
    };
  }, [expPlaying, expStepIndex, speed, viewedVersion, expSteps.length]);

  // ---- 运行算法（普通模式，全部由后端计算） ----------------------------

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
    if (inExperiment) return;
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
  }, [target, inExperiment]);

  // ---- 播放控制（普通模式） --------------------------------------------

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

  // ---- 实验播放控制 ----
  const expStep = useCallback((delta: number) => {
    setExpPlaying(false);
    setExpStepIndex((i) => Math.min(expSteps.length - 1, Math.max(0, i + delta)));
  }, [expSteps.length]);
  const expReset = useCallback(() => {
    setExpPlaying(false);
    setExpStepIndex(0);
  }, []);

  // 图被改动后源点失效的保护（实验态节点集不变，仅普通模式需要）
  useEffect(() => {
    if (inExperiment) return;
    if (source && !graph.nodes.some((n) => n.id === source)) setSource(null);
    if (target && !graph.nodes.some((n) => n.id === target)) setTarget(null);
  }, [graph.nodes, source, target, inExperiment]);

  const finalPathText = useMemo(() => {
    if (!result?.path) return null;
    const p = result.path;
    if (!p.exists) return `到 ${p.target}：${p.reason}`;
    return `最短路径 ${p.nodes.join(" → ")}，总权重 ${p.total_weight}`;
  }, [result]);

  const nodeIds = graph.nodes.map((n) => n.id);

  const setSourceSafe = (id: string) => {
    if (inExperiment) {
      setError("实验绑定的源点固定，改源点请先退出实验。");
      return;
    }
    setSource(id);
    invalidateDemo();
  };

  return (
    <div className="app">
      <header className="topbar">
        <h1>最短路径算法教学看板</h1>
        <div className="subtitle">
          {inExperiment
            ? "动态实验模式：每次改边只在上一版结果上做增量修复，对比「修了哪里、为什么只修这里」"
            : "带权有向图 · 单源最短路 · Dijkstra（非负权）对照 Bellman–Ford（负权 / 负权环检测）"}
        </div>
      </header>

      <div className="toolbar">
        <div className="tool-group">
          <button
            className={mode === "move" ? "tool tool-active" : "tool"}
            onClick={() => setMode("move")}
            title="拖动节点调整位置；从节点左上角小方块拖出可建立有向边"
            disabled={inExperiment}
          >
            ✥ 移动 / 连线
          </button>
          <button
            className={mode === "add-node" ? "tool tool-active" : "tool"}
            onClick={() => setMode("add-node")}
            title="在画布空白处单击添加节点（实验模式不支持增删节点）"
            disabled={inExperiment}
          >
            ＋ 添加节点
          </button>
          <button
            className="tool tool-danger"
            onClick={deleteSelected}
            disabled={!selectedNode && !selectedEdge}
            title={
              inExperiment
                ? "删除选中的边（Delete 键）；实验中不能删节点"
                : "删除选中的节点或边（Delete 键）"
            }
          >
            🗑 删除选中
          </button>
          <button className="tool" onClick={clearGraph}>
            清空
          </button>
          {!inExperiment ? (
            <button
              className="tool tool-experiment"
              onClick={startExperiment}
              disabled={!source || loading || nodeIds.length === 0}
              title={
                !source
                  ? "请先设置源点再开实验"
                  : "对当前图与源点开启动态实验：之后改边只做增量修复"
              }
            >
              🧪 开启动态实验
            </button>
          ) : (
            <button className="tool tool-experiment tool-experiment-on" onClick={exitExperiment}>
              ⏹ 退出实验（回到整图运行）
            </button>
          )}
        </div>
        <div className="tool-group presets">
          <span className="presets-label">载入经典图：</span>
          {Object.entries(presets).map(([key, p]) => (
            <button
              key={key}
              className="preset-btn"
              onClick={() => loadPreset(key)}
              title="载入示例图会退出当前实验"
            >
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
      {!inExperiment && result?.warning && (
        <div className="banner banner-warn">⚠ {result.warning}</div>
      )}
      {!inExperiment && result?.has_negative_cycle && (
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
            mode={inExperiment ? "move" : mode}
            result={inExperiment ? null : result}
            currentStep={inExperiment ? null : currentStep}
            source={source}
            target={inExperiment ? null : target}
            selectedNode={selectedNode}
            selectedEdge={selectedEdge}
            experiment={
              inExperiment && viewedVersion
                ? {
                    current: viewedVersion,
                    step: expCurrentStep,
                    readOnly: expReadOnly,
                  }
                : null
            }
            onCanvasClickAddNode={addNode}
            onMoveNode={handleMoveNode}
            onCreateEdge={createEdge}
            onSelectNode={setSelectedNode}
            onSelectEdge={setSelectedEdge}
            onEditEdgeWeight={setEdgeWeight}
            onSetSource={setSourceSafe}
            onSetTarget={setTarget}
          />
          <div className="legend">
            {inExperiment ? (
              <>
                <span><i className="lg lg-source" />源点（实验中固定）</span>
                <span><i className="lg lg-exp-invalid" />作废重算</span>
                <span><i className="lg lg-exp-changed" />距离改变</span>
                <span><i className="lg lg-exp-repro" />重处理但距离同值</span>
                <span><i className="lg lg-exp-untouched" />未触碰</span>
                <span><i className="lg lg-cycle" />负权环</span>
                <span className="legend-tip">
                  双击边改权 · 拉线加边 · 选中边删除，全部走实验编辑（不再整图重跑）
                  {expReadOnly ? " · 历史回看只读" : ""}
                </span>
              </>
            ) : (
              <>
                <span><i className="lg lg-source" />源点（右键节点设置）</span>
                <span><i className="lg lg-target" />目标</span>
                <span><i className="lg lg-settled" />已确定</span>
                <span><i className="lg lg-active" />当前松弛边</span>
                <span><i className="lg lg-cycle" />负权环</span>
                <span><i className="lg lg-path" />最短路径</span>
                <span className="legend-tip">
                  双击边改权重（可负）· 拖节点移动 · 从节点左上角小方块拉线建边
                </span>
              </>
            )}
          </div>
        </section>

        <aside className="sidebar">
          {inExperiment && viewedVersion ? (
            <>
              <ExperimentPanel
                current={viewedVersion}
                viewingVersion={experiment.viewingVersion?.version ?? null}
                stepIndex={expStepIndex}
                stepCount={expSteps.length}
                playing={expPlaying}
                speed={speed}
                loading={loading}
                onPlayPause={() => {
                  if (expStepIndex >= expSteps.length - 1) setExpStepIndex(0);
                  setExpPlaying((p) => !p);
                }}
                onStep={expStep}
                onReset={expReset}
                onSpeed={changeSpeed}
                onExit={exitExperiment}
                onBackToLatest={backToLatest}
              />
              <VersionList
                history={experiment.history}
                current={viewedVersion}
                viewingVersion={experiment.viewingVersion?.version ?? null}
                onSelect={(v) => void viewVersion(v)}
              />
            </>
          ) : (
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

          <DistanceTable
            nodeIds={nodeIds}
            result={inExperiment ? null : result}
            step={inExperiment ? null : currentStep}
            source={source}
            target={target}
            playing={inExperiment ? expPlaying : playing}
            experiment={inExperiment ? viewedVersion : null}
            expStep={expCurrentStep}
          />

          {!inExperiment && finalPathText && (
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
          readOnly={expReadOnly}
          experimentMode={inExperiment}
          onSetWeight={setEdgeWeight}
          onSetSource={setSourceSafe}
        />
      </section>

      <footer className="footer">
        算法（Dijkstra / Bellman–Ford / 负权环检测 / 路径回溯 / 动态增量修复）
        均由 FastAPI 后端计算并保证正确性；前端只渲染后端返回的逐步状态，不自行重算。
        {!inExperiment && hasNegativeEdge(graph) && algorithm === "dijkstra" && (
          <strong className="footer-warn"> 当前图含负权边，请改用 Bellman–Ford。</strong>
        )}
        {inExperiment && (
          <strong className="footer-exp">
            {" "}动态实验：增量修复在负权下仍给出正确结果；产生 / 打破负权环时会如实标注并退回全量。
          </strong>
        )}
      </footer>
    </div>
  );
}
