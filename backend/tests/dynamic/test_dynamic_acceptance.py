"""验收主线（动态增量修复）：

1. 随机图（含负权边、含不可达节点）上各做 ≥200 次随机编辑，
   每次返回的距离表都与同图全量 Bellman–Ford 完全一致，前驱链合法；
2. 调大非树边 / 改动不可达区域边：距离变化与被重处理集合均为空；
3. 调大树边：被重处理节点全部落在对应前驱子树内；
4. 30 节点逆序单链调最后一条边：只重处理链尾、松弛数 ≤ 全量 1/10；
5. 版本号落后的编辑被拒绝，实验版本与距离表不变；
6. 制造再打破源点可达负权环：状态与距离两次正确，打破那步标明全量；
7. 按版本号取回的历史结果与当时编辑返回的结果一致。
"""

import random

import pytest

from app.dynamic.edits import EdgeEdit
from app.dynamic.reference import full_bellman_ford
from app.dynamic.repair import _pred_subtree
from app.dynamic.store import VersionConflict
from ..conftest import make_graph
from .conftest import (
    apply_edit_locally,
    assert_predecessors_legal,
    random_edit,
    random_graph,
)


# ---- 验收 1：≥200 次随机编辑后，增量结果始终等于全量 Bellman–Ford -------

@pytest.mark.parametrize("seed", [11, 23, 37, 51, 67])
def test_acceptance_1_random_edits_match_full_bellman_ford(seed, svc):
    rng = random.Random(seed)
    n = rng.randrange(6, 11)
    graph = random_graph(rng, n, edge_prob=0.18)
    source = graph.node_ids[0]

    experiment, record = svc.create_experiment(graph, source)
    reference = full_bellman_ford(record.graph, source)
    assert record.dist == reference.dist

    present = {(e.source, e.target) for e in record.graph.edges}
    edits_applied = 0
    target_edits = 205
    while edits_applied < target_edits:
        edit = random_edit(rng, record.graph)
        if edit is None:
            continue
        experiment, record = svc.submit_edit(
            experiment.id, edit, record.version
        )
        apply_edit_locally(present, edit)
        edits_applied += 1

        reference = full_bellman_ford(record.graph, source)
        assert record.dist == reference.dist, (
            f"seed={seed} edit#{edits_applied} {edit.describe()}\n"
            f"增量：{record.dist}\n全量：{reference.dist}"
        )
        assert record.has_negative_cycle == reference.has_negative_cycle
        assert_predecessors_legal(
            record.graph, source, record.dist, record.pred
        )
        if reference.has_negative_cycle:
            # 环上及其下游节点必须标注为不存在有限值
            for v in reference.affected:
                assert record.dist[v] is None
            assert set(record.affected) == set(reference.affected)
            assert record.mode == "full"

    assert record.version == edits_applied


def test_reachable_distance_is_exact_path_weight(svc):
    """额外不变量：每个有限距离都等于其前驱链上的真实边权之和。"""
    rng = random.Random(99)
    graph = random_graph(rng, 8, edge_prob=0.22)
    source = graph.node_ids[0]
    exp, rec = svc.create_experiment(graph, source)
    edge_index = {(e.source, e.target): e.weight for e in rec.graph.edges}
    for _ in range(120):
        edit = random_edit(rng, rec.graph)
        if edit is None:
            continue
        exp, rec = svc.submit_edit(exp.id, edit, rec.version)
        if rec.has_negative_cycle:
            continue
        edge_index.clear()
        edge_index.update(
            {(e.source, e.target): e.weight for e in rec.graph.edges}
        )
        for v, d in rec.dist.items():
            if d is None:
                continue
            total, cur = 0.0, v
            while cur != source:
                p = rec.pred[cur]
                total += edge_index[(p, cur)]
                cur = p
            assert abs(total - d) < 1e-9


# ---- 验收 2：非树边调大 / 不可达区域改动 → 空变化、空重处理 -------------

def test_acceptance_2_increase_non_tree_edge_is_noop(svc):
    g = make_graph(
        ["A", "B", "C", "D", "E", "F"],
        [
            ("A", "B", 7), ("A", "C", 3), ("C", "B", 2), ("B", "D", 4),
            ("C", "D", 9), ("B", "E", 15), ("C", "E", 20), ("D", "E", 1),
        ],
    )
    exp, v0 = svc.create_experiment(g, "A")
    # pred[B] = C，A→B 不是树边；调大它距离应纹丝不动
    exp, v1 = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 1000.0), v0.version
    )
    assert v1.dist == v0.dist
    assert v1.changed == []
    assert v1.reprocessed == []
    assert v1.relax_count == 0
    assert v1.mode == "incremental"

    # 删除这条非树边同样无影响
    exp, v2 = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.DELETE, "A", "B"), v1.version
    )
    assert v2.dist == v0.dist
    assert v2.changed == []
    assert v2.reprocessed == []


def test_acceptance_2_edit_in_unreachable_region_is_noop(svc):
    # D→E 位于源点 A 不可达的区域（A、B 与 D、E 不连通）
    g = make_graph(
        ["A", "B", "D", "E"],
        [("A", "B", 2), ("D", "E", 3), ("E", "D", -2)],
    )
    exp, v0 = svc.create_experiment(g, "A")
    assert v0.dist == {"A": 0.0, "B": 2.0, "D": None, "E": None}

    edits = (
        EdgeEdit(EdgeEdit.UPDATE, "D", "E", 100.0),
        EdgeEdit(EdgeEdit.UPDATE, "E", "D", -9.0),
        EdgeEdit(EdgeEdit.DELETE, "D", "E"),
        EdgeEdit(EdgeEdit.ADD, "E", "E", -1.0),
    )
    version = 0
    for edit in edits:
        exp, rec = svc.submit_edit(exp.id, edit, version)
        version += 1
        assert rec.dist == v0.dist, edit
        assert rec.changed == [], edit
        assert rec.reprocessed == [], edit
        assert rec.relax_count == 0, edit
        assert rec.has_negative_cycle is False, edit


# ---- 验收 3：调大树边时重处理节点 ⊆ 终点的前驱子树 ----------------------

@pytest.mark.parametrize("seed", range(40))
def test_acceptance_3_reprocessed_within_pred_subtree(seed, svc):
    rng = random.Random(seed)
    n = rng.randrange(4, 9)
    nodes = [f"v{i}" for i in range(n)]
    triples = []
    for i, u in enumerate(nodes):
        for j, v in enumerate(nodes):
            if i != j and rng.random() < 0.28:
                triples.append((u, v, rng.randrange(0, 12)))
    # 保证从 v0 出发可达：追加一条链（再打乱边序模拟任意存储顺序）
    backbone = [(nodes[i], nodes[i + 1], 10 + i) for i in range(n - 1)]
    backbone_keys = {(u, v) for u, v, _ in backbone}
    triples = [t for t in triples if (t[0], t[1]) not in backbone_keys]
    triples = backbone + triples
    rng.shuffle(triples)
    g = make_graph(nodes, triples)
    exp, v0 = svc.create_experiment(g, nodes[0])
    tree_edges = [(v0.pred[v], v) for v in nodes if v0.pred[v] is not None]
    assert tree_edges  # 背骨链保证全部可达，必有树边
    u, v = tree_edges[seed % len(tree_edges)]
    exp, rec = svc.submit_edit(
        exp.id,
        EdgeEdit(EdgeEdit.UPDATE, u, v, float(rng.randrange(30, 90))),
        0,
    )
    subtree = set(_pred_subtree(v, v0.pred))
    assert set(rec.reprocessed) <= subtree
    # 子树以外的节点距离一个都不变
    for node in nodes:
        if node not in subtree:
            assert rec.dist[node] == v0.dist[node]
    # 子树根 v 必然被重新处理（它的距离只会变大或变为不可达）
    assert v in rec.reprocessed


# ---- 验收 4：30 节点逆序单链 --------------------------------------------

def test_acceptance_4_reverse_chain_only_tail_reprocessed(svc):
    n = 30
    nodes = [f"n{i}" for i in range(n)]
    triples = [(f"n{i}", f"n{i + 1}", 1) for i in range(n - 1)]
    # 边按「从链尾到链头」的顺序存放
    g = make_graph(nodes, list(reversed(triples)))
    exp, v0 = svc.create_experiment(g, "n0")
    assert v0.dist["n29"] == 29.0

    exp, v1 = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "n28", "n29", 2.0), 0
    )
    assert v1.reprocessed == ["n29"]
    assert v1.changed == [{"node": "n29", "before": 29.0, "after": 30.0}]
    assert v1.dist["n29"] == 30.0
    assert v1.relax_count <= v1.full_relax_count / 10
    # 全量口径核对：V 个节点、V−1 条边、从链尾顺序时 BF 恰好跑满 V−1 轮 + 检测轮
    assert v1.full_relax_count == (n - 1) * n


# ---- 验收 5：旧版本号被拒绝，实验状态不变 -------------------------------

def test_acceptance_5_stale_version_rejected(svc):
    g = make_graph(["A", "B"], [("A", "B", 1)])
    exp, v0 = svc.create_experiment(g, "A")
    exp, v1 = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 4.0), 0
    )
    assert v1.version == 1

    stale = EdgeEdit(EdgeEdit.UPDATE, "A", "B", 9.0)
    with pytest.raises(VersionConflict) as exc_info:
        svc.submit_edit(exp.id, stale, base_version=0)
    assert exc_info.value.current_version == 1

    # 实验状态原封不动：版本号、距离表、历史长度都不变
    again = svc.get_experiment(exp.id)
    assert again.version == 1
    assert again.latest.dist == v1.dist
    assert len(again.versions) == 2


# ---- 验收 6：制造再打破源点可达负权环 -----------------------------------

def test_acceptance_6_make_then_break_negative_cycle(svc):
    g = make_graph(
        ["A", "B", "C", "D"],
        [("A", "B", 3), ("A", "C", 6), ("B", "C", 2), ("B", "D", 5)],
    )
    exp, v0 = svc.create_experiment(g, "A")
    assert v0.has_negative_cycle is False

    # 新增 C→B（−6），与 B→C（2）构成权 −4 的负环
    exp, v1 = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.ADD, "C", "B", -6.0), 0
    )
    assert v1.has_negative_cycle is True
    assert set(v1.cycle["nodes"]) == {"B", "C"}
    assert v1.cycle["weight"] == -4.0
    assert set(v1.affected) == {"B", "C", "D"}
    for node in v1.affected:
        assert v1.dist[node] is None
    assert v1.dist["A"] == 0.0
    assert v1.mode == "full"
    assert "负权环" in v1.reason

    # 打破负环：C→B 改为 +6（环权变为 8）
    exp, v2 = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "C", "B", 6.0), 1
    )
    assert v2.has_negative_cycle is False
    assert v2.mode == "full", "从负环状态恢复必须标明走全量"
    assert "全量" in v2.reason
    reference = full_bellman_ford(v2.graph, "A")
    assert v2.dist == reference.dist
    assert v2.dist == {"A": 0.0, "B": 3.0, "C": 5.0, "D": 8.0}
    assert_predecessors_legal(v2.graph, "A", v2.dist, v2.pred)

    # 再做一次普通的调小编辑，恢复后应重新走增量
    exp, v3 = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "C", 2.0), 2
    )
    assert v3.has_negative_cycle is False
    assert v3.mode == "incremental"
    assert v3.dist == full_bellman_ford(v3.graph, "A").dist


def test_acceptance_6_break_cycle_by_deleting_edge(svc):
    """用删除环上一条边的方式打破负环，也必须全量恢复为有限值。"""
    g = make_graph(
        ["A", "B", "C", "D"],
        [("A", "B", 3), ("A", "C", 6), ("B", "C", 2), ("B", "D", 5)],
    )
    exp, _ = svc.create_experiment(g, "A")
    exp, made = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.ADD, "C", "B", -6.0), 0
    )
    assert made.has_negative_cycle
    exp, broken = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.DELETE, "C", "B"), 1
    )
    assert broken.mode == "full"
    assert broken.has_negative_cycle is False
    ref = full_bellman_ford(broken.graph, "A")
    assert broken.dist == ref.dist
    assert broken.dist == {"A": 0.0, "B": 3.0, "C": 5.0, "D": 8.0}


def test_acceptance_6_break_self_loop_then_incremental(svc):
    """源点负权自环被改成非负后恢复，后续编辑重回增量。"""
    g = make_graph(["A", "B"], [("A", "B", 2)])
    exp, _ = svc.create_experiment(g, "A")
    exp, made = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.ADD, "A", "A", -1.0), 0
    )
    assert made.has_negative_cycle and made.cycle["nodes"] == ["A"]
    exp, broken = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "A", 0.0), 1
    )
    assert broken.mode == "full" and not broken.has_negative_cycle
    assert broken.dist == {"A": 0.0, "B": 2.0}
    exp, after = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 7.0), 2
    )
    assert after.mode == "incremental"
    assert after.dist == full_bellman_ford(after.graph, "A").dist


# ---- 验收 7：按版本号取回的结果与当时返回一致 ---------------------------

def test_acceptance_7_history_retrieval_matches(svc):
    g = make_graph(
        ["A", "B", "C"],
        [("A", "B", 4), ("A", "C", 5), ("B", "C", 3)],
    )
    exp, v0 = svc.create_experiment(g, "A")
    snapshots = [svc.serialize_version(exp, v0)]
    for i, edit in enumerate((
        EdgeEdit(EdgeEdit.UPDATE, "A", "B", 1.0),
        EdgeEdit(EdgeEdit.UPDATE, "B", "C", 9.0),
        EdgeEdit(EdgeEdit.ADD, "C", "A", -2.0),
        EdgeEdit(EdgeEdit.UPDATE, "C", "A", 4.0),  # 打破可能出现的环
    )):
        exp, rec = svc.submit_edit(exp.id, edit, i)
        snapshots.append(svc.serialize_version(exp, rec))

    for version, snapshot in enumerate(snapshots):
        _, fetched = svc.get_version(exp.id, version)
        payload = svc.serialize_version(exp, fetched)
        assert payload["version"] == snapshot["version"]
        assert payload["dist"] == snapshot["dist"]
        assert payload["pred"] == snapshot["pred"]
        assert payload["mode"] == snapshot["mode"]
        assert payload["changed"] == snapshot["changed"]
        assert payload["reprocessed"] == snapshot["reprocessed"]
        assert payload["relax_count"] == snapshot["relax_count"]
        assert payload["has_negative_cycle"] == snapshot["has_negative_cycle"]
        # 取回的图也与当时一致
        old_edges = [
            (e["source"], e["target"], e["weight"])
            for e in snapshot["graph"]["edges"]
        ]
        fetched_edges = [
            (e.source, e.target, e.weight) for e in fetched.graph.edges
        ]
        assert fetched_edges == old_edges
