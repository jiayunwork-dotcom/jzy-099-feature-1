"""带权有向图模型与输入校验。

算法模块只依赖本模块定义的 :class:`Graph`，不直接接触 HTTP / Pydantic，
保证算法可以独立测试、独立复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Iterable, Iterator


class GraphError(ValueError):
    """图结构非法（引用不存在的节点、重复边、权重不是有限数等）。"""


@dataclass(frozen=True)
class Edge:
    """一条有向带权边。"""

    source: str
    target: str
    weight: float


@dataclass
class Node:
    """一个节点，x/y 仅用于前端布点，不参与算法。"""

    id: str
    x: float = 0.0
    y: float = 0.0


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    # 用插入序的 dict 邻接表，保证松弛顺序确定、trace 可复现
    adj: dict[str, list[Edge]] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    # ---- 构造 ----------------------------------------------------------

    @classmethod
    def from_payload(cls, payload: dict) -> "Graph":
        """从接口收到的纯数据（已通过 Pydantic 结构校验）构造图，

        并在此完成算法相关的语义校验：
        节点 id 非空且唯一；边端点必须存在；权重是有限数；
        同一对 (source, target) 只允许一条边（含自环）。
        """
        raw_nodes = payload.get("nodes") or []
        raw_edges = payload.get("edges") or []

        graph = cls()
        for i, raw in enumerate(raw_nodes):
            node_id = str(raw["id"]).strip()
            if not node_id:
                raise GraphError(f"第 {i + 1} 个节点的 id 不能为空")
            if node_id in graph.nodes:
                raise GraphError(f"节点 id 重复：{node_id}")
            try:
                x = float(raw.get("x", 0.0))
                y = float(raw.get("y", 0.0))
            except (TypeError, ValueError):
                raise GraphError(f"节点 {node_id} 的坐标必须是数字")
            graph.nodes[node_id] = Node(node_id, x, y)
            graph.adj[node_id] = []

        for i, raw in enumerate(raw_edges):
            u = str(raw["source"]).strip()
            v = str(raw["target"]).strip()
            try:
                w = float(raw["weight"])
            except (TypeError, ValueError):
                raise GraphError(
                    f"第 {i + 1} 条边（{u}→{v}）的权重必须是数字"
                )
            if not isfinite(w):
                raise GraphError(f"边 {u}→{v} 的权重必须是有限数")
            if u not in graph.nodes:
                raise GraphError(f"第 {i + 1} 条边引用了不存在的起点：{u}")
            if v not in graph.nodes:
                raise GraphError(f"第 {i + 1} 条边引用了不存在的终点：{v}")
            if any(e.source == u and e.target == v for e in graph.edges):
                raise GraphError(f"同一对节点之间不允许重复边：{u}→{v}")
            edge = Edge(u, v, w)
            graph.edges.append(edge)
            graph.adj[u].append(edge)

        return graph

    # ---- 查询 ----------------------------------------------------------

    @property
    def node_ids(self) -> list[str]:
        return list(self.nodes)

    def neighbors(self, u: str) -> list[Edge]:
        return self.adj[u]

    def __len__(self) -> int:
        return len(self.nodes)

    def __iter__(self) -> Iterator[str]:
        return iter(self.nodes)

    def reachable_from(self, source: str) -> set[str]:
        """从 source 出发沿有向边可达的全部节点（含自身）。"""
        seen: set[str] = set()
        stack = [source]
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            stack.extend(e.target for e in self.adj[u])
        return seen

    def edges_from(self, source: str) -> Iterable[Edge]:
        """从某节点出发可达范围内的所有边（用于负权环检测）。"""
        seen_nodes = self.reachable_from(source)
        for edge in self.edges:
            if edge.source in seen_nodes:
                yield edge

    def relax(self, dist: dict[str, float], pred: dict[str, str | None],
              edge: Edge) -> bool:
        """尝试松弛一条边，成功则更新距离/前驱并返回 True。

        距离为 None（已被标记为「负权环影响」）的起点不再参与松弛。
        """
        du = dist[edge.source]
        if du is None:
            return False
        candidate = du + edge.weight
        dv = dist[edge.target]
        if dv is None or candidate < dv:
            dist[edge.target] = candidate
            pred[edge.target] = edge.source
            return True
        return False
