"""动态实验的编辑（edit）：改权、加边、删边，外加页面需要的加 / 删节点。

编辑是在**实验当前版本的图**上校验语义的（引用节点是否存在、边是否已存在
等），校验失败抛 :class:`EditError`，实验状态不得发生任何改动。

编辑本身只负责把旧图变成新图；「增量修复该如何做」在
:mod:`app.dynamic.repair` 中根据旧图 / 新图的差异决定。
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal

from ..graph import Edge, Graph, Node

EditKind = Literal["set_weight", "add_edge", "delete_edge", "add_node", "delete_node"]


class EditError(ValueError):
    """编辑语义非法（引用不存在的节点 / 边、重复边、权重不是有限数等）。"""


@dataclass(frozen=True)
class Edit:
    """一次提交给实验的图编辑。

    ``kind`` 取值：

    - ``set_weight`` ：把已存在的边 u→v 权重改为 weight（调大 / 调小均可）；
    - ``add_edge``   ：新增一条边 u→v，要求该边之前不存在；
    - ``delete_edge``：删除一条边，要求该边之前存在；
    - ``add_node``   ：新增一个节点（x/y 仅用于前端布点）；
    - ``delete_node``：删除一个节点，同时删除它的所有关联边（删源点非法）。
    """

    kind: EditKind
    source: str | None = None
    target: str | None = None
    weight: float | None = None
    node_id: str | None = None
    x: float = 0.0
    y: float = 0.0

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Edit":
        """从已通过 Pydantic 结构校验的纯数据构造编辑，并校验权重有限。"""
        kind = payload.get("kind")
        if kind not in (
            "set_weight", "add_edge", "delete_edge", "add_node", "delete_node",
        ):
            raise EditError(f"未知的编辑类型：{kind!r}")

        def opt_str(key: str) -> str | None:
            value = payload.get(key)
            return None if value is None else str(value).strip()

        weight: float | None = None
        if kind in ("set_weight", "add_edge"):
            raw_weight = payload.get("weight")
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError):
                raise EditError("边权重必须是数字")
            if not isfinite(weight):
                raise EditError("边权重必须是有限数")

        node_id = opt_str("node_id")
        x, y = 0.0, 0.0
        if kind == "add_node":
            if not node_id:
                node_id = None  # 缺省时由 apply 自动生成
            try:
                x = float(payload.get("x", 0.0))
                y = float(payload.get("y", 0.0))
            except (TypeError, ValueError):
                raise EditError("节点坐标必须是数字")

        return cls(
            kind=kind,
            source=opt_str("source"),
            target=opt_str("target"),
            weight=weight,
            node_id=node_id,
            x=x,
            y=y,
        )

    def to_payload(self) -> dict[str, Any]:
        """转回可序列化的纯数据（用于版本历史里展示每次编辑）。"""
        data: dict[str, Any] = {"kind": self.kind}
        if self.source is not None:
            data["source"] = self.source
        if self.target is not None:
            data["target"] = self.target
        if self.weight is not None:
            data["weight"] = self.weight
        if self.node_id is not None:
            data["node_id"] = self.node_id
        if self.kind == "add_node":
            data["x"] = self.x
            data["y"] = self.y
        return data

    def describe(self) -> str:
        """给学生看的一句话编辑说明。"""
        if self.kind == "set_weight":
            return f"把边 {self.source}→{self.target} 的权重改为 {_fmt(self.weight)}"
        if self.kind == "add_edge":
            return f"新增边 {self.source}→{self.target}（权 {_fmt(self.weight)}）"
        if self.kind == "delete_edge":
            return f"删除边 {self.source}→{self.target}"
        if self.kind == "add_node":
            return f"新增节点 {self.node_id}"
        return f"删除节点 {self.node_id}"

    # ---- 在图上校验 / 应用 ---------------------------------------------

    def validate(self, graph: Graph, *, source: str) -> None:
        """校验编辑在 ``graph`` 上可执行；非法时抛 :class:`EditError`。"""
        if self.kind in ("set_weight", "add_edge", "delete_edge"):
            u, v = self.source, self.target
            if not u or not v:
                raise EditError("边编辑必须同时给出 source 和 target")
            if u not in graph.nodes:
                raise EditError(f"编辑引用了不存在的节点：{u}")
            if v not in graph.nodes:
                raise EditError(f"编辑引用了不存在的节点：{v}")
            exists = any(
                e.source == u and e.target == v for e in graph.edges
            )
            if self.kind == "add_edge" and exists:
                raise EditError(f"边 {u}→{v} 已存在，不能重复新增")
            if self.kind in ("set_weight", "delete_edge") and not exists:
                action = "修改权重" if self.kind == "set_weight" else "删除"
                raise EditError(f"边 {u}→{v} 不存在，无法{action}")
            return

        if self.kind == "add_node":
            node_id = (self.node_id or "").strip()
            if not node_id:
                raise EditError("新增节点的 id 不能为空")
            if node_id in graph.nodes:
                raise EditError(f"节点 id 已存在：{node_id}")
            return

        # delete_node
        node_id = self.node_id
        if not node_id:
            raise EditError("删除节点必须给出 node_id")
        if node_id not in graph.nodes:
            raise EditError(f"节点不存在：{node_id}")
        if node_id == source:
            raise EditError(f"不能删除源点：{node_id}（请先退出实验或更换源点）")

    def apply(self, graph: Graph, *, source: str) -> "Graph":
        """返回应用本编辑后的**新图**（不修改旧图），并顺带完成一次校验。"""
        self.validate(graph, source=source)
        new = clone_graph(graph)
        if self.kind == "set_weight":
            edge = next(
                e for e in new.edges
                if e.source == self.source and e.target == self.target
            )
            updated = Edge(edge.source, edge.target, float(self.weight))  # type: ignore[arg-type]
            new.edges = [
                updated if (e.source == edge.source and e.target == edge.target) else e
                for e in new.edges
            ]
            new.adj[edge.source] = [
                updated if (e.source == edge.source and e.target == edge.target) else e
                for e in new.adj[edge.source]
            ]
        elif self.kind == "add_edge":
            edge = Edge(self.source, self.target, float(self.weight))  # type: ignore[arg-type]
            new.edges.append(edge)
            new.adj[self.source].append(edge)
        elif self.kind == "delete_edge":
            new.edges = [
                e for e in new.edges
                if not (e.source == self.source and e.target == self.target)
            ]
            new.adj[self.source] = [
                e for e in new.adj[self.source]
                if not (e.source == self.source and e.target == self.target)
            ]
        elif self.kind == "add_node":
            node = Node(self.node_id, self.x, self.y)  # type: ignore[arg-type]
            new.nodes[node.id] = node
            new.adj[node.id] = []
        else:  # delete_node
            node_id = self.node_id
            del new.nodes[node_id]  # type: ignore[arg-type]
            del new.adj[node_id]
            new.edges = [
                e for e in new.edges
                if e.source != node_id and e.target != node_id
            ]
            for u in list(new.adj):
                new.adj[u] = [
                    e for e in new.adj[u]
                    if e.source != node_id and e.target != node_id
                ]
        return new


def clone_graph(graph: Graph) -> Graph:
    """深拷贝一张图（边 / 节点均为不可变值，复制容器即可）。"""
    new = Graph()
    new.nodes = {k: Node(v.id, v.x, v.y) for k, v in graph.nodes.items()}
    new.edges = [Edge(e.source, e.target, e.weight) for e in graph.edges]
    new.adj = {
        u: [Edge(e.source, e.target, e.weight) for e in edges]
        for u, edges in graph.adj.items()
    }
    return new


def graph_to_payload(graph: Graph) -> dict[str, Any]:
    """把 :class:`Graph` 转回接口使用的纯数据（版本历史需要）。"""
    return {
        "nodes": [
            {"id": node.id, "x": node.x, "y": node.y}
            for node in graph.nodes.values()
        ],
        "edges": [
            {"source": e.source, "target": e.target, "weight": e.weight}
            for e in graph.edges
        ],
    }


def _fmt(x: float | None) -> str:
    if x is None:
        return "∞"
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


# 供前端在新增节点时申请一个服务端不冲突的 id（目前前端本地生成，
# 但保留一个集中入口，避免两边 id 规则漂移）。
def auto_node_id(graph: Graph) -> str:
    used = set(graph.nodes)
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for ch in letters:
        if ch not in used:
            return ch
    i = 1
    while f"N{i}" in used:
        i += 1
    return f"N{i}"
