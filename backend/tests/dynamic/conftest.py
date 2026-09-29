"""动态实验层测试的公共夹具与随机图 / 随机编辑生成器。"""

import random

import pytest

from app.graph import Graph
from app.dynamic.edits import EdgeEdit
from app.dynamic.routes import service as http_service
from app.dynamic.service import DynamicService


NEG_WEIGHTS = (-9, -6, -3, -1, 0, 1, 2, 4, 8, 15)


def make_graph(nodes, edges) -> Graph:
    return Graph.from_payload({
        "nodes": [
            {"id": node, "x": 100.0 * (i + 1), "y": 100.0 * (i + 1)}
            for i, node in enumerate(nodes)
        ],
        "edges": [
            {"source": u, "target": v, "weight": w} for u, v, w in edges
        ],
    })


def random_graph(rng: random.Random, n: int, *, edge_prob: float = 0.2,
                 weights=NEG_WEIGHTS) -> Graph:
    """随机有向图（含负权边，允许自环、允许不可达节点）。"""
    nodes = [f"v{i}" for i in range(n)]
    edges = []
    for u in nodes:
        for v in nodes:
            if u != v and rng.random() < edge_prob:
                edges.append((u, v, rng.choice(weights)))
    # 小概率加自环（可能是负权自环）
    for u in nodes:
        if rng.random() < 0.05:
            edges.append((u, u, rng.choice(weights)))
    return make_graph(nodes, edges)


def random_edit(rng: random.Random, graph: Graph) -> EdgeEdit | None:
    """在当前图上随机生成一次合法编辑（调权 / 加边 / 删边）。"""
    node_ids = graph.node_ids
    present = [(e.source, e.target) for e in graph.edges]
    pairs = [(u, v) for u in node_ids for v in node_ids if u != v]
    absent = [p for p in pairs if p not in set(present)]
    roll = rng.random()
    if present and roll < 0.5:
        u, v = rng.choice(present)
        return EdgeEdit(EdgeEdit.UPDATE, u, v, float(rng.choice(NEG_WEIGHTS)))
    if present and roll < 0.72:
        u, v = rng.choice(present)
        return EdgeEdit(EdgeEdit.DELETE, u, v)
    if absent:
        u, v = rng.choice(absent)
        return EdgeEdit(EdgeEdit.ADD, u, v, float(rng.choice(NEG_WEIGHTS)))
    return None


def apply_edit_locally(edges: set[tuple[str, str]], edit: EdgeEdit) -> None:
    """同步测试侧维护的边集合（用于下一次随机编辑）。"""
    if edit.kind == EdgeEdit.DELETE:
        edges.discard((edit.source, edit.target))
    elif edit.kind == EdgeEdit.ADD:
        edges.add((edit.source, edit.target))


def assert_predecessors_legal(graph: Graph, source: str, dist, pred) -> None:
    """距离有限的节点，前驱链必须无环且回到源点；前驱边必须真实存在。"""
    edge_set = {(e.source, e.target) for e in graph.edges}
    for v in graph.node_ids:
        if dist[v] is None:
            continue
        if v == source:
            assert pred[v] is None
            continue
        chain, cur = [], v
        while cur is not None:
            assert cur not in chain, f"前驱链有环：{chain}"
            chain.append(cur)
            p = pred[cur]
            if p is not None:
                assert (p, cur) in edge_set, f"前驱边 {p}→{cur} 不存在"
            cur = p
        assert chain[-1] == source, f"{v} 的前驱链终止于 {chain[-1]} 而非源点"


@pytest.fixture
def svc() -> DynamicService:
    """每个测试一个独立的服务实例，实验互不干扰。"""
    return DynamicService(max_experiments=10)


@pytest.fixture(autouse=True)
def _clear_http_service():
    """HTTP 层服务是模块级单例；每个测试前后清空，保证可重复。"""
    http_service.store.clear()
    yield
    http_service.store.clear()
