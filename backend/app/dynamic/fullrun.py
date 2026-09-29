"""全量基准：在一张图上从头跑一遍 Bellman–Ford。

动态实验里它只在三种场合被调用：

1. 开实验（版本 0）给出一份完整初始结果；
2. 上一版处于「含负权环」状态时，任何编辑都无法安全地局部修复（旧标签
   根本不是有限最短距离），直接全量重算；
3. 作为对照基准返回 ``full_relax_count``——同一张图从头跑一遍要检查多少条边。

本实现与 :func:`app.bellman_ford.run_bellman_ford` 采用**完全相同**的松弛顺序、
提前停止与检测轮逻辑，因此最终距离 / 前驱 / 负权环结果逐字段一致（有测试钉住），
区别仅在于这里不产出逐步 trace，而是返回实际检查过的边数。
"""

from __future__ import annotations

from typing import Any

from ..graph import Graph
from ..negative_cycle import find_all_negatively_affected


def full_bellman_ford(graph: Graph, source: str) -> dict[str, Any]:
    """从头跑 Bellman–Ford，返回结果与实际边检查次数。

    返回字段：``dist`` / ``pred`` / ``has_negative_cycle`` / ``cycle`` /
    ``affected`` / ``reachable`` / ``edge_checks``。

    计数口径与教学版一致：每一轮都按固定边序检查全部 |E| 条边（不论该边
    是否成功松弛），检测轮同样检查全部边；某一轮整轮无更新则提前停止。

    负权环 / −∞ 集合用 :func:`find_all_negatively_affected` 完备求解
    （多轮检测，不漏掉需要多跳才能污染到的节点），并据此修正距离表。
    """
    n = len(graph)
    dist: dict[str, float | None] = {v: None for v in graph.node_ids}
    pred: dict[str, str | None] = {v: None for v in graph.node_ids}
    dist[source] = 0.0

    edge_checks = 0
    passes_run = 0  # 实际跑完的松弛轮数（含提前停止的那一轮空轮）

    for _ in range(1, n):
        passes_run += 1
        updated_any = False
        for edge in graph.edges:
            edge_checks += 1
            du = dist[edge.source]
            if du is None:
                continue
            candidate = du + edge.weight
            dv = dist[edge.target]
            if dv is None or candidate < dv:
                dist[edge.target] = candidate
                pred[edge.target] = edge.source
                updated_any = True
        if not updated_any:
            break

    # ---- 检测轮：再检查全部边一次（仅用于计数与「是否有环」） ----------
    detect_dist = dict(dist)
    edge_checks += len(graph.edges)
    still_updating = False
    for edge in graph.edges:
        du = detect_dist[edge.source]
        if du is None:
            continue
        candidate = du + edge.weight
        dv = detect_dist[edge.target]
        if dv is None or candidate < dv:
            detect_dist[edge.target] = candidate
            still_updating = True

    reachable = graph.reachable_from(source)

    if still_updating:
        # 完备地求 −∞ 集合与一个真实负权环（修正检测轮的漏标）
        affected, cycle_nodes, cycle_edges, cycle_weight = (
            find_all_negatively_affected(graph, source)
        )
        for v in affected:
            dist[v] = None  # −∞：不存在有限最短距离
        cycle_info: dict[str, Any] | None = (
            {
                "nodes": cycle_nodes,
                "edges": cycle_edges,
                "weight": cycle_weight,
            }
            if cycle_nodes
            else None
        )
        has_cycle = True
    else:
        affected = []
        cycle_info = None
        has_cycle = False

    return {
        "dist": dist,
        "pred": pred,
        "has_negative_cycle": has_cycle,
        "cycle": cycle_info,
        "affected": affected,
        "reachable": sorted(reachable),
        "edge_checks": edge_checks,
        "passes_run": passes_run,
    }
