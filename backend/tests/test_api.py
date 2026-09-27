"""HTTP 接口层测试（非法输入带原因、负权拒绝/放行、预设、路径回溯）。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


POSITIVE_BODY = {
    "graph": {
        "nodes": [
            {"id": "A", "x": 0, "y": 0},
            {"id": "B", "x": 1, "y": 1},
        ],
        "edges": [{"source": "A", "target": "B", "weight": 3}],
    },
    "source": "A",
    "target": "B",
    "algorithm": "dijkstra",
}


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_presets_exposed():
    resp = client.get("/api/presets")
    assert resp.status_code == 200
    data = resp.json()
    assert {"positive", "negative", "cycle", "longchain"} <= set(data)
    for item in data.values():
        assert item["graph"]["nodes"] and item["graph"]["edges"]
        assert "name" in item and "description" in item


def test_dijkstra_run_and_path():
    resp = client.post("/api/run", json=POSITIVE_BODY)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["dist"] == {"A": 0.0, "B": 3.0}
    assert data["steps"][0]["type"] == "init"
    assert data["path"]["exists"]
    assert data["path"]["nodes"] == ["A", "B"]
    assert data["path"]["total_weight"] == 3.0


def test_bellman_ford_run():
    body = dict(POSITIVE_BODY, algorithm="bellman_ford")
    resp = client.post("/api/run", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["dist"] == {"A": 0.0, "B": 3.0}
    assert data["has_negative_cycle"] is False
    # BF 无优先队列
    assert all(step["queue"] == [] for step in data["steps"])


def test_dijkstra_rejects_negative_edge_with_reason():
    body = {
        "graph": {
            "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "edges": [
                {"source": "A", "target": "B", "weight": 4},
                {"source": "A", "target": "C", "weight": 5},
                {"source": "C", "target": "B", "weight": -3},
            ],
        },
        "source": "A",
        "algorithm": "dijkstra",
    }
    resp = client.post("/api/run", json=body)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "负权边" in detail
    # 拒绝信息必须明确指向具体的负权边，并提示改用 Bellman–Ford
    assert "C" in detail and "B" in detail and "Bellman" in detail
    # 此时不能偷偷给出距离结果
    assert "steps" not in resp.json()


def test_dijkstra_allow_negative_returns_warning():
    body = {
        "graph": {
            "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "edges": [
                {"source": "A", "target": "B", "weight": 4},
                {"source": "A", "target": "C", "weight": 5},
                {"source": "C", "target": "B", "weight": -3},
            ],
        },
        "source": "A",
        "algorithm": "dijkstra",
        "allow_negative": True,
    }
    resp = client.post("/api/run", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["warning"] is not None


def test_bellman_ford_reports_negative_cycle_over_http():
    body = {
        "graph": {
            "nodes": [
                {"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"},
            ],
            "edges": [
                {"source": "A", "target": "B", "weight": 3},
                {"source": "B", "target": "C", "weight": 2},
                {"source": "C", "target": "B", "weight": -6},
                {"source": "B", "target": "D", "weight": 4},
            ],
        },
        "source": "A",
        "target": "D",
        "algorithm": "bellman_ford",
    }
    resp = client.post("/api/run", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["has_negative_cycle"] is True
    assert set(data["cycle"]["nodes"]) == {"B", "C"}
    assert data["cycle"]["weight"] == -4.0
    for v in data["affected"]:
        assert data["dist"][v] is None
    # 经过负权环的目标路径明确不可用
    assert data["path"]["exists"] is False
    assert "负权环" in data["path"]["reason"]


def test_unknown_source_rejected():
    body = dict(POSITIVE_BODY, source="Z")
    resp = client.post("/api/run", json=body)
    assert resp.status_code == 400
    assert "源点不存在" in resp.json()["detail"]


def test_dangling_edge_rejected():
    body = {
        "graph": {
            "nodes": [{"id": "A"}],
            "edges": [{"source": "A", "target": "B", "weight": 1}],
        },
        "source": "A",
        "algorithm": "dijkstra",
    }
    resp = client.post("/api/run", json=body)
    assert resp.status_code == 400
    assert "不存在的终点" in resp.json()["detail"]


def test_empty_graph_rejected():
    body = {"graph": {"nodes": [], "edges": []},
            "source": "A", "algorithm": "dijkstra"}
    resp = client.post("/api/run", json=body)
    assert resp.status_code == 400


def test_extra_field_rejected():
    body = dict(POSITIVE_BODY, bogus=1)
    resp = client.post("/api/run", json=body)
    assert resp.status_code == 422


def test_preset_cycle_end_to_end():
    presets = client.get("/api/presets").json()
    body = {
        "graph": presets["cycle"]["graph"],
        "source": presets["cycle"]["source"],
        "algorithm": "bellman_ford",
    }
    data = client.post("/api/run", json=body).json()
    assert data["has_negative_cycle"] is True
