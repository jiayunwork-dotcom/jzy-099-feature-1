"""动态修复 trace、计数与局部性的细粒度测试。"""

from app.dynamic.edits import EdgeEdit
from app.dynamic.reference import full_bellman_ford
from ..conftest import make_graph


def test_initial_version_is_full_with_complete_bf_trace(svc):
    g = make_graph(["A", "B"], [("A", "B", 1)])
    _, v0 = svc.create_experiment(g, "A")
    assert v0.mode == "initial"
    assert v0.version == 0
    assert v0.relax_count == v0.full_relax_count
    assert v0.steps[0]["type"] == "init"
    assert v0.steps[-1]["type"] == "finished"


def test_incremental_steps_tell_the_repair_story(svc):
    g = make_graph(
        ["A", "B", "C", "D"],
        [("A", "B", 1), ("B", "C", 1), ("A", "D", 9), ("C", "D", 1)],
    )
    exp, v0 = svc.create_experiment(g, "A")
    # pred 树：A→B→C→D；调大 A→B，子树 {B,C,D} 全部作废
    exp, v1 = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 8.0), 0
    )
    types = [s["type"] for s in v1.steps]
    assert types[0] == "repair_edit"
    assert "repair_invalidate_plan" in types
    assert "repair_invalidated" in types
    assert "repair_boundary" in types
    assert types[-1] == "repair_finished"

    # 作废帧中 B,C,D 被标为 invalidated，A 始终不在其中
    for step in v1.steps:
        assert "A" not in step["invalidated"]
    invalidate_frames = [s for s in v1.steps if s["type"] == "repair_invalidated"]
    assert set(invalidate_frames[0]["invalidated"]) == {"B", "C", "D"}
    # 每一帧都带完整距离/前驱快照
    for step in v1.steps:
        assert set(step["dist"]) == {"A", "B", "C", "D"}
        assert set(step["pred"]) == {"A", "B", "C", "D"}


def test_noop_non_tree_edge_has_single_noop_frame(svc):
    g = make_graph(["A", "B", "C"], [("A", "B", 5), ("A", "C", 1), ("C", "B", 1)])
    exp, _ = svc.create_experiment(g, "A")
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 50.0), 0
    )
    assert rec.relax_count == 0
    assert any(s["type"] == "repair_noop" for s in rec.steps)
    assert all(s["type"] in {"repair_edit", "repair_noop"} for s in rec.steps)


def test_decrease_propagates_wave_by_wave_and_stops(svc):
    # 一条链 A→B→C→D，把 A→B 从 10 调小到 1：改进逐层传播三层
    g = make_graph(
        ["A", "B", "C", "D"],
        [("A", "B", 10), ("B", "C", 10), ("C", "D", 10)],
    )
    exp, _ = svc.create_experiment(g, "A")
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 1.0), 0
    )
    assert rec.dist == {"A": 0.0, "B": 1.0, "C": 11.0, "D": 21.0}
    assert rec.reprocessed == ["B", "C", "D"]
    assert {c["node"] for c in rec.changed} == {"B", "C", "D"}
    waves = [s["pass"] for s in rec.steps if s["type"] == "repair_wave_start"]
    assert waves == [1, 2, 3]
    # 全量口径：3 条边；边序为链顺序时 BF 第 1 轮即传到底、第 2 轮提前停止，
    # 再加固定的检测轮 → 3 边 × 3 轮 = 9
    assert rec.full_relax_count == 9
    assert rec.relax_count == 3
    assert rec.relax_count <= rec.full_relax_count / 3


def test_add_edge_can_make_unreachable_node_reachable(svc):
    g = make_graph(["A", "B"], [("A", "A", 1)])
    exp, v0 = svc.create_experiment(g, "A")
    assert v0.dist["B"] is None
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.ADD, "A", "B", 3.0), 0
    )
    assert rec.dist["B"] == 3.0
    assert rec.changed == [{"node": "B", "before": None, "after": 3.0}]
    assert rec.pred["B"] == "A"
    assert rec.reprocessed == ["B"]


def test_delete_tree_edge_can_make_subtree_unreachable(svc):
    g = make_graph(
        ["A", "B", "C"], [("A", "B", 1), ("B", "C", 1), ("A", "A", 0)]
    )
    exp, _ = svc.create_experiment(g, "A")
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.DELETE, "B", "C"), 0
    )
    assert rec.dist["B"] == 1.0
    assert rec.dist["C"] is None
    assert rec.pred["C"] is None
    assert rec.changed == [{"node": "C", "before": 2.0, "after": None}]


def test_negative_weight_decrease_matches_full(svc):
    g = make_graph(
        ["A", "B", "C", "D"],
        [("A", "B", 4), ("A", "C", 5), ("B", "D", 7),
         ("C", "B", -3), ("C", "D", 5), ("D", "A", 8)],
    )
    exp, _ = svc.create_experiment(g, "A")
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "C", "B", -7.0), 0
    )
    ref = full_bellman_ford(rec.graph, "A")
    assert rec.mode == "incremental"
    assert rec.dist == ref.dist


def test_new_negative_self_loop_is_detected_via_full(svc):
    g = make_graph(["A", "B"], [("A", "B", 2)])
    exp, _ = svc.create_experiment(g, "A")
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.ADD, "A", "A", -1.0), 0
    )
    assert rec.mode == "full"
    assert rec.has_negative_cycle is True
    assert rec.cycle["nodes"] == ["A"]
    assert rec.dist["A"] is None and rec.dist["B"] is None


def test_positive_cycle_is_not_reported(svc):
    """环权为正（B→C=10、C→B=−6，环权 +4）不得误报为负权环。

    这是一个容易误判的陷阱：新增 C→B（−6）后会更新 d[B]，但环总体为正。
    """
    g = make_graph(
        ["A", "B", "C", "D"],
        [("A", "B", 3), ("A", "C", 6), ("B", "C", 10), ("B", "D", 5)],
    )
    exp, _ = svc.create_experiment(g, "A")
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.ADD, "C", "B", -6.0), 0
    )
    assert rec.has_negative_cycle is False
    assert rec.mode == "incremental"
    ref = full_bellman_ford(rec.graph, "A")
    assert rec.dist == ref.dist
    assert rec.dist == {"A": 0.0, "B": 0.0, "C": 6.0, "D": 5.0}


def test_hidden_negative_cycle_through_already_processed_node(svc):
    """负环沿「已经处理过」的节点绕回时也必须检出。

    新增 C→B（−2）先把 B 降低；B→C 当时不再松弛，但环绕一圈后
    （B→C=2、C→B=−2，环权 0 不算），构造真正为负的环权 −1：
    B→C=1、C→B=−2。即使 B 已被波次处理过，安全校验仍须发现它。
    """
    g = make_graph(
        ["A", "B", "C"],
        [("A", "B", 3), ("A", "C", 6), ("B", "C", 1)],
    )
    exp, _ = svc.create_experiment(g, "A")
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.ADD, "C", "B", -2.0), 0
    )
    # 环权 1 + (−2) = −1 < 0
    assert rec.has_negative_cycle is True
    assert rec.mode == "full"
    assert set(rec.cycle["nodes"]) == {"B", "C"}
    assert rec.dist["A"] == 0.0
    for node in ("B", "C"):
        assert rec.dist[node] is None


def test_detection_frames_when_cycle_needs_safety_check(svc):
    """正环会走完安全校验帧并被正确放行（不误报、随后正常结束）。"""
    g = make_graph(
        ["A", "B", "C"],
        [("A", "B", 3), ("A", "C", 8), ("B", "C", 10)],
    )
    exp, _ = svc.create_experiment(g, "A")
    # 新增 C→B（−6）与 B→C（10）构成环权 +4 的环：先降低 B，但非负环
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.ADD, "C", "B", -6.0), 0
    )
    types_ = [s["type"] for s in rec.steps]
    assert "repair_detect_start" in types_
    assert "repair_negative_cycle" not in types_
    assert types_[-1] == "repair_finished"
    assert rec.has_negative_cycle is False
    assert rec.mode == "incremental"


def test_detection_frames_when_cycle_caught_in_wave(svc):
    """传播前沿直接绕出长度 n 的环：波次阶段即检出。"""
    g = make_graph(
        ["A", "B", "C"],
        [("A", "B", 3), ("A", "C", 6), ("B", "C", 2)],
    )
    exp, _ = svc.create_experiment(g, "A")
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.ADD, "C", "B", -6.0), 0
    )
    types_ = [s["type"] for s in rec.steps]
    assert "repair_negative_cycle" in types_
    assert types_.index("repair_negative_cycle") < types_.index("repair_full")


def test_relax_count_counts_checked_edges_not_updates(svc):
    # 调小一条边但它不能松弛：触发边被检查（计 1），但没有更新
    g = make_graph(["A", "B"], [("A", "B", 1)])
    exp, _ = svc.create_experiment(g, "A")
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 0.5), 0
    )
    assert rec.relax_count == 1
    assert rec.changed[0]["before"] == 1.0
    # 再调大（树边）：子树 {B}，边界边 A→B 被检查一次
    exp, rec = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 6.0), rec.version
    )
    assert rec.relax_count == 1
    assert rec.dist["B"] == 6.0


def test_full_relax_count_is_e_times_passes_like_teaching_bf():
    # 与教学版 run_bellman_ford 的口径一致：每轮检查全部边（含检测轮）
    g = make_graph(
        ["C", "D", "B", "A"],
        [("C", "D", 2), ("B", "C", 3), ("A", "B", 5)],
    )
    ref = full_bellman_ford(g, "A")
    # 逆序链：3 轮传播 + 1 轮检测，每轮 3 条边
    assert ref.relax_count == 12
    assert ref.dist["D"] == 10.0
