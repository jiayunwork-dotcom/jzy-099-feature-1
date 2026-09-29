"""动态实验 HTTP 接口端到端测试（含错误码与历史版本接口）。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def body_graph():
    return {
        "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "F"}],
        "edges": [
            {"source": "A", "target": "B", "weight": 7},
            {"source": "A", "target": "C", "weight": 3},
            {"source": "C", "target": "B", "weight": 2},
            {"source": "B", "target": "C", "weight": 4},
        ],
    }


def test_create_experiment_returns_version_zero():
    resp = client.post("/api/experiments", json={
        "graph": body_graph(), "source": "A"})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["version"] == 0
    assert data["current_version"] == 0
    assert data["mode"] == "initial"
    assert data["experiment_id"]
    assert data["dist"]["A"] == 0.0
    assert data["changed"] == []
    assert data["steps"][0]["type"] == "init"
    assert data["relax_count"] == data["full_relax_count"]


def test_create_rejects_bad_graph_and_missing_source():
    resp = client.post("/api/experiments", json={
        "graph": {"nodes": [], "edges": []}, "source": "A"})
    assert resp.status_code == 400
    resp = client.post("/api/experiments", json={
        "graph": body_graph(), "source": "Z"})
    assert resp.status_code == 400
    assert "源点不存在" in resp.json()["detail"]


def test_edit_full_roundtrip_and_counts_side_by_side():
    eid = client.post("/api/experiments", json={
        "graph": body_graph(), "source": "A"}).json()["experiment_id"]

    # 非树边调大：距离表纹丝不动，增量 0 次检查
    resp = client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 0, "kind": "update_weight",
        "source": "A", "target": "B", "weight": 100})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["version"] == 1
    assert data["changed"] == []
    assert data["reprocessed"] == []
    assert data["relax_count"] == 0
    assert data["full_relax_count"] > 0
    assert data["mode"] == "incremental"

    # 树边调大：局部修复
    resp = client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 1, "kind": "update_weight",
        "source": "C", "target": "B", "weight": 10})
    data = resp.json()
    assert data["version"] == 2
    assert {c["node"] for c in data["changed"]} == {"B"}
    assert data["steps"][0]["type"] == "repair_edit"


def test_stale_edit_409_keeps_state():
    eid = client.post("/api/experiments", json={
        "graph": body_graph(), "source": "A"}).json()["experiment_id"]
    client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 0, "kind": "update_weight",
        "source": "A", "target": "B", "weight": 10})
    resp = client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 0, "kind": "update_weight",
        "source": "A", "target": "B", "weight": 20})
    assert resp.status_code == 409
    assert "1" in resp.json()["detail"]
    history = client.get(f"/api/experiments/{eid}").json()
    assert history["current_version"] == 1
    assert len(history["versions"]) == 2


def test_invalid_edits_400_with_reason():
    eid = client.post("/api/experiments", json={
        "graph": body_graph(), "source": "A"}).json()["experiment_id"]

    r1 = client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 0, "kind": "update_weight",
        "source": "A", "target": "Z", "weight": 1})
    assert r1.status_code == 400 and "不存在的节点" in r1.json()["detail"]

    r2 = client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 0, "kind": "delete_edge",
        "source": "B", "target": "A"})
    assert r2.status_code == 400 and "本来就不存在" in r2.json()["detail"]

    r3 = client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 0, "kind": "add_edge",
        "source": "A", "target": "B", "weight": 1})
    assert r3.status_code == 400 and "已经存在" in r3.json()["detail"]

    r4 = client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 0, "kind": "bogus",
        "source": "A", "target": "B"})
    assert r4.status_code == 400

    # 全部被拒绝：仍停留在版本 0
    assert client.get(f"/api/experiments/{eid}").json()["current_version"] == 0


def test_missing_experiment_and_version_404():
    r1 = client.get("/api/experiments/nope-nope")
    assert r1.status_code == 404
    assert "实验不存在" in r1.json()["detail"]

    r2 = client.post("/api/experiments/nope-nope/edits", json={
        "base_version": 0, "kind": "update_weight",
        "source": "A", "target": "B", "weight": 1})
    assert r2.status_code == 404

    eid = client.post("/api/experiments", json={
        "graph": body_graph(), "source": "A"}).json()["experiment_id"]
    r3 = client.get(f"/api/experiments/{eid}/versions/7")
    assert r3.status_code == 404 and "版本不存在" in r3.json()["detail"]


def test_history_endpoint_lists_versions():
    eid = client.post("/api/experiments", json={
        "graph": body_graph(), "source": "A"}).json()["experiment_id"]
    client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 0, "kind": "update_weight",
        "source": "A", "target": "B", "weight": 2})
    client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 1, "kind": "add_edge",
        "source": "B", "target": "A", "weight": -3})
    data = client.get(f"/api/experiments/{eid}").json()
    assert data["current_version"] == 2
    assert [v["version"] for v in data["versions"]] == [0, 1, 2]
    assert data["versions"][1]["edit"]["kind"] == "update_weight"
    assert data["versions"][2]["mode"] == "full"  # 出现负环 → 全量


def test_version_fetch_returns_graph_and_dist_of_that_version():
    eid = client.post("/api/experiments", json={
        "graph": body_graph(), "source": "A"}).json()["experiment_id"]
    client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 0, "kind": "update_weight",
        "source": "A", "target": "C", "weight": 1})
    v0 = client.get(f"/api/experiments/{eid}/versions/0").json()
    v1 = client.get(f"/api/experiments/{eid}/versions/1").json()
    assert v0["dist"]["C"] == 3.0
    assert v1["dist"]["C"] == 1.0
    assert v0["graph"]["edges"] != v1["graph"]["edges"] or \
        v0["dist"] != v1["dist"]
    edge = next(e for e in v0["graph"]["edges"]
                if e["source"] == "A" and e["target"] == "C")
    assert edge["weight"] == 3


def test_cycle_make_and_break_over_http():
    graph = {
        "nodes": [{"id": n} for n in "ABCD"],
        "edges": [
            {"source": "A", "target": "B", "weight": 3},
            {"source": "A", "target": "C", "weight": 6},
            {"source": "B", "target": "C", "weight": 2},
            {"source": "B", "target": "D", "weight": 5},
        ],
    }
    eid = client.post("/api/experiments", json={
        "graph": graph, "source": "A"}).json()["experiment_id"]
    made = client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 0, "kind": "add_edge",
        "source": "C", "target": "B", "weight": -6}).json()
    assert made["has_negative_cycle"] is True
    assert made["mode"] == "full"
    for node in made["affected"]:
        assert made["dist"][node] is None

    broken = client.post(f"/api/experiments/{eid}/edits", json={
        "base_version": 1, "kind": "update_weight",
        "source": "C", "target": "B", "weight": 6}).json()
    assert broken["has_negative_cycle"] is False
    assert broken["mode"] == "full"
    assert broken["dist"] == {"A": 0.0, "B": 3.0, "C": 5.0, "D": 8.0}


def test_experiment_does_not_touch_static_run_endpoint():
    # 静态接口请求/响应格式不变
    resp = client.post("/api/run", json={
        "graph": {
            "nodes": [{"id": "A"}, {"id": "B"}],
            "edges": [{"source": "A", "target": "B", "weight": 3}],
        },
        "source": "A", "algorithm": "bellman_ford"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["dist"] == {"A": 0.0, "B": 3.0}
    # 静态接口响应保持原样：不含动态实验才有的字段
    assert "invalidated" not in data["steps"][0]
    assert "reprocessed" not in data
