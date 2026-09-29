"""动态实验的 HTTP 接口与实验/版本存储测试。

覆盖：

- 开实验返回编号、版本 0、完整初始结果；
- 每次编辑版本号 +1，返回变化清单 / 被重新处理节点 / 修复帧 / 两组松弛计数；
- 验收点 #5：版本号落后 → 409，实验版本与距离表不变；
- 验收点 #6：造出源点可达负权环 → 含环状态；再打破 → 标明全量并恢复；
- 验收点 #7：按版本号取回的历史结果与当时编辑返回一致；
- 非法编辑（节点不存在 / 删不存在的边 / 加已存在的边）→ 400 且状态不变；
- LRU：超出容量淘汰最久未访问实验；被淘汰 / 不存在 → 404「实验不存在」。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.dynamic import experiment as experiment_module
from app.main import app

client = TestClient(app)


GRAPH = {
    "nodes": [{"id": "s"}, {"id": "a"}, {"id": "b"}, {"id": "c"}],
    "edges": [
        {"source": "s", "target": "a", "weight": 1},
        {"source": "a", "target": "b", "weight": 1},
        {"source": "b", "target": "c", "weight": 1},
    ],
}


@pytest.fixture(autouse=True)
def reset_store():
    """每个测试前后清空进程级实验表，避免相互影响。"""
    experiment_module.store._experiments.clear()
    yield
    experiment_module.store._experiments.clear()


def _create(graph=None, source="s"):
    resp = client.post(
        "/api/experiments",
        json={"graph": graph or GRAPH, "source": source},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _edit(eid, payload, expected=200):
    resp = client.post(f"/api/experiments/{eid}/edits", json=payload)
    assert resp.status_code == expected, resp.text
    return resp.json()


# ---- 开实验 / 初始结果 --------------------------------------------------

def test_create_experiment_returns_id_version_zero_and_full_result():
    data = _create()
    assert len(data["experiment_id"]) >= 8
    assert data["version"] == 0
    r = data["result"]
    assert r["version"] == 0
    assert r["mode"] == "full"
    assert r["dist"] == {"s": 0.0, "a": 1.0, "b": 2.0, "c": 3.0}
    assert r["pred"] == {"s": None, "a": "s", "b": "a", "c": "b"}
    assert r["has_negative_cycle"] is False
    assert r["incremental_relax_count"] == r["full_relax_count"]
    assert r["changed"] == []
    assert r["steps"], "初始结果必须带可播放的全量演示帧"
    assert all(step["phase"] == "full" for step in r["steps"])


def test_create_experiment_validates_graph():
    resp = client.post(
        "/api/experiments",
        json={"graph": {"nodes": [], "edges": []}, "source": "s"},
    )
    assert resp.status_code == 400
    resp = client.post(
        "/api/experiments",
        json={"graph": GRAPH, "source": "zz"},
    )
    assert resp.status_code == 400 and "源点不存在" in resp.json()["detail"]


# ---- 编辑与版本号 -------------------------------------------------------

def test_edits_increment_version_and_return_shape():
    eid = _create()["experiment_id"]
    # 调小树边 s→a：1 → 5 是调大；这里改测调小（5 不存在），故用新增捷径
    # 先把 s→a 调大走「作废子树」流程
    j = _edit(eid, {
        "kind": "set_weight", "base_version": 0,
        "source": "s", "target": "a", "weight": 5,
    })
    assert j["version"] == 1
    assert j["mode"] == "incremental"
    assert j["reason"] is None
    assert {c["node"] for c in j["changed"]} == {"a", "b", "c"}
    assert set(j["reprocessed"]) == {"a", "b", "c"}
    assert j["incremental_relax_count"] <= j["full_relax_count"]
    assert j["steps"], "修复必须带逐步帧"
    types_ = {f["type"] for f in j["steps"]}
    assert {"invalidate_plan", "invalidate", "reprocess"} <= types_
    assert j["edit"] == {
        "kind": "set_weight", "source": "s", "target": "a", "weight": 5.0,
    }
    # 每帧都有完整距离快照与「作废 / 重新处理」集合，供前端着色
    for frame in j["steps"]:
        assert set(frame["dist"]) == {"s", "a", "b", "c"}
        assert "reprocessed" in frame and "invalidated" in frame
        assert set(frame["invalidated"]) <= {"a", "b", "c"}


def test_incremental_vs_full_counts_shown_side_by_side():
    eid = _create()["experiment_id"]
    # 调大非树边：增量 0 次；同图全量要若干轮，两数并排
    g = {
        "nodes": [{"id": "s"}, {"id": "a"}, {"id": "b"}],
        "edges": [
            {"source": "s", "target": "a", "weight": 1},
            {"source": "s", "target": "b", "weight": 5},
            {"source": "a", "target": "b", "weight": 1},
        ],
    }
    exp = _create(g, source="s")
    eid = exp["experiment_id"]
    j = _edit(eid, {
        "kind": "set_weight", "base_version": 0,
        "source": "s", "target": "b", "weight": 50,
    })
    assert j["incremental_relax_count"] == 0
    assert j["full_relax_count"] > 0


# ---- 验收点 #5：版本落后拒绝 -------------------------------------------

def test_stale_version_rejected_without_state_change():
    eid = _create()["experiment_id"]
    _edit(eid, {
        "kind": "set_weight", "base_version": 0,
        "source": "s", "target": "a", "weight": 5,
    })
    # 仍基于版本 0 提交 → 409
    resp = client.post(f"/api/experiments/{eid}/edits", json={
        "kind": "set_weight", "base_version": 0,
        "source": "a", "target": "b", "weight": 9,
    })
    assert resp.status_code == 409
    assert "当前版本为 1" in resp.json()["detail"]
    # 实验仍停在版本 1，距离表是第一次编辑后的结果
    summary = client.get(f"/api/experiments/{eid}").json()
    assert summary["current_version"] == 1
    v1 = client.get(f"/api/experiments/{eid}/versions/1").json()
    assert v1["dist"]["a"] == 5.0
    # 被拒绝的那次改动没有叠加上去
    assert v1["dist"]["b"] == 6.0


# ---- 非法编辑 → 400 且状态不变 -----------------------------------------

def test_bad_edits_are_rejected_and_state_unchanged():
    eid = _create()["experiment_id"]

    # 引用不存在的节点
    r = client.post(f"/api/experiments/{eid}/edits", json={
        "kind": "add_edge", "base_version": 0,
        "source": "s", "target": "zz", "weight": 1,
    })
    assert r.status_code == 400 and "不存在" in r.json()["detail"]

    # 删除不存在的边
    r = client.post(f"/api/experiments/{eid}/edits", json={
        "kind": "delete_edge", "base_version": 0,
        "source": "s", "target": "c",
    })
    assert r.status_code == 400 and "不存在" in r.json()["detail"]

    # 新增已存在的边
    r = client.post(f"/api/experiments/{eid}/edits", json={
        "kind": "add_edge", "base_version": 0,
        "source": "s", "target": "a", "weight": 2,
    })
    assert r.status_code == 400 and "已存在" in r.json()["detail"]

    # 删除源点
    r = client.post(f"/api/experiments/{eid}/edits", json={
        "kind": "delete_node", "base_version": 0, "node_id": "s",
    })
    assert r.status_code == 400 and "源点" in r.json()["detail"]

    # 权重不是有限数（NaN 通过 float 强转但被编辑层拒绝，与 /api/run 一致 → 400）
    r = client.post(f"/api/experiments/{eid}/edits", json={
        "kind": "set_weight", "base_version": 0,
        "source": "s", "target": "a", "weight": "nan",
    })
    assert r.status_code == 400 and "有限数" in r.json()["detail"]

    # 实验状态完全没变
    summary = client.get(f"/api/experiments/{eid}").json()
    assert summary["current_version"] == 0
    v0 = client.get(f"/api/experiments/{eid}/versions/0").json()
    assert v0["dist"] == {"s": 0.0, "a": 1.0, "b": 2.0, "c": 3.0}


# ---- 加 / 删边与节点 ----------------------------------------------------

def test_add_and_delete_edge_edits():
    eid = _create()["experiment_id"]
    j = _edit(eid, {
        "kind": "add_edge", "base_version": 0,
        "source": "s", "target": "c", "weight": 1,
    })
    assert j["version"] == 1
    assert j["dist"]["c"] == 1.0
    assert any(
        e["source"] == "s" and e["target"] == "c"
        for e in j["graph"]["edges"]
    )

    j2 = _edit(eid, {
        "kind": "delete_edge", "base_version": 1,
        "source": "s", "target": "c",
    })
    assert j2["version"] == 2
    assert not any(
        e["source"] == "s" and e["target"] == "c"
        for e in j2["graph"]["edges"]
    )


def test_add_and_delete_node_edits():
    eid = _create()["experiment_id"]
    j = _edit(eid, {
        "kind": "add_node", "base_version": 0,
        "node_id": "z", "x": 12, "y": 34,
    })
    assert j["version"] == 1
    assert any(n["id"] == "z" for n in j["graph"]["nodes"])
    assert j["dist"]["z"] is None  # 新节点不可达
    assert j["changed"] == []

    # 删掉树中间节点 a：b、c 应当变得不可达
    j2 = _edit(eid, {"kind": "delete_node", "base_version": 1, "node_id": "a"})
    assert j2["version"] == 2
    assert "a" not in j2["dist"]
    assert j2["dist"]["b"] is None and j2["dist"]["c"] is None
    assert j2["changed"] and all(
        entry["new"] is None for entry in j2["changed"]
    )


# ---- 验收点 #6（HTTP 全链路）：造环 → 打破 ------------------------------

def test_negative_cycle_create_and_break_over_http():
    graph = {
        "nodes": [{"id": "s"}, {"id": "a"}, {"id": "b"}, {"id": "t"}],
        "edges": [
            {"source": "s", "target": "a", "weight": 1},
            {"source": "a", "target": "b", "weight": 2},
            {"source": "b", "target": "a", "weight": 3},
            {"source": "b", "target": "t", "weight": 4},
        ],
    }
    eid = _create(graph, source="s")["experiment_id"]

    # 造出负权环：b→a 调为 -5（a-b-a 环权 -3）
    j = _edit(eid, {
        "kind": "set_weight", "base_version": 0,
        "source": "b", "target": "a", "weight": -5,
    })
    assert j["version"] == 1
    assert j["has_negative_cycle"] is True
    assert set(j["cycle"]["nodes"]) == {"a", "b"}
    assert j["cycle"]["weight"] < 0
    assert set(j["affected"]) == {"a", "b", "t"}
    for v in j["affected"]:
        assert j["dist"][v] is None
    assert j["dist"]["s"] == 0.0
    assert any(frame["type"] == "negative_cycle" for frame in j["steps"])

    # 实验摘要也应反映含环状态
    summary = client.get(f"/api/experiments/{eid}").json()
    assert summary["has_negative_cycle"] is True

    # 打破环：把 b→a 调回正权 → 必须走全量并标明
    j2 = _edit(eid, {
        "kind": "set_weight", "base_version": 1,
        "source": "b", "target": "a", "weight": 5,
    })
    assert j2["version"] == 2
    assert j2["mode"] == "full"
    assert "全量" in (j2["reason"] or "")
    assert j2["has_negative_cycle"] is False
    assert j2["dist"] == {"s": 0.0, "a": 1.0, "b": 3.0, "t": 7.0}
    assert j2["affected"] == []
    assert all(frame["phase"] == "full" for frame in j2["steps"])


# ---- 验收点 #7：历史版本取回与当时一致 ----------------------------------

def test_historical_versions_match_responses_at_time():
    eid = _create()["experiment_id"]
    r1 = _edit(eid, {
        "kind": "set_weight", "base_version": 0,
        "source": "s", "target": "a", "weight": 5,
    })
    r2 = _edit(eid, {
        "kind": "add_edge", "base_version": 1,
        "source": "s", "target": "c", "weight": 2,
    })
    for version, original in ((1, r1), (2, r2)):
        got = client.get(
            f"/api/experiments/{eid}/versions/{version}"
        ).json()
        assert got["version"] == version
        assert got["dist"] == original["dist"]
        assert got["pred"] == original["pred"]
        assert got["graph"] == original["graph"]
        assert got["changed"] == original["changed"]
        assert got["reprocessed"] == original["reprocessed"]
        assert got["mode"] == original["mode"]
        assert got["incremental_relax_count"] == original["incremental_relax_count"]

    # 版本列表完整
    summary = client.get(f"/api/experiments/{eid}").json()
    assert summary["versions"] == [0, 1, 2]

    # 取越界版本 → 400
    r = client.get(f"/api/experiments/{eid}/versions/99")
    assert r.status_code == 400


# ---- 404：不存在 / 已淘汰 -----------------------------------------------

def test_missing_experiment_returns_clear_404():
    r = client.get("/api/experiments/doesnotexist")
    assert r.status_code == 404
    assert "实验不存在" in r.json()["detail"]
    r = client.post("/api/experiments/doesnotexist/edits", json={
        "kind": "delete_edge", "base_version": 0,
        "source": "s", "target": "a",
    })
    assert r.status_code == 404
    r = client.get("/api/experiments/doesnotexist/versions/0")
    assert r.status_code == 404


def test_lru_evicts_least_recently_accessed():
    small = experiment_module.ExperimentStore(max_experiments=2)
    e1 = small.create(GRAPH, "s")[0]
    e2 = small.create(GRAPH, "s")[0]
    # 访问 e1，使 e2 成为最久未访问
    small.summarize(e1)
    e3 = small.create(GRAPH, "s")[0]
    # e2 应已被淘汰
    with pytest.raises(experiment_module.ExperimentNotFound):
        small.summarize(e2)
    # e1、e3 仍在
    assert small.summarize(e1).experiment_id == e1
    assert small.summarize(e3).experiment_id == e3


def test_delete_experiment():
    eid = _create()["experiment_id"]
    assert client.delete(f"/api/experiments/{eid}").status_code == 200
    assert client.get(f"/api/experiments/{eid}").status_code == 404
    assert client.delete(f"/api/experiments/{eid}").status_code == 404
