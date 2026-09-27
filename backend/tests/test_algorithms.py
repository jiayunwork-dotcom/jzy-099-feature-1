"""算法正确性主线测试：

1. 无负权时 Dijkstra 与 Bellman–Ford 距离完全一致（含随机图）；
2. 存在源点可达的负权环时必须如实识别，不能返回有限最短距离；
3. 源点到自身为 0、不可达为 ∞、边权调大距离不减小等不变量；
4. Dijkstra 遇负权默认拒绝，放行时必须带警告。
"""

import pytest

from app.bellman_ford import run_bellman_ford
from app.dijkstra import run_dijkstra
from app.graph import GraphError
from app.path import backtrack_path
from .conftest import make_graph, random_nonnegative_graph


# ---- 主线一：非负权图上两算法一致 --------------------------------------

@pytest.mark.parametrize("seed", list(range(30)))
def test_dijkstra_equals_bellman_ford_on_nonnegative_graphs(seed):
    g = random_nonnegative_graph(seed)
    if not g.nodes:
        return
    for source in g.node_ids:
        d = run_dijkstra(g, source)
        bf = run_bellman_ford(g, source)
        assert d["dist"] == bf["dist"], (
            f"seed={seed}, source={source}: "
            f"Dijkstra {d['dist']} != Bellman-Ford {bf['dist']}"
        )


def test_dijkstra_equals_bellman_ford_preset(positive_graph):
    d = run_dijkstra(positive_graph, "A")
    bf = run_bellman_ford(positive_graph, "A")
    assert d["dist"] == bf["dist"]
    assert d["dist"] == {"A": 0.0, "B": 5.0, "C": 3.0,
                         "D": 9.0, "E": 10.0, "F": None}


# ---- 基本不变量 ---------------------------------------------------------

def test_source_distance_is_zero(positive_graph):
    d = run_dijkstra(positive_graph, "C")
    bf = run_bellman_ford(positive_graph, "C")
    assert d["dist"]["C"] == 0.0
    assert bf["dist"]["C"] == 0.0


def test_unreachable_is_infinity(positive_graph):
    d = run_dijkstra(positive_graph, "A")
    bf = run_bellman_ford(positive_graph, "A")
    assert d["dist"]["F"] is None  # null 即 ∞
    assert bf["dist"]["F"] is None
    assert "F" not in d["reachable"]
    assert bf["has_negative_cycle"] is False


@pytest.mark.parametrize("seed", range(15))
def test_increasing_edge_weight_never_decreases_distances(seed):
    """把某条边的权重调大（或删除），任一节点的最短距离都不会减小。"""
    g = random_nonnegative_graph(seed, n=7)
    if not g.edges:
        return
    source = g.node_ids[0]
    base = run_bellman_ford(g, source)["dist"]

    edge = g.edges[seed % len(g.edges)]
    heavier = make_graph(
        g.node_ids,
        [(e.source, e.target,
          e.weight + 5 if (e.source == edge.source and e.target == edge.target)
          else e.weight)
         for e in g.edges],
    )
    after = run_bellman_ford(heavier, source)["dist"]
    for v in g.node_ids:
        if base[v] is not None and after[v] is not None:
            assert after[v] >= base[v]


def test_triangle_inequality_invariant(positive_graph):
    """对所有边 u→v：d[v] ≤ d[u] + w（可达节点上）。"""
    d = run_dijkstra(positive_graph, "A")["dist"]
    for edge in positive_graph.edges:
        if d[edge.source] is None:
            continue
        dv = d[edge.target]
        if dv is None:
            continue  # F 不可达，无法形成约束
        assert dv <= d[edge.source] + edge.weight + 1e-9


# ---- 主线二：负权环必须如实识别 ----------------------------------------

def test_bellman_ford_detects_reachable_cycle(cycle_graph):
    bf = run_bellman_ford(cycle_graph, "A")
    assert bf["has_negative_cycle"] is True
    cycle_nodes = set(bf["cycle"]["nodes"])
    assert cycle_nodes == {"B", "C"}
    # 环上节点及其下游均不得返回有限距离
    assert set(bf["affected"]) == {"B", "C", "D", "E", "F"}
    for v in bf["affected"]:
        assert bf["dist"][v] is None
    # 源点自身仍为 0
    assert bf["dist"]["A"] == 0.0


def test_reported_cycle_edges_form_a_real_negative_cycle(cycle_graph):
    bf = run_bellman_ford(cycle_graph, "A")
    edges = bf["cycle"]["edges"]
    weight = bf["cycle"]["weight"]
    assert len(edges) == 2
    assert weight == -4.0
    # 边首尾相接
    for i, edge in enumerate(edges):
        nxt = edges[(i + 1) % len(edges)]
        assert edge["target"] == nxt["source"]


def test_negative_cycle_marks_trace_step(cycle_graph):
    bf = run_bellman_ford(cycle_graph, "A")
    assert any(step["type"] == "negative_cycle" for step in bf["steps"])


def test_unreachable_negative_cycle_is_not_reported():
    """负权环若从源点不可达，则不应污染结果。"""
    g = make_graph(
        ["A", "B", "C"],
        [("A", "A", 0), ("B", "C", 1), ("C", "B", -3)],
    )
    # 0 权自环不算负权环；真正的环 B-C 与 A 不连通
    bf = run_bellman_ford(g, "A")
    assert bf["has_negative_cycle"] is False
    assert bf["dist"] == {"A": 0.0, "B": None, "C": None}


def test_negative_self_loop_is_detected():
    g = make_graph(["A"], [("A", "A", -1)])
    bf = run_bellman_ford(g, "A")
    assert bf["has_negative_cycle"] is True
    assert bf["cycle"]["nodes"] == ["A"]
    assert bf["dist"]["A"] is None  # 连源点也会被污染（−∞）


@pytest.mark.parametrize("n", [3, 4, 5, 6])
def test_cycle_detection_various_graphs(n):
    """在一条出链上挂一个三角形负权环，各种规模下都应被检测出来。"""
    nodes = [f"v{i}" for i in range(n)]
    edge_triples = [
        (nodes[i], nodes[i + 1], 4)
        for i in range(2, n - 1)  # 环外尾巴：v2→v3→…→v_{n-1}
    ]
    edge_triples.append((nodes[0], nodes[1], 1))
    edge_triples.append((nodes[1], nodes[2], 1))
    edge_triples.append((nodes[2], nodes[0], -8))  # 环总权 -6
    g = make_graph(nodes, edge_triples)
    bf = run_bellman_ford(g, nodes[0])
    assert bf["has_negative_cycle"] is True
    assert bf["cycle"]["weight"] < 0
    assert set(bf["cycle"]["nodes"]) == {nodes[0], nodes[1], nodes[2]}


# ---- Bellman–Ford 在无环负权图上给出正确答案 --------------------------

def test_bellman_ford_handles_negative_edges(negative_graph):
    bf = run_bellman_ford(negative_graph, "A")
    assert bf["has_negative_cycle"] is False
    assert bf["dist"] == {"A": 0.0, "B": 2.0, "C": 5.0,
                          "D": 9.0, "E": 11.0}


def test_dijkstra_wrong_on_negative_graph_but_can_be_compared(negative_graph):
    bf = run_bellman_ford(negative_graph, "A")
    forced = run_dijkstra(negative_graph, "A", allow_negative=True)
    # 放行模式：结果确实与正确答案不符，且必须带警告
    assert forced["warning"] is not None
    assert forced["dist"] != bf["dist"]
    assert forced["dist"]["B"] == 4.0  # Dijkstra 过早确定 B=4


def test_dijkstra_rejects_negative_edges_by_default(negative_graph):
    with pytest.raises(GraphError, match="负权边"):
        run_dijkstra(negative_graph, "A")


def test_missing_source_rejected(positive_graph):
    with pytest.raises(GraphError, match="源点不存在"):
        run_dijkstra(positive_graph, "Z")
    with pytest.raises(GraphError, match="源点不存在"):
        run_bellman_ford(positive_graph, "Z")


# ---- trace 结构 ---------------------------------------------------------

def test_dijkstra_trace_shows_queue_and_settled(positive_graph):
    d = run_dijkstra(positive_graph, "A")
    init = d["steps"][0]
    assert init["type"] == "init" and init["queue"] == [["A", 0.0]]
    settle_steps = [s for s in d["steps"] if s["type"] == "settle"]
    # 每个可达节点恰好被确定一次，且按距离非降序弹出
    settled = [s["current_node"] for s in settle_steps]
    assert settled == ["A", "C", "B", "D", "E"]
    popped_dist = [s["dist"][s["current_node"]] for s in settle_steps]
    assert popped_dist == sorted(popped_dist)
    assert "F" not in settled
    final = d["steps"][-1]
    assert final["type"] == "finished"
    assert set(final["settled"]) == {"A", "B", "C", "D", "E"}


def test_bellman_ford_trace_records_passes_and_edges(negative_graph):
    bf = run_bellman_ford(negative_graph, "A")
    passes = {s["pass"] for s in bf["steps"] if s["type"] == "pass_start"}
    # 第 3 轮结束时已收敛，提前在第 4 轮前停止（最多 V−1 = 4 轮）
    assert passes <= {1, 2, 3, 4}
    assert 1 in passes
    detect = [s for s in bf["steps"] if s["type"] == "detect"]
    assert len(detect) == len(negative_graph.edges)
    assert bf["steps"][-1]["type"] == "finished"


def test_bellman_ford_early_stop_on_long_chain():
    # 预设 longchain：边序不利需要 3 轮；这里直接构造验证轮次信息存在
    g = make_graph(
        ["C", "D", "B", "A"],
        [("C", "D", 2), ("B", "C", 3), ("A", "B", 5)],
    )
    bf = run_bellman_ford(g, "A")
    assert bf["dist"]["D"] == 10.0
    # 第 3 轮才更新 D；第 4 轮（V−1=3，检测轮 n=4）无更新
    d_updates = [s for s in bf["steps"]
                 if s["type"] == "relax" and s["active_edges"]
                 and s["active_edges"][0]["target"] == "D" and s["relaxed"]]
    assert d_updates[-1]["pass"] == 3


# ---- 路径回溯 -----------------------------------------------------------

def test_path_backtracking(positive_graph):
    bf = run_bellman_ford(positive_graph, "A")
    path = backtrack_path(positive_graph, "A", "E",
                          bf["dist"], bf["pred"])
    assert path["exists"]
    assert path["nodes"] == ["A", "C", "B", "D", "E"]
    assert path["distance"] == 10.0
    assert path["total_weight"] == 3 + 2 + 4 + 1


def test_path_to_source_is_empty(positive_graph):
    d = run_dijkstra(positive_graph, "A")
    path = backtrack_path(positive_graph, "A", "A", d["dist"], d["pred"])
    assert path["exists"] and path["nodes"] == ["A"]
    assert path["distance"] == 0.0 and path["total_weight"] is None


def test_path_unreachable_reports_infinity(positive_graph):
    d = run_dijkstra(positive_graph, "A")
    path = backtrack_path(positive_graph, "A", "F", d["dist"], d["pred"])
    assert not path["exists"] and "∞" in path["reason"]


def test_path_through_negative_cycle_does_not_exist(cycle_graph):
    bf = run_bellman_ford(cycle_graph, "A")
    path = backtrack_path(cycle_graph, "A", "E",
                          bf["dist"], bf["pred"], affected=bf["affected"])
    assert not path["exists"]
    assert "负权环" in path["reason"]


def test_path_matches_adjacent_weights(negative_graph):
    bf = run_bellman_ford(negative_graph, "A")
    path = backtrack_path(negative_graph, "A", "E",
                          bf["dist"], bf["pred"])
    assert path["nodes"] == ["A", "C", "B", "D", "E"]
    assert path["total_weight"] == 5 - 3 + 7 + 2


# ---- 一致性：前驱链全部合法 --------------------------------------------

@pytest.mark.parametrize("seed", range(10))
def test_predecessors_form_source_rooted_tree(seed):
    g = random_nonnegative_graph(seed, n=9)
    source = g.node_ids[0]
    for result in (run_dijkstra(g, source), run_bellman_ford(g, source)):
        pred, dist = result["pred"], result["dist"]
        for v in g.node_ids:
            if v == source:
                assert pred[v] is None
            if dist[v] is None:
                continue
            chain, cur = [], v
            while cur is not None:
                assert cur not in chain  # 前驱链无环
                chain.append(cur)
                cur = pred[cur]
            assert chain[-1] == source
