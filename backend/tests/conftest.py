"""pytest 公共夹具与构造图的辅助函数。"""

import random

import pytest

from app.graph import Graph


def make_graph(nodes, edges) -> Graph:
    """nodes: id 列表；edges: (u, v, w) 三元组列表。坐标自动布点。"""
    payload = {
        "nodes": [
            {"id": node, "x": 100.0 * (i + 1), "y": 100.0 * (i + 1)}
            for i, node in enumerate(nodes)
        ],
        "edges": [
            {"source": u, "target": v, "weight": w} for u, v, w in edges
        ],
    }
    return Graph.from_payload(payload)


def random_nonnegative_graph(seed: int, *, n: int = 8,
                             edge_prob: float = 0.3,
                             max_weight: int = 12) -> Graph:
    """生成随机非负权有向图（无重复边、无负权）。"""
    rng = random.Random(seed)
    nodes = [f"v{i}" for i in range(n)]
    edges = []
    for u in nodes:
        for v in nodes:
            if u != v and rng.random() < edge_prob:
                edges.append((u, v, rng.randrange(0, max_weight)))
    return make_graph(nodes, edges)


@pytest.fixture
def positive_graph() -> Graph:
    # 对应预设 positive
    return make_graph(
        ["A", "B", "C", "D", "E", "F"],
        [
            ("A", "B", 7),
            ("A", "C", 3),
            ("C", "B", 2),
            ("B", "D", 4),
            ("C", "D", 9),
            ("B", "E", 15),
            ("C", "E", 20),
            ("D", "E", 1),
        ],
    )


@pytest.fixture
def negative_graph() -> Graph:
    # 对应预设 negative：Dijkstra 会算错
    return make_graph(
        ["A", "B", "C", "D", "E"],
        [
            ("A", "B", 4),
            ("A", "C", 5),
            ("B", "D", 7),
            ("C", "B", -3),
            ("C", "D", 5),
            ("D", "E", 2),
            ("A", "E", 15),
        ],
    )


@pytest.fixture
def cycle_graph() -> Graph:
    # 对应预设 cycle：B→C→B 为权 -4 的负权环
    return make_graph(
        ["A", "B", "C", "D", "E", "F"],
        [
            ("A", "B", 3),
            ("A", "C", 6),
            ("B", "C", 2),
            ("C", "B", -6),
            ("B", "D", 5),
            ("D", "E", 2),
            ("D", "F", 7),
            ("E", "F", 1),
        ],
    )
