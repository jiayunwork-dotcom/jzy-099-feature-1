"""最短路径回溯。

根据算法结束时的前驱表，从目标节点一路回溯到源点，
还原「源点 → 目标」的具体节点序列、边序列与总权重。
若目标不可达、受负权环污染或前驱表无法连回源点，则给出明确原因。
"""

from __future__ import annotations

from .graph import Graph


def backtrack_path(
    graph: Graph,
    source: str,
    target: str,
    dist: dict[str, float | None],
    pred: dict[str, str | None],
    *,
    affected: list[str] | None = None,
) -> dict:
    """还原 source → target 的最短路径。

    返回 ``{target, distance, nodes, edges, exists, reason}``。
    """
    edge_index = {(e.source, e.target): e for e in graph.edges}
    affected = affected or []

    def fail(reason: str) -> dict:
        return {
            "target": target,
            "distance": None,
            "nodes": [],
            "edges": [],
            "exists": False,
            "reason": reason,
            "total_weight": None,
        }

    if target not in graph.nodes:
        return fail(f"目标节点不存在：{target}")
    if target == source:
        return {
            "target": target,
            "distance": 0.0,
            "nodes": [source],
            "edges": [],
            "exists": True,
            "reason": None,
            "total_weight": None,
        }
    if target in affected:
        return fail("目标节点受负权环影响，最短距离为 −∞，最短路径不存在")
    if dist.get(target) is None:
        return fail(f"节点 {target} 从源点 {source} 不可达，距离为 ∞")

    # 沿前驱回溯（防御性地限制步数，异常前驱表不会导致死循环）
    chain: list[str] = [target]
    guard = 0
    node = target
    while node != source:
        node = pred.get(node)  # type: ignore[assignment]
        guard += 1
        if node is None or guard > len(graph) + 1:
            return fail("前驱链无法连回源点，路径不存在")
        chain.append(node)

    nodes = list(reversed(chain))
    edges: list[dict] = []
    total = 0.0
    for u, v in zip(nodes, nodes[1:]):
        edge = edge_index.get((u, v))
        if edge is None:
            return fail(f"前驱边 {u}→{v} 在图中不存在")
        edges.append({"source": u, "target": v, "weight": edge.weight})
        total += edge.weight

    return {
        "target": target,
        "distance": dist[target],
        "nodes": nodes,
        "edges": edges,
        "exists": True,
        "reason": None,
        "total_weight": total,
    }
