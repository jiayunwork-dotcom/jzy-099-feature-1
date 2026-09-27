"""负权环检测。

Bellman–Ford 跑满 V−1 轮后若仍能松弛某条边，说明存在从源点可达的负权环。
本模块负责三件互相独立的事：

1. :func:`relax_one_pass`：在给定距离/前驱表上按固定边序松弛一轮，
   返回仍被更新的目标节点（供检测轮使用，也便于单测）；
2. :func:`find_negative_cycle`：从检测轮更新后的前驱关系图中沿前驱链回溯，
   找出具体的环并用**真实边权之和为负**加以校验；
3. :func:`nodes_affected_by_cycle`：找出所有被负权环污染的节点
   （从环上沿出边可达，最短距离应为 −∞）。
"""

from __future__ import annotations

from .graph import Graph


def relax_one_pass(
    graph: Graph,
    dist: dict[str, float | None],
    pred: dict[str, str | None],
) -> list[str]:
    """按固定边序做一轮（就地）松弛，返回本轮距离被更新的目标节点列表。"""
    updated: list[str] = []
    for edge in graph.edges:
        du = dist[edge.source]
        if du is None:
            continue
        candidate = du + edge.weight
        dv = dist[edge.target]
        if dv is None or candidate < dv:
            dist[edge.target] = candidate
            pred[edge.target] = edge.source
            updated.append(edge.target)
    return updated


def _pred_cycle(pred: dict[str, str | None], start: str) -> list[str] | None:
    """从 start 沿前驱链回溯，进入环时返回环上节点（沿前驱方向、首尾不重复）。"""
    seen: dict[str, int] = {}
    chain: list[str] = []
    node: str | None = start
    while node is not None and node not in seen:
        seen[node] = len(chain)
        chain.append(node)
        node = pred.get(node)
    if node is None:
        return None
    return chain[seen[node]:]


def _build_forward_cycle(
    graph: Graph, pred_cycle: list[str]
) -> tuple[list[str], list[dict], float] | None:
    """把沿前驱方向得到的环整理成沿有向边的顺序，并用真实边权校验为负。

    pred_cycle = [x0, x1, ..., x_{k-1}] 满足 pred[x_i] = x_{i+1}（下标模 k），
    故图上的有向边为 x_{i+1} → x_i，正向环就是把序列反转。
    """
    edge_index = {(e.source, e.target): e for e in graph.edges}
    forward = list(reversed(pred_cycle))
    edges: list[dict] = []
    total = 0.0
    for i, u in enumerate(forward):
        v = forward[(i + 1) % len(forward)]
        edge = edge_index.get((u, v))
        if edge is None:
            return None  # 前驱指向的边在图中不存在，防御性兜底
        edges.append({"source": u, "target": v, "weight": edge.weight})
        total += edge.weight
    if total >= 0:
        return None
    return forward, edges, total


def find_negative_cycle(
    graph: Graph,
    source: str,
    dist: dict[str, float | None],
    pred: dict[str, str | None],
    candidates: list[str],
) -> tuple[list[str], list[dict], float | None]:
    """从检测轮更新后的前驱关系图中定位一个源点可达的负权环。

    :param candidates: 检测轮中仍被松弛的节点；
    :returns: ``(cycle_nodes, cycle_edges, total_weight)``，
        cycle_nodes 按环上有向边顺序排列、首尾不重复；检测不到返回空。
    """
    tries = list(dict.fromkeys(candidates))  # 去重保序
    tries.extend(v for v in graph.node_ids if v not in tries)  # 兜底全量扫描

    reachable = graph.reachable_from(source)
    for start in tries:
        pred_cycle = _pred_cycle(pred, start)
        if not pred_cycle:
            continue
        if not all(node in reachable for node in pred_cycle):
            continue
        built = _build_forward_cycle(graph, pred_cycle)
        if built is not None:
            return built
    return [], [], None


def nodes_affected_by_cycle(graph: Graph, source: str,
                            cycle_nodes: list[str]) -> list[str]:
    """沿出边做 BFS，求被负权环污染的全部节点（含环上节点）。

    这些节点的最短路径可以无限次绕环使总权趋于 −∞，
    因此不能返回任何有限的最短距离。
    """
    affected: set[str] = set(cycle_nodes)
    stack = list(cycle_nodes)
    while stack:
        u = stack.pop()
        for edge in graph.neighbors(u):
            if edge.target not in affected:
                affected.add(edge.target)
                stack.append(edge.target)
    reachable = graph.reachable_from(source)
    return [v for v in graph.node_ids if v in affected and v in reachable]
