"""增量修复（dynamic repair）的单元测试。

覆盖验收点：

- #2 调大非树边 / 改动不可达区域的边：变化清单与被重新处理集合都为空；
- #3 调大树边：被重新处理的节点全部落在该边终点的树子树内，子树外一个都不出现；
- #4 30 节点单链（边按链尾到链头存放）只重算链尾一个节点，
  且松弛次数不超过全量的十分之一；
- #6 造出源点可达负权环 → 状态/距离正确；再打破 → 标明走全量并恢复；
- 增量结果在大量随机图（含负权、不可达、删/增节点）上与独立的
  Bellman–Ford 参考实现逐节点一致、前驱链合法（验收点 #1 的核心）。
"""

from __future__ import annotations

import random

import pytest

from app.dynamic.edits import Edit, EditError
from app.dynamic.experiment import (
    FULL_FROM_CYCLE_REASON,
)
from app.dynamic.repair import (
    apply_full_recompute,
    apply_incremental_repair,
    full_bellman_ford,
    initial_result,
)
from app.bellman_ford import run_bellman_ford
from app.graph import Graph
from .conftest import make_graph


# ---- 辅助 ---------------------------------------------------------------

def subtree(pred: dict, root: str) -> set[str]:
    children: dict[str, list[str]] = {}
    for node, parent in pred.items():
        if parent is not None:
            children.setdefault(parent, []).append(node)
    seen, stack = set(), [root]
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        stack.extend(children.get(u, []))
    return seen


# ---- 验收点 #2：非树边调大 / 不可达区域改动 → 什么都不发生 -------------

def test_increase_off_tree_edge_changes_nothing():
    # s→a(1), s→b(5), a→b(1)：最短路径树为 s-a-b，边 s→b 不在树上
    g = make_graph(["s", "a", "b"],
                   [("s", "a", 1), ("s", "b", 5), ("a", "b", 1)])
    init = initial_result(g, "s")
    assert init["dist"] == {"s": 0.0, "a": 1.0, "b": 2.0}

    g2 = make_graph(["s", "a", "b"],
                    [("s", "a", 1), ("s", "b", 100), ("a", "b", 1)])
    out = apply_incremental_repair(
        old_graph=g, new_graph=g2, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("set_weight", "s", "b", 100),
    )
    assert out["changed"] == []
    assert out["reprocessed"] == []
    assert out["incremental_relax_count"] == 0
    assert out["dist"] == {"s": 0.0, "a": 1.0, "b": 2.0}
    assert {f["type"] for f in out["steps"]} == {"noop"}


def test_edit_in_unreachable_region_changes_nothing():
    # x→y 与源点 s 完全不连通
    g = make_graph(["s", "x", "y"],
                   [("s", "s", 0), ("x", "y", 3)])
    init = initial_result(g, "s")
    g2 = make_graph(["s", "x", "y"],
                    [("s", "s", 0), ("x", "y", 99)])
    out = apply_incremental_repair(
        old_graph=g, new_graph=g2, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("set_weight", "x", "y", 99),
    )
    assert out["changed"] == []
    assert out["reprocessed"] == []
    assert out["incremental_relax_count"] == 0


def test_delete_off_tree_edge_changes_nothing():
    g = make_graph(["s", "a", "b"],
                   [("s", "a", 1), ("s", "b", 5), ("a", "b", 1)])
    init = initial_result(g, "s")
    g2 = make_graph(["s", "a", "b"],
                    [("s", "a", 1), ("a", "b", 1)])  # 删掉非树边 s→b
    out = apply_incremental_repair(
        old_graph=g, new_graph=g2, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("delete_edge", "s", "b"),
    )
    assert out["changed"] == []
    assert out["reprocessed"] == []
    assert out["dist"]["b"] == 2.0


def test_set_same_weight_is_noop():
    g = make_graph(["s", "a"], [("s", "a", 4)])
    init = initial_result(g, "s")
    out = apply_incremental_repair(
        old_graph=g, new_graph=g, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("set_weight", "s", "a", 4),
    )
    assert out["changed"] == [] and out["reprocessed"] == []
    assert out["incremental_relax_count"] == 0


# ---- 验收点 #3：调大树边，只动子树 --------------------------------------

def test_increase_tree_edge_reprocessed_within_subtree():
    g = make_graph(
        ["s", "a", "b", "c", "d"],
        [
            ("s", "a", 1), ("s", "b", 8),
            ("a", "b", 1), ("b", "c", 1), ("c", "d", 1),
            # 一条绕开树边的备份路径 s→d，证明子树外 s 不会被动
            ("a", "d", 20),
        ],
    )
    init = initial_result(g, "s")
    # 树：s-a-b-c-d；调大 a→b
    g2 = make_graph(
        ["s", "a", "b", "c", "d"],
        [
            ("s", "a", 1), ("s", "b", 8),
            ("a", "b", 6), ("b", "c", 1), ("c", "d", 1),
            ("a", "d", 20),
        ],
    )
    out = apply_incremental_repair(
        old_graph=g, new_graph=g2, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("set_weight", "a", "b", 6),
    )
    tree_sub = subtree(init["pred"], "b")
    assert tree_sub == {"b", "c", "d"}
    assert set(out["reprocessed"]) <= tree_sub
    assert {"s", "a"}.isdisjoint(out["reprocessed"])
    # 子树外距离不变
    assert out["dist"]["s"] == 0.0 and out["dist"]["a"] == 1.0
    # 变化清单只含子树节点
    assert {c["node"] for c in out["changed"]} <= tree_sub
    # 与全量 Bellman–Ford 一致（备份路径 s→b=8 生效）
    ref = full_bellman_ford(g2, "s")["dist"]
    assert out["dist"] == ref


def test_delete_tree_edge_makes_subtree_unreachable_when_no_alternative():
    g = make_graph(
        ["s", "a", "b"],
        [("s", "a", 1), ("a", "b", 1), ("s", "s", 0)],
    )
    init = initial_result(g, "s")
    g2 = make_graph(["s", "a", "b"], [("s", "a", 1), ("s", "s", 0)])
    out = apply_incremental_repair(
        old_graph=g, new_graph=g2, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("delete_edge", "a", "b"),
    )
    assert out["reprocessed"] == ["b"]
    assert out["dist"]["b"] is None
    assert {c["node"] for c in out["changed"]} == {"b"}
    entry = out["changed"][0]
    assert entry["old"] == 2.0 and entry["new"] is None


def test_increase_tree_edge_with_negative_edge():
    # 子树里含负权边，增量修复（子树内 Bellman–Ford 式松弛）仍必须正确
    g = make_graph(
        ["s", "a", "b", "c"],
        [("s", "a", 2), ("a", "b", 1), ("b", "c", 5), ("a", "c", -3)],
    )
    init = initial_result(g, "s")
    # 树里 c 的前驱可能是 a（负权）；选树边 s→a 调大
    g2 = make_graph(
        ["s", "a", "b", "c"],
        [("s", "a", 7), ("a", "b", 1), ("b", "c", 5), ("a", "c", -3)],
    )
    out = apply_incremental_repair(
        old_graph=g, new_graph=g2, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("set_weight", "s", "a", 7),
    )
    ref = full_bellman_ford(g2, "s")
    assert out["dist"] == ref["dist"]
    assert set(out["reprocessed"]) <= subtree(init["pred"], "a")


# ---- 验收点 #4：30 节点单链 ---------------------------------------------

def test_chain_only_tail_reprocessed_and_under_one_tenth():
    n = 30
    nodes = [f"n{i}" for i in range(n)]
    # 边按「从链尾到链头」的顺序存放
    edges = [(f"n{i}", f"n{i + 1}", 1) for i in range(n - 1)][::-1]
    g = make_graph(nodes, edges)
    init = initial_result(g, "n0")
    assert init["dist"]["n29"] == 29.0
    full_count = init["full_relax_count"]

    edges2 = [(u, v, 2 if (u, v) == ("n28", "n29") else w) for u, v, w in edges]
    g2 = make_graph(nodes, edges2)
    out = apply_incremental_repair(
        old_graph=g, new_graph=g2, source="n0",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("set_weight", "n28", "n29", 2),
    )
    assert out["reprocessed"] == ["n29"]
    assert [c["node"] for c in out["changed"]] == ["n29"]
    assert out["changed"][0]["old"] == 29.0
    assert out["changed"][0]["new"] == 30.0
    assert out["incremental_relax_count"] <= full_count / 10
    assert out["incremental_relax_count"] <= 1  # 该子树只有一条边界边被检查


# ---- 调小：改进沿出边扩散 -----------------------------------------------

def test_decrease_propagates_and_stops():
    g = make_graph(
        ["s", "a", "b", "c"],
        [("s", "a", 10), ("a", "b", 10), ("b", "c", 10)],
    )
    init = initial_result(g, "s")
    g2 = make_graph(
        ["s", "a", "b", "c"],
        [("s", "a", 1), ("a", "b", 10), ("b", "c", 10)],
    )
    out = apply_incremental_repair(
        old_graph=g, new_graph=g2, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("set_weight", "s", "a", 1),
    )
    assert {c["node"] for c in out["changed"]} == {"a", "b", "c"}
    assert set(out["reprocessed"]) == {"a", "b", "c"}
    assert out["dist"] == {"s": 0.0, "a": 1.0, "b": 11.0, "c": 21.0}
    # 松弛次数明显少于全量
    assert out["incremental_relax_count"] < out["full_relax_count"]


def test_add_edge_shortcut_spreads_outwards():
    # 新增一条绕远捷径，扩散到可达的下游；孤立的 x 永不出现在 reprocessed
    g = make_graph(
        ["s", "a", "b", "x"],
        [("s", "a", 10), ("a", "b", 10)],
    )
    init = initial_result(g, "s")
    g2 = make_graph(
        ["s", "a", "b", "x"],
        [("s", "a", 10), ("a", "b", 10), ("s", "b", 1)],
    )
    out = apply_incremental_repair(
        old_graph=g, new_graph=g2, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("add_edge", "s", "b", 1),
    )
    assert out["reprocessed"] == ["b"]
    assert out["dist"]["b"] == 1.0
    assert out["dist"]["x"] is None
    assert "x" not in out["reprocessed"]


# ---- 验收点 #6：负权环的造出与打破（修复引擎层面） ----------------------

def test_incremental_detects_new_reachable_negative_cycle():
    g = make_graph(
        ["s", "a", "b"],
        [("s", "a", 1), ("a", "b", 2), ("b", "a", 3)],
    )
    init = initial_result(g, "s")
    assert init["has_negative_cycle"] is False
    # 把 b→a 调成 -5：a-b-a 环权 2-5 = -3
    g2 = make_graph(
        ["s", "a", "b"],
        [("s", "a", 1), ("a", "b", 2), ("b", "a", -5)],
    )
    out = apply_incremental_repair(
        old_graph=g, new_graph=g2, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("set_weight", "b", "a", -5),
    )
    assert out["mode"] == "incremental"
    assert out["has_negative_cycle"] is True
    assert set(out["cycle"]["nodes"]) == {"a", "b"}
    assert out["cycle"]["weight"] < 0
    assert set(out["affected"]) == {"a", "b"}
    assert out["dist"]["s"] == 0.0
    for v in out["affected"]:
        assert out["dist"][v] is None


def test_unreachable_negative_cycle_not_reported_incrementally():
    # 新造出的负权环在源点不可达区域：不应进入含环状态
    g = make_graph(["s", "x", "y"], [("s", "s", 0)])
    init = initial_result(g, "s")
    # 先加 x→y（起点不可达，种子不生效）
    g2 = make_graph(["s", "x", "y"], [("s", "s", 0), ("x", "y", 1)])
    out1 = apply_incremental_repair(
        old_graph=g, new_graph=g2, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("add_edge", "x", "y", 1),
    )
    # 再加 y→x 与 x→y 构成负权环，但整个环从 s 不可达
    g3 = make_graph(
        ["s", "x", "y"],
        [("s", "s", 0), ("x", "y", 1), ("y", "x", -3)],
    )
    out = apply_incremental_repair(
        old_graph=g2, new_graph=g3, source="s",
        old_dist=dict(out1["dist"]), old_pred=dict(out1["pred"]),
        edit=Edit("add_edge", "y", "x", -3),
    )
    assert out["has_negative_cycle"] is False
    assert out["dist"] == {"s": 0.0, "x": None, "y": None}
    assert out["reprocessed"] == []


def test_break_cycle_is_marked_full_and_recovers():
    # 先在环状态上，再打破：全量重算，有限距离恢复，且标明原因
    g = make_graph(
        ["s", "a", "b"],
        [("s", "a", 1), ("a", "b", 2), ("b", "a", -5)],
    )
    init = initial_result(g, "s")
    assert init["has_negative_cycle"] is True
    g2 = make_graph(
        ["s", "a", "b"],
        [("s", "a", 1), ("a", "b", 2), ("b", "a", 5)],
    )
    out = apply_full_recompute(
        new_graph=g2, source="s",
        old_dist=dict(init["dist"]), reason=FULL_FROM_CYCLE_REASON,
    )
    assert out["mode"] == "full"
    assert "全量" in out["reason"]
    assert out["has_negative_cycle"] is False
    assert out["dist"] == {"s": 0.0, "a": 1.0, "b": 3.0}
    assert out["incremental_relax_count"] == out["full_relax_count"]


def test_spfa_reenqueue_when_node_improves_twice():
    # 回归用例：节点已出队后又被一条更优路径改进时必须重新入队，
    # 否则其下游会停在偏大的旧值（含负权边的传播顺序问题）。
    # 结构（边序刻意不利）：
    #   s→a(0), s→b(100), a→c(0), b→c(-50), c→t(0)
    # 触发方式：先让 b→c 很重，再把它调小；同时 s→b 调小，使 c、t
    # 的最优值在 c 已被处理之后才出现，必须重新入队才能传到 t。
    nodes = ["s", "a", "b", "c", "t"]
    edges = [("s", "a", 0), ("s", "b", 100), ("a", "c", 0),
             ("b", "c", 100), ("c", "t", 0)]
    g = make_graph(nodes, edges)
    init = initial_result(g, "s")
    # 新增 s→t 之外，先把 s→b 调小，b 改进后 b→c（仍很重）不足以更新 c
    g1 = make_graph(nodes, [
        ("s", "a", 0), ("s", "b", 10), ("a", "c", 0),
        ("b", "c", 100), ("c", "t", 0),
    ])
    o1 = apply_incremental_repair(
        old_graph=g, new_graph=g1, source="s",
        old_dist=dict(init["dist"]), old_pred=dict(init["pred"]),
        edit=Edit("set_weight", "s", "b", 10),
    )
    assert o1["dist"] == full_bellman_ford(g1, "s")["dist"]
    # 再把 b→c 调小：c 被 a→c 先以 0 处理，b→c=10-50=-40 更优，
    # c 必须重新入队，t 才能由 0 更新为 -40。
    g2 = make_graph(nodes, [
        ("s", "a", 0), ("s", "b", 10), ("a", "c", 0),
        ("b", "c", -50), ("c", "t", 0),
    ])
    o2 = apply_incremental_repair(
        old_graph=g1, new_graph=g2, source="s",
        old_dist=dict(o1["dist"]), old_pred=dict(o1["pred"]),
        edit=Edit("set_weight", "b", "c", -50),
    )
    ref = full_bellman_ford(g2, "s")
    assert o2["dist"] == ref["dist"]
    assert o2["dist"]["t"] == -40.0
    assert "t" in o2["reprocessed"]


# ---- 全量基准与教学版 Bellman–Ford 完全一致 ----------------------------

@pytest.mark.parametrize("seed", range(20))
def test_fullrun_matches_teaching_bellman_ford(seed):
    rng = random.Random(seed)
    n = rng.randrange(2, 9)
    nodes = [f"v{i}" for i in range(n)]
    triples = [
        (u, v, rng.randrange(-6, 10))
        for u in nodes for v in nodes
        if u != v and rng.random() < 0.3
    ]
    g = make_graph(nodes, triples)
    source = nodes[0]
    taught = run_bellman_ford(g, source)
    full = full_bellman_ford(g, source)
    assert full["dist"] == taught["dist"]
    assert full["pred"] == taught["pred"]
    assert full["has_negative_cycle"] == taught["has_negative_cycle"]
    assert full["affected"] == taught["affected"]


# ---- 编辑的语义校验 -----------------------------------------------------

def test_edit_validation_rejects_bad_inputs():
    g = make_graph(["s", "a"], [("s", "a", 1)])
    with pytest.raises(EditError):
        Edit("add_edge", "s", "zz", 1).validate(g, source="s")
    with pytest.raises(EditError):
        Edit("add_edge", "s", "a", 1).validate(g, source="s")
    with pytest.raises(EditError):
        Edit("delete_edge", "a", "s").validate(g, source="s")
    with pytest.raises(EditError):
        Edit("set_weight", "s", "a", 1).apply(
            make_graph(["s"], []), source="s")
    with pytest.raises(EditError):
        Edit("delete_node", node_id="s").validate(g, source="s")


# ---- 验收点 #1 的引擎版随机压测 -----------------------------------------

def _reference_bellman_ford(graph: Graph, source: str):
    """独立参考实现：标准 N 轮松弛 + 额外轮次标记 −∞ 并向下游扩散。"""
    ids = graph.node_ids
    n = len(ids)
    d = {v: None for v in ids}
    d[source] = 0.0
    for _ in range(n):
        nd = dict(d)
        for e in graph.edges:
            if d[e.source] is None:
                continue
            cand = d[e.source] + e.weight
            if nd[e.target] is None or cand < nd[e.target]:
                nd[e.target] = cand
        d = nd
    polluted: set[str] = set()
    for i in range(2 * n + 1):
        nd = dict(d)
        for e in graph.edges:
            if d[e.source] is None:
                continue
            cand = d[e.source] + e.weight
            if nd[e.target] is None or cand < nd[e.target] - 1e-9:
                nd[e.target] = cand
                if i >= 1:
                    polluted.add(e.target)
        d = nd
    reach = graph.reachable_from(source)
    flood = set(polluted)
    while True:
        added = {e.target for e in graph.edges
                 if e.source in flood and e.target not in flood}
        if not added:
            break
        flood |= added
    has_cycle = bool(flood)
    for v in flood:
        d[v] = None
    affected = flood & reach
    return d, has_cycle, affected


def _random_graph(rng: random.Random, n: int) -> Graph:
    nodes = [f"v{i}" for i in range(n)]
    triples = [
        (u, v, rng.randrange(-6, 12))
        for u in nodes for v in nodes
        if u != v and rng.random() < 0.28
    ]
    return make_graph(nodes, triples)


def _random_edit(rng: random.Random, g: Graph, source: str):
    ids = g.node_ids
    for _ in range(30):
        kind = rng.choice(
            ["set_weight", "set_weight", "add_edge", "delete_edge",
             "add_node", "delete_node"]
        )
        if kind == "set_weight" and g.edges:
            e = rng.choice(g.edges)
            return Edit("set_weight", e.source, e.target, rng.randrange(-6, 12))
        if kind == "add_edge":
            u, v = rng.choice(ids), rng.choice(ids)
            if not any(e.source == u and e.target == v for e in g.edges):
                return Edit("add_edge", u, v, rng.randrange(-6, 12))
        if kind == "delete_edge" and g.edges:
            e = rng.choice(g.edges)
            return Edit("delete_edge", e.source, e.target)
        if kind == "add_node":
            nid = f"z{rng.randrange(0, 10 ** 7)}"
            if nid not in g.nodes:
                return Edit("add_node", node_id=nid)
        if kind == "delete_node":
            cand = [i for i in ids if i != source]
            if cand:
                return Edit("delete_node", node_id=rng.choice(cand))
    return None


@pytest.mark.parametrize("seed,graph_index,edits", [
    (1001, 0, 220), (1002, 1, 220), (1003, 2, 220),
])
def test_random_edits_match_reference(seed, graph_index, edits):
    rng = random.Random(seed * 31 + graph_index)
    g = _random_graph(rng, rng.choice([6, 9, 12]))
    source = g.node_ids[0]
    init = initial_result(g, source)

    ref_d, ref_cycle, ref_aff = _reference_bellman_ford(g, source)
    assert init["dist"] == ref_d
    assert init["has_negative_cycle"] == ref_cycle

    dist = dict(init["dist"])
    pred = dict(init["pred"])
    has_cycle = init["has_negative_cycle"]
    applied = 0
    for _ in range(edits):
        ed = _random_edit(rng, g, source)
        if ed is None:
            break
        new_graph = ed.apply(g, source=source)
        if has_cycle:
            out = apply_full_recompute(
                new_graph=new_graph, source=source,
                old_dist=dict(dist), reason=FULL_FROM_CYCLE_REASON,
            )
        else:
            out = apply_incremental_repair(
                old_graph=g, new_graph=new_graph, source=source,
                old_dist=dict(dist), old_pred=dict(pred), edit=ed,
            )

        ref_d, ref_cycle, ref_aff = _reference_bellman_ford(new_graph, source)
        assert out["dist"] == ref_d, (ed.to_payload(), out["dist"], ref_d)
        assert out["has_negative_cycle"] == ref_cycle
        if ref_cycle:
            assert set(out["affected"]) == ref_aff
        else:
            # 前驱链合法：每个可达节点都能沿前驱无环地回到源点，距离与边权吻合
            for v in new_graph.node_ids:
                if v == source:
                    assert out["dist"][v] == 0.0
                    continue
                if out["dist"][v] is None:
                    continue
                p = out["pred"][v]
                assert p is not None
                w = next(
                    e.weight for e in new_graph.edges
                    if e.source == p and e.target == v
                )
                assert abs(out["dist"][v] - (out["dist"][p] + w)) < 1e-9
                chain, cur = [v], v
                while cur != source:
                    cur = out["pred"][cur]
                    assert cur is not None and cur not in chain
                    chain.append(cur)

        dist, pred = dict(out["dist"]), dict(out["pred"])
        has_cycle = out["has_negative_cycle"]
        g = new_graph
        applied += 1
    assert applied >= 200
