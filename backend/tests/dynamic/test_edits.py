"""编辑校验与纯函数应用的单元测试（非法编辑不得改动图 / 实验状态）。"""

import pytest

from app.dynamic.edits import (
    ADD_EDGE,
    DELETE_EDGE,
    UPDATE_WEIGHT,
    EdgeEdit,
    EditError,
    apply_edit,
    validate_edit,
)
from ..conftest import make_graph


@pytest.fixture
def graph():
    return make_graph(["A", "B", "C"], [("A", "B", 2), ("B", "C", -1)])


def test_update_weight_changes_both_edge_lists(graph):
    new = apply_edit(graph, EdgeEdit(UPDATE_WEIGHT, "A", "B", 7.0))
    assert new.edges[0].weight == 7.0
    assert new.adj["A"][0].weight == 7.0
    # 原对象未被修改
    assert graph.edges[0].weight == 2
    # 其它边不动
    assert new.edges[1].weight == -1


def test_add_edge_appended_to_edges_and_adj(graph):
    new = apply_edit(graph, EdgeEdit(ADD_EDGE, "A", "C", 5.0))
    assert len(new.edges) == 3
    assert [(e.source, e.target) for e in new.adj["A"]] == [("A", "B"), ("A", "C")]
    assert len(graph.edges) == 2  # 原图不变


def test_delete_edge_removes_from_edges_and_adj(graph):
    new = apply_edit(graph, EdgeEdit(DELETE_EDGE, "B", "C"))
    assert [(e.source, e.target) for e in new.edges] == [("A", "B")]
    assert new.adj["B"] == []
    assert graph.adj["B"]  # 原图不变


def test_update_missing_edge_rejected(graph):
    with pytest.raises(EditError, match="不存在"):
        validate_edit(graph, EdgeEdit(UPDATE_WEIGHT, "C", "A", 1.0))


def test_add_existing_edge_rejected(graph):
    with pytest.raises(EditError, match="已经存在"):
        validate_edit(graph, EdgeEdit(ADD_EDGE, "A", "B", 1.0))


def test_delete_missing_edge_rejected(graph):
    with pytest.raises(EditError, match="本来就不存在"):
        validate_edit(graph, EdgeEdit(DELETE_EDGE, "C", "A"))


def test_unknown_node_rejected(graph):
    with pytest.raises(EditError, match="不存在的节点"):
        validate_edit(graph, EdgeEdit(UPDATE_WEIGHT, "A", "Z", 1.0))
    with pytest.raises(EditError, match="不存在的节点"):
        validate_edit(graph, EdgeEdit(ADD_EDGE, "Z", "A", 1.0))


def test_non_finite_weight_rejected(graph):
    with pytest.raises(EditError, match="有限数"):
        EdgeEdit.from_payload(
            {"kind": "add_edge", "source": "A", "target": "C", "weight": float("nan")}
        )


def test_invalid_kind_rejected():
    with pytest.raises(EditError, match="编辑类型非法"):
        EdgeEdit.from_payload({"kind": "explode", "source": "A", "target": "B"})


def test_delete_does_not_need_weight(graph):
    edit = EdgeEdit.from_payload(
        {"kind": "delete_edge", "source": "A", "target": "B"}
    )
    assert edit.weight is None
    new = apply_edit(graph, edit)
    assert len(new.edges) == 1


def test_self_loop_edits_allowed(graph):
    g2 = apply_edit(graph, EdgeEdit(ADD_EDGE, "A", "A", -3.0))
    assert any(e.source == "A" and e.target == "A" for e in g2.edges)
    g3 = apply_edit(g2, EdgeEdit(UPDATE_WEIGHT, "A", "A", 0.0))
    assert g3.edges[-1].weight == 0.0
    g4 = apply_edit(g3, EdgeEdit(DELETE_EDGE, "A", "A"))
    assert not any(e.source == "A" and e.target == "A" for e in g4.edges)
