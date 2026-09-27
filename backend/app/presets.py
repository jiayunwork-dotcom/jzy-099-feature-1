"""内置经典示例图，供前端一键载入对照。

- ``positive``   ：非负权图，含一个不可达节点，Dijkstra / Bellman–Ford 结果一致；
- ``negative``   ：带负权边但无负权环，Dijkstra 会算错、Bellman–Ford 正确；
- ``cycle``      ：含源点可达的负权环，最短距离不存在；
- ``longchain``  ：边序「不利」的非负链，展示 Bellman–Ford 需要逐轮传播。
"""

from __future__ import annotations

PRESETS: dict[str, dict] = {
    "positive": {
        "name": "非负权图（含不可达节点）",
        "description": (
            "所有边权非负，Dijkstra 与 Bellman–Ford 的距离结果完全一致；"
            "节点 F 从源点不可达，距离恒为 ∞。"
        ),
        "source": "A",
        "target": "E",
        "graph": {
            "nodes": [
                {"id": "A", "x": 80, "y": 280},
                {"id": "B", "x": 330, "y": 110},
                {"id": "C", "x": 330, "y": 460},
                {"id": "D", "x": 610, "y": 200},
                {"id": "E", "x": 880, "y": 300},
                {"id": "F", "x": 610, "y": 480},
            ],
            "edges": [
                {"source": "A", "target": "B", "weight": 7},
                {"source": "A", "target": "C", "weight": 3},
                {"source": "C", "target": "B", "weight": 2},
                {"source": "B", "target": "D", "weight": 4},
                {"source": "C", "target": "D", "weight": 9},
                {"source": "B", "target": "E", "weight": 15},
                {"source": "C", "target": "E", "weight": 20},
                {"source": "D", "target": "E", "weight": 1},
            ],
        },
    },
    "negative": {
        "name": "带负权边、无负权环",
        "description": (
            "边 C→B 权为 −3。Bellman–Ford 给出正确结果（d[B]=2, d[E]=11）；"
            "Dijkstra 过早确定 B 的距离，结果不可信（会误得 d[E]=12）。"
        ),
        "source": "A",
        "target": "E",
        "graph": {
            "nodes": [
                {"id": "A", "x": 80, "y": 300},
                {"id": "B", "x": 340, "y": 110},
                {"id": "C", "x": 340, "y": 480},
                {"id": "D", "x": 620, "y": 250},
                {"id": "E", "x": 880, "y": 300},
            ],
            "edges": [
                {"source": "A", "target": "B", "weight": 4},
                {"source": "A", "target": "C", "weight": 5},
                {"source": "B", "target": "D", "weight": 7},
                {"source": "C", "target": "B", "weight": -3},
                {"source": "C", "target": "D", "weight": 5},
                {"source": "D", "target": "E", "weight": 2},
                {"source": "A", "target": "E", "weight": 15},
            ],
        },
    },
    "cycle": {
        "name": "含源点可达的负权环",
        "description": (
            "B→C（2）与 C→B（−6）构成权为 −4 的负权环。"
            "每绕一圈总权继续减小，B、C、D、E、F 的最短距离均不存在。"
        ),
        "source": "A",
        "target": "E",
        "graph": {
            "nodes": [
                {"id": "A", "x": 60, "y": 300},
                {"id": "B", "x": 300, "y": 130},
                {"id": "C", "x": 300, "y": 470},
                {"id": "D", "x": 560, "y": 300},
                {"id": "E", "x": 800, "y": 140},
                {"id": "F", "x": 800, "y": 460},
            ],
            "edges": [
                {"source": "A", "target": "B", "weight": 3},
                {"source": "A", "target": "C", "weight": 6},
                {"source": "B", "target": "C", "weight": 2},
                {"source": "C", "target": "B", "weight": -6},
                {"source": "B", "target": "D", "weight": 5},
                {"source": "D", "target": "E", "weight": 2},
                {"source": "D", "target": "F", "weight": 7},
                {"source": "E", "target": "F", "weight": 1},
            ],
        },
    },
    "longchain": {
        "name": "非负长链（Bellman–Ford 逐轮传播）",
        "description": (
            "边按 C→D、B→C、A→B 的顺序存储，Bellman–Ford 每轮只能把已知距离"
            "向前传播一个节点，需要 V−1 轮才收敛；Dijkstra 则按距离增长依次确定。"
        ),
        "source": "A",
        "target": "D",
        "graph": {
            "nodes": [
                {"id": "C", "x": 620, "y": 300},
                {"id": "D", "x": 880, "y": 300},
                {"id": "B", "x": 360, "y": 300},
                {"id": "A", "x": 100, "y": 300},
            ],
            "edges": [
                {"source": "C", "target": "D", "weight": 2},
                {"source": "B", "target": "C", "weight": 3},
                {"source": "A", "target": "B", "weight": 5},
            ],
        },
    },
}


def list_presets() -> dict:
    """返回预设列表（包含完整图数据，前端可直接载入）。"""
    return PRESETS
