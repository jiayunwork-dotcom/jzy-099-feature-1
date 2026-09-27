"""额外的不变量测试：边权调大距离不减小、快照一致性等。"""

import pytest

from app.bellman_ford import run_bellman_ford
from app.dijkstra import run_dijkstra
from .conftest import make_graph


@pytest.mark.parametrize("seed", list(range(20)))
def test_monotonicity_heavier_weights_never_shorten_paths(seed):
    """把每条边都调大 3，所有可达节点的最短距离只增不减。"""
    nodes = ["s", "a", "b", "c", "d", "t"]
    edges = [
        ("s", "a", 2), ("s", "b", 5), ("a", "b", 1),
        ("a", "c", 4), ("b", "c", 2), ("b", "d", 6),
        ("c", "t", 3), ("d", "t", 1), ("a", "d", 7),
    ]
    g = make_graph(
        nodes,
        [(u, v, (w * 7 + seed * 3) % 11) for (u, v, w) in edges],
    )
    base = run_bellman_ford(g, "s")["dist"]
    g_heavy = make_graph(
        nodes,
        [(e.source, e.target, e.weight + 3) for e in g.edges],
    )
    after = run_bellman_ford(g_heavy, "s")["dist"]
    for v in nodes:
        if base[v] is None:
            continue
        assert after[v] is not None and after[v] >= base[v]


def test_dijkstra_matches_bellman_ford_after_negative_edge_removed():
    """把负权边改成非负后，两种算法在同一张图上重新一致。"""
    g = make_graph(
        ["A", "B", "C", "D"],
        [("A", "B", 4), ("A", "C", 5), ("C", "B", -3),
         ("B", "D", 7), ("C", "D", 5)],
    )
    g_fixed = make_graph(
        ["A", "B", "C", "D"],
        [("A", "B", 4), ("A", "C", 5), ("C", "B", 3),
         ("B", "D", 7), ("C", "D", 5)],
    )
    assert run_dijkstra(g_fixed, "A")["dist"] == run_bellman_ford(g_fixed, "A")["dist"]
    # 改边权可能让某些距离变大
    bf_before = run_bellman_ford(g, "A")["dist"]
    bf_after = run_bellman_ford(g_fixed, "A")["dist"]
    assert bf_after["B"] > bf_before["B"]


def test_distance_to_self_always_zero_even_with_self_loop():
    g = make_graph(["A", "B"], [("A", "A", 5), ("A", "B", 2)])
    for algo in (run_dijkstra(g, "A"), run_bellman_ford(g, "A")):
        assert algo["dist"]["A"] == 0.0


def test_trace_steps_have_consistent_snapshots():
    g = make_graph(
        ["A", "B", "C", "D", "E", "F"],
        [
            ("A", "B", 7), ("A", "C", 3), ("C", "B", 2),
            ("B", "D", 4), ("C", "D", 9), ("B", "E", 15),
            ("C", "E", 20), ("D", "E", 1),
        ],
    )
    d = run_dijkstra(g, "A")
    bf = run_bellman_ford(g, "A")
    for res in (d, bf):
        # 每一步都带全部节点的距离快照
        for step in res["steps"]:
            assert set(step["dist"]) == set(g.node_ids)
            assert set(step["pred"]) == set(g.node_ids)
            # 距离表中不能出现 NaN
            assert all(v is None or v == v for v in step["dist"].values())
        # 最终步与结果一致
        final = res["steps"][-1]
        assert final["dist"] == res["dist"]
