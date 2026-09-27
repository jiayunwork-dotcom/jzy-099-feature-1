"""图模型与输入校验测试。"""

import pytest

from app.graph import Graph, GraphError
from .conftest import make_graph


def test_basic_graph():
    g = make_graph(["A", "B"], [("A", "B", 2.5)])
    assert g.node_ids == ["A", "B"]
    assert [(e.source, e.target, e.weight) for e in g.edges] == [("A", "B", 2.5)]
    assert g.reachable_from("A") == {"A", "B"}
    assert g.reachable_from("B") == {"B"}


def test_self_loop_is_allowed():
    g = make_graph(["A"], [("A", "A", 1)])
    assert len(g.edges) == 1


def test_negative_weight_is_allowed_at_graph_level():
    g = make_graph(["A", "B"], [("A", "B", -9)])
    assert g.edges[0].weight == -9


def test_missing_source_endpoint_rejected():
    with pytest.raises(GraphError, match="不存在的起点"):
        make_graph(["A"], [("X", "A", 1)])


def test_missing_target_endpoint_rejected():
    with pytest.raises(GraphError, match="不存在的终点"):
        make_graph(["A"], [("A", "X", 1)])


def test_duplicate_edge_rejected():
    with pytest.raises(GraphError, match="重复边"):
        make_graph(["A", "B"], [("A", "B", 1), ("A", "B", 2)])


def test_duplicate_node_rejected():
    with pytest.raises(GraphError, match="重复"):
        Graph.from_payload({"nodes": [{"id": "A"}, {"id": "A"}], "edges": []})


def test_non_finite_weight_rejected():
    with pytest.raises(GraphError, match="有限数"):
        Graph.from_payload({
            "nodes": [{"id": "A"}, {"id": "B"}],
            "edges": [{"source": "A", "target": "B", "weight": float("inf")}],
        })
