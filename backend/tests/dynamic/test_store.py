"""实验存储：LRU 淘汰、不存在实验、版本冲突等边界。"""

import pytest

from app.dynamic.edits import EdgeEdit
from app.dynamic.service import DynamicService
from app.dynamic.store import ExperimentNotFound, VersionConflict, VersionNotFound
from ..conftest import make_graph


@pytest.fixture
def one_graph():
    return make_graph(["A", "B"], [("A", "B", 1)])


def test_lru_evicts_least_recently_accessed(one_graph):
    svc = DynamicService(max_experiments=3)
    ids = [svc.create_experiment(one_graph, "A")[0].id for _ in range(3)]
    # 访问最早的那个，把它刷新到最近使用
    svc.get_experiment(ids[0])
    # 再插入第四个：应淘汰「次早」的 ids[1]，而非 ids[0]
    fourth, _ = svc.create_experiment(one_graph, "A")
    assert svc.get_experiment(ids[0]).id == ids[0]
    with pytest.raises(ExperimentNotFound):
        svc.get_experiment(ids[1])
    assert svc.get_experiment(fourth.id)


def test_submitting_edit_refreshes_lru(one_graph):
    svc = DynamicService(max_experiments=2)
    e1, _ = svc.create_experiment(one_graph, "A")
    e2, _ = svc.create_experiment(one_graph, "A")
    # 给 e1 提交编辑 → e1 变为最近访问；插入新实验时应淘汰 e2
    svc.submit_edit(e1.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 4.0), 0)
    e3, _ = svc.create_experiment(one_graph, "A")
    assert svc.get_experiment(e1.id)
    with pytest.raises(ExperimentNotFound):
        svc.get_experiment(e2.id)
    assert svc.get_experiment(e3.id)


def test_missing_experiment_raises_not_found(svc):
    with pytest.raises(ExperimentNotFound):
        svc.get_experiment("deadbeef")
    with pytest.raises(ExperimentNotFound):
        svc.submit_edit(
            "deadbeef", EdgeEdit(EdgeEdit.UPDATE, "A", "B", 1.0), 0
        )


def test_missing_version_raises(svc, one_graph):
    exp, _ = svc.create_experiment(one_graph, "A")
    with pytest.raises(VersionNotFound):
        svc.get_version(exp.id, 5)
    # 负版本
    with pytest.raises(VersionNotFound):
        svc.get_version(exp.id, -1)


def test_invalid_edit_does_not_change_experiment(svc):
    g = make_graph(["A", "B"], [("A", "B", 1)])
    exp, v0 = svc.create_experiment(g, "A")
    with pytest.raises(Exception):
        svc.submit_edit(exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "X", 2.0), 0)
    same = svc.get_experiment(exp.id)
    assert same.version == 0
    assert same.latest is v0
    assert len(same.versions) == 1


def test_two_stale_edits_do_not_overlap(svc, one_graph):
    exp, _ = svc.create_experiment(one_graph, "A")
    svc.submit_edit(exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 3.0), 0)
    # 第二个客户端仍基于版本 0
    with pytest.raises(VersionConflict):
        svc.submit_edit(exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 8.0), 0)
    latest = svc.get_experiment(exp.id).latest
    assert latest.dist["B"] == 3.0  # 后一次编辑没有叠加上去


def test_history_retains_every_version_graph_and_dist(svc, one_graph):
    exp, v0 = svc.create_experiment(one_graph, "A")
    exp, v1 = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.UPDATE, "A", "B", 7.0), 0
    )
    exp, v2 = svc.submit_edit(
        exp.id, EdgeEdit(EdgeEdit.ADD, "B", "A", -1.0), 1
    )
    assert len(exp.versions) == 3
    # 旧版本的图仍是旧图（边数不变）
    _, fetched0 = svc.get_version(exp.id, 0)
    assert len(fetched0.graph.edges) == 1
    assert fetched0.dist["B"] == 1.0
    _, fetched1 = svc.get_version(exp.id, 1)
    assert len(fetched1.graph.edges) == 1
    assert fetched1.graph.edges[0].weight == 7.0
    assert fetched1.dist["B"] == 7.0
    _, fetched2 = svc.get_version(exp.id, 2)
    assert len(fetched2.graph.edges) == 2
