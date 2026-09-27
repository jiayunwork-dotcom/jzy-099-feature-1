"""Bellman–Ford 单源最短路径（允许负权边，可识别负权环）。

产出逐步 trace：初始化 → 最多 V−1 轮（每轮按固定顺序松弛所有边）→
第 V 轮检测（若仍有边可松弛，则存在源点可达的负权环）。
检测到负权环时，环上及其下游节点的距离一律标记为 null（即 −∞，
最短路径不存在有限值），并给出环上节点与边，供前端高亮。
"""

from __future__ import annotations

from .graph import Graph, GraphError
from .negative_cycle import (
    find_negative_cycle,
    nodes_affected_by_cycle,
)
from .dijkstra import fmt_num


def _snapshot(dist, pred, settled, queue, *, active_edges=None, current_node=None,
              step_type, message, relaxed=None, pass_index=None,
              cycle=None, affected=None) -> dict:
    return {
        "type": step_type,
        "message": message,
        "dist": dict(dist),
        "pred": dict(pred),
        "settled": list(settled),
        "current_node": current_node,
        "active_edges": active_edges,
        "queue": queue,  # Bellman–Ford 没有优先队列，恒为 []
        "pass": pass_index,
        "relaxed": relaxed,
        "cycle": cycle,
        "affected": affected or [],
    }


def run_bellman_ford(graph: Graph, source: str) -> dict:
    if source not in graph.nodes:
        raise GraphError(f"源点不存在：{source}")

    n = len(graph)
    dist: dict[str, float | None] = {v: None for v in graph.node_ids}
    pred: dict[str, str | None] = {v: None for v in graph.node_ids}
    dist[source] = 0.0

    steps: list[dict] = []
    steps.append(_snapshot(
        dist, pred, [], [],
        step_type="init", pass_index=0,
        message=(
            f"初始化：d[{source}] = 0，其余节点为 ∞。"
            f"接下来最多进行 {max(n - 1, 0)} 轮松弛，每轮检查全部 "
            f"{len(graph.edges)} 条边。"
        ),
    ))

    # ---- 第 1 … V−1 轮 ----------------------------------------------------
    pass_index = 0
    for pass_index in range(1, n):
        updated_any = False
        steps.append(_snapshot(
            dist, pred, [], [],
            step_type="pass_start", pass_index=pass_index,
            message=f"—— 第 {pass_index} 轮开始（按固定顺序松弛所有边）——",
        ))
        for edge in graph.edges:
            u, v, w = edge.source, edge.target, edge.weight
            du, dv = dist[u], dist[v]
            active = [{"source": u, "target": v}]
            if du is None:
                relaxed = False
                message = (
                    f"检查边 {u}→{v}（权 {fmt_num(w)}）：d[{u}] = ∞，"
                    f"无法经过 {u} 到达 {v}，跳过。"
                )
            else:
                candidate = du + w
                if dv is None or candidate < dv:
                    old = "∞" if dv is None else fmt_num(dv)
                    dist[v] = candidate
                    pred[v] = u
                    relaxed = True
                    updated_any = True
                    message = (
                        f"松弛边 {u}→{v}（权 {fmt_num(w)}）："
                        f"{fmt_num(du)} + {fmt_num(w)} = {fmt_num(candidate)} "
                        f"< {old}，更新 d[{v}]，前驱记为 {u}。"
                    )
                else:
                    relaxed = False
                    message = (
                        f"检查边 {u}→{v}（权 {fmt_num(w)}）："
                        f"{fmt_num(du)} + {fmt_num(w)} = {fmt_num(candidate)} "
                        f"≥ d[{v}]={fmt_num(dv)}，不松弛。"
                    )
            steps.append(_snapshot(
                dist, pred, [], [],
                active_edges=active, current_node=u,
                step_type="relax", message=message, relaxed=relaxed,
                pass_index=pass_index,
            ))
        if updated_any:
            steps.append(_snapshot(
                dist, pred, [], [],
                step_type="pass_end", pass_index=pass_index,
                message=f"第 {pass_index} 轮结束：本轮有距离被更新。",
            ))
        else:
            steps.append(_snapshot(
                dist, pred, [], [],
                step_type="pass_end", pass_index=pass_index,
                message="本轮没有任何边能更新距离，已提前收敛，结束松弛。",
            ))
            break

    # ---- 第 V 轮：负权环检测 ---------------------------------------------
    detect_dist = dict(dist)
    detect_pred = dict(pred)
    still_updating: list[str] = []
    steps.append(_snapshot(
        dist, pred, [], [],
        step_type="detect_start", pass_index=n,
        message=(
            f"—— 第 {n} 轮（检测轮）：若仍有边可松弛，"
            "则存在源点可达的负权环 ——"
        ),
    ))
    for edge in graph.edges:
        u, v, w = edge.source, edge.target, edge.weight
        du = detect_dist[u]
        active = [{"source": u, "target": v}]
        if du is None:
            steps.append(_snapshot(
                dist, pred, [], [],
                active_edges=active, current_node=u,
                step_type="detect", message=f"检测边 {u}→{v}：d[{u}] = ∞，跳过。",
                relaxed=False, pass_index=n,
            ))
            continue
        candidate = du + w
        dv = detect_dist[v]
        if dv is None or candidate < dv:
            detect_dist[v] = candidate
            detect_pred[v] = u
            still_updating.append(v)
            steps.append(_snapshot(
                dist, pred, [], [],
                active_edges=active, current_node=u,
                step_type="detect",
                message=(
                    f"检测边 {u}→{v}（权 {fmt_num(w)}）：距离仍能从 "
                    f"{fmt_num(dv)} 降到 {fmt_num(candidate)}！"
                    "说明存在源点可达的负权环。"
                ),
                relaxed=True, pass_index=n,
            ))
        else:
            steps.append(_snapshot(
                dist, pred, [], [],
                active_edges=active, current_node=u,
                step_type="detect",
                message=f"检测边 {u}→{v}：无法再松弛。",
                relaxed=False, pass_index=n,
            ))

    still_updating = list(dict.fromkeys(still_updating))

    result: dict
    if still_updating:
        cycle_nodes, cycle_edges, cycle_weight = find_negative_cycle(
            graph, source, detect_dist, detect_pred, still_updating
        )
        affected = nodes_affected_by_cycle(graph, source, cycle_nodes)
        for v in affected:
            dist[v] = None  # −∞：不存在有限最短距离
        cycle_info = {
            "nodes": cycle_nodes,
            "edges": cycle_edges,
            "weight": cycle_weight,
        }
        steps.append(_snapshot(
            dist, pred, [], [],
            step_type="negative_cycle", pass_index=n,
            message=(
                "存在负权环，最短路不存在！环上节点："
                f"{ '→'.join(cycle_nodes + [cycle_nodes[0]]) if cycle_nodes else '' }；"
                "沿环每绕一圈总权进一步减小，环上及其可达节点的距离标记为 −∞。"
            ),
            cycle=cycle_info, affected=affected,
        ))
        result = {
            "algorithm": "bellman_ford",
            "source": source,
            "dist": dist,
            "pred": pred,
            "settled": [],
            "reachable": sorted(graph.reachable_from(source)),
            "steps": steps,
            "warning": None,
            "has_negative_cycle": True,
            "cycle": cycle_info,
            "affected": affected,
        }
    else:
        reachable = graph.reachable_from(source)
        settled = [v for v in graph.node_ids if v in reachable]
        unreachable = [v for v in graph.node_ids if v not in reachable]
        tail = (
            "检测轮没有边能继续松弛，确认不存在源点可达的负权环，"
            f"各可达节点距离已确定。节点 {', '.join(unreachable)} 不可达，距离为 ∞。"
            if unreachable
            else "检测轮没有边能继续松弛，确认不存在源点可达的负权环，所有距离已确定。"
        )
        steps.append(_snapshot(
            dist, pred, settled, [],
            step_type="finished", pass_index=n, message=tail,
        ))
        result = {
            "algorithm": "bellman_ford",
            "source": source,
            "dist": dist,
            "pred": pred,
            "settled": settled,
            "reachable": sorted(reachable),
            "steps": steps,
            "warning": None,
            "has_negative_cycle": False,
            "cycle": None,
            "affected": [],
        }
    return result
