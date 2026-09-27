"""Dijkstra 单源最短路径（要求非负权）。

除最终结果外，本模块产出一份**逐步 trace**：每个中间状态都带有距离表快照、
正在处理的边、已确定节点集合以及优先队列内容，前端据此驱动动画。
"""

from __future__ import annotations

from typing import Optional

from .graph import Graph, GraphError

INF = None  # JSON 中用 null 表示无穷大


def _snapshot(dist: dict, pred: dict, settled: list[str],
              queue: list[list], *, active_edges=None, current_node=None,
              step_type: str, message: str, relaxed: Optional[bool] = None,
              pass_index: Optional[int] = None) -> dict:
    """组装一个中间状态快照。dist 中的 +∞ 统一转成 null。"""
    step: dict = {
        "type": step_type,
        "message": message,
        "dist": {k: (None if v is None else v) for k, v in dist.items()},
        "pred": dict(pred),
        "settled": list(settled),
        "current_node": current_node,
        "active_edges": active_edges,
        "queue": [[node, d] for node, d in queue],
        "pass": pass_index,
        "relaxed": relaxed,
    }
    return step


def _queue_view(queue: dict, settled: set[str]) -> list[list]:
    """优先队列的教学视图：每个未确定节点只保留当前最优条目，按 (距离, id) 排序。"""
    return sorted(
        ([node, d] for node, d in queue.items() if node not in settled),
        key=lambda item: (item[1], item[0]),
    )


def run_dijkstra(graph: Graph, source: str, *, allow_negative: bool = False) -> dict:
    """在 graph 上从 source 运行 Dijkstra，返回结果与逐步 trace。

    :param allow_negative: 为 True 时不拒绝负权边，但结果会带 warning，
        前端必须明确提示「结果不可信」。
    :raises GraphError: 图含负权边且未显式放行，或源点不存在。
    """
    if source not in graph.nodes:
        raise GraphError(f"源点不存在：{source}")

    negative_edges = [
        (e.source, e.target) for e in graph.edges if e.weight < 0
    ]
    warning: Optional[str] = None
    if negative_edges:
        u, v = negative_edges[0]
        msg = (
            f"图中存在负权边（如 {u}→{v}），Dijkstra 可能给出错误结果；"
            "请改用 Bellman–Ford。"
        )
        if not allow_negative:
            raise GraphError(msg)
        warning = msg + "（以下结果仅供演示，不保证正确）"

    n = len(graph)
    dist: dict[str, Optional[float]] = {v: None for v in graph.node_ids}
    pred: dict[str, Optional[str]] = {v: None for v in graph.node_ids}
    dist[source] = 0.0

    # queue 存每个未确定节点当前已知的最优距离；取最小即优先队列弹出
    queue: dict[str, float] = {source: 0.0}
    settled: list[str] = []
    settled_set: set[str] = set()
    steps: list[dict] = []

    steps.append(_snapshot(
        dist, pred, settled, _queue_view(queue, settled_set),
        step_type="init",
        message=(
            f"初始化：源点 {source} 距离为 0，其余节点为 ∞；"
            f"优先队列 = [{source}(0)]。"
        ),
    ))

    while queue:
        # 模拟优先队列弹出距离最小者（同距离按节点 id 打破平局，保证可复现）
        u = min(queue, key=lambda node: (queue[node], node))
        du = queue.pop(u)
        settled.append(u)
        settled_set.add(u)

        steps.append(_snapshot(
            dist, pred, settled,
            _queue_view(queue, settled_set),
            current_node=u,
            step_type="settle",
            message=(
                f"从优先队列弹出距离最小的节点 {u}（d={fmt_num(du)}），"
                f"非负权下该距离即为最短距离，标记为已确定。"
            ),
        ))

        for edge in graph.neighbors(u):
            v, w = edge.target, edge.weight
            if v in settled_set:
                # 已确定的节点不会再被更新（非负权保证），跳过
                continue
            active = [{"source": u, "target": v}]
            dv = dist[v]
            candidate = du + w
            if dv is None or candidate < dv:
                dist[v] = candidate
                pred[v] = u
                queue[v] = candidate  # 等价于优先队列的 decrease-key
                relaxed = True
                old = "∞" if dv is None else fmt_num(dv)
                message = (
                    f"松弛边 {u}→{v}（权 {fmt_num(w)}）："
                    f"{fmt_num(du)} + {fmt_num(w)} = {fmt_num(candidate)} "
                    f"< {old}，更新 d[{v}]，节点入队/降键。"
                )
            else:
                relaxed = False
                message = (
                    f"检查边 {u}→{v}（权 {fmt_num(w)}）："
                    f"{fmt_num(du)} + {fmt_num(w)} = {fmt_num(candidate)} "
                    f"≥ d[{v}]={fmt_num(dv)}，不松弛。"
                )
            steps.append(_snapshot(
                dist, pred, settled,
                _queue_view(queue, settled_set),
                active_edges=active, current_node=u,
                step_type="relax", message=message, relaxed=relaxed,
            ))

    reachable = graph.reachable_from(source)
    unreachable = [v for v in graph.node_ids if v not in reachable]
    tail = (
        f"队列为空，算法结束。节点 {', '.join(unreachable)} 从 {source} 不可达，距离为 ∞。"
        if unreachable else "队列为空，所有可达节点的最短距离均已确定。"
    )
    steps.append(_snapshot(
        dist, pred, settled, [],
        step_type="finished", message=tail,
    ))

    return {
        "algorithm": "dijkstra",
        "source": source,
        "dist": dist,
        "pred": pred,
        "settled": settled,
        "reachable": sorted(reachable),
        "steps": steps,
        "warning": warning,
        "has_negative_cycle": False,
        "cycle": None,
        "affected": [],
    }


def fmt_num(x) -> str:
    """数字展示：整数去 .0，None 显示 ∞。"""
    if x is None:
        return "∞"
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)
