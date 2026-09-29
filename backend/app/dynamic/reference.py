"""同图全量 Bellman–Ford：动态修复的权威对照与松弛计数来源。

这里的全量结果是增量修复**必须**对得上的答案（验收第 1 条），
``relax_count`` 是「同一张图从头跑一遍 Bellman–Ford 要检查多少条边」
的口径，与教学版 :func:`app.bellman_ford.run_bellman_ford` 完全一致：

- 第 1…V−1 轮每轮按固定边序检查全部 E 条边，某轮无更新则提前停止；
- 之后固定再跑一轮检测轮（仍检查全部 E 条边），用于识别负权环；
- 计数按「检查过的边」计，无论该次松弛是否成功、起点是否为 ∞。

不带逐步 trace，便于在随机编辑压测中反复调用。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..graph import Graph
from ..negative_cycle import (
    find_negative_cycle,
    nodes_affected_by_cycle,
)


@dataclass
class FullResult:
    dist: dict[str, float | None]
    pred: dict[str, str | None]
    has_negative_cycle: bool
    cycle: dict | None
    affected: list[str]
    relax_count: int
    passes: int  # 实际执行的松弛轮数（不含检测轮）


def full_bellman_ford(graph: Graph, source: str) -> FullResult:
    n = len(graph)
    dist: dict[str, float | None] = {v: None for v in graph.node_ids}
    pred: dict[str, str | None] = {v: None for v in graph.node_ids}
    dist[source] = 0.0

    passes_done = 0
    # 第 1 … V−1 轮；某轮全无更新即提前收敛
    for pass_index in range(1, n):
        passes_done = pass_index
        updated_any = False
        for edge in graph.edges:
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

    # 检测轮：拷贝距离表再松弛一轮（与教学版实现保持同一口径）
    detect_dist = dict(dist)
    detect_pred = dict(pred)
    still_updating: list[str] = []
    for edge in graph.edges:
        du = detect_dist[edge.source]
        if du is None:
            continue
        candidate = du + edge.weight
        dv = detect_dist[edge.target]
        if dv is None or candidate < dv:
            detect_dist[edge.target] = candidate
            detect_pred[edge.target] = edge.source
            still_updating.append(edge.target)

    # 每轮固定检查全部边；松弛轮 + 一个检测轮
    relax_count = len(graph.edges) * (passes_done + 1)

    if still_updating:
        cycle_nodes, cycle_edges, cycle_weight = find_negative_cycle(
            graph, source, detect_dist, detect_pred, still_updating
        )
        affected = nodes_affected_by_cycle(graph, source, cycle_nodes)
        for v in affected:
            dist[v] = None
        cycle = {
            "nodes": cycle_nodes,
            "edges": cycle_edges,
            "weight": cycle_weight,
        }
        return FullResult(
            dist=dist, pred=pred, has_negative_cycle=True, cycle=cycle,
            affected=affected, relax_count=relax_count, passes=passes_done,
        )

    return FullResult(
        dist=dist, pred=pred, has_negative_cycle=False, cycle=None,
        affected=[], relax_count=relax_count, passes=passes_done,
    )
