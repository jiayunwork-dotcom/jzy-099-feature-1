"""边编辑：调权 / 新增边 / 删除边的校验与纯函数应用。

编辑的校验与应用都只操作 :class:`~app.graph.Graph`，不依赖 Web 层，
也不触碰任何距离状态——这样实验服务可以先校验、再改图、再修复，
校验失败时实验状态（图、版本、距离）保持原样。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from math import isfinite
from typing import Any, ClassVar, Literal

from ..graph import Edge, Graph, GraphError

EditKind = Literal["update_weight", "add_edge", "delete_edge"]

UPDATE_WEIGHT: EditKind = "update_weight"
ADD_EDGE: EditKind = "add_edge"
DELETE_EDGE: EditKind = "delete_edge"
VALID_KINDS: tuple[EditKind, ...] = (UPDATE_WEIGHT, ADD_EDGE, DELETE_EDGE)


class EditError(GraphError):
    """单次编辑非法（端点不存在、边已存在 / 不存在、权重非有限数等）。

    这类错误拒绝应用，实验状态保持不变。
    """


@dataclass(frozen=True)
class EdgeEdit:
    """对一条有向边的一次编辑。

    调权（``update_weight``）要求边已存在；新增（``add_edge``）要求边尚不存在；
    删除（``delete_edge``）要求边存在。
    """

    kind: EditKind
    source: str
    target: str
    weight: float | None = None

    UPDATE: ClassVar[EditKind] = UPDATE_WEIGHT
    ADD: ClassVar[EditKind] = ADD_EDGE
    DELETE: ClassVar[EditKind] = DELETE_EDGE

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> "EdgeEdit":
        kind = raw.get("kind")
        if kind not in VALID_KINDS:
            raise EditError(
                "编辑类型非法：kind 必须是 update_weight / add_edge / delete_edge"
            )
        source = str(raw.get("source", "")).strip()
        target = str(raw.get("target", "")).strip()
        if not source or not target:
            raise EditError("编辑缺少端点：source 与 target 都不能为空")
        weight: float | None = None
        if kind != "delete_edge":
            try:
                weight = float(raw["weight"])
            except (KeyError, TypeError, ValueError):
                raise EditError(
                    f"编辑 {source}→{target} 缺少合法的 weight（必须是数字）"
                )
            if not isfinite(weight):
                raise EditError(f"边 {source}→{target} 的权重必须是有限数")
        return cls(kind=kind, source=source, target=target, weight=weight)

    def describe(self) -> str:
        if self.kind == "add_edge":
            return f"新增边 {self.source}→{self.target}（权 {self.weight:g}）"
        if self.kind == "delete_edge":
            return f"删除边 {self.source}→{self.target}"
        return f"把边 {self.source}→{self.target} 的权重改为 {self.weight:g}"


def find_edge(graph: Graph, u: str, v: str) -> Edge | None:
    for edge in graph.edges:
        if edge.source == u and edge.target == v:
            return edge
    return None


def validate_edit(graph: Graph, edit: EdgeEdit) -> None:
    """在不改图的前提下校验编辑；不合法抛 :class:`EditError`。"""
    if edit.source not in graph.nodes:
        raise EditError(f"编辑引用了不存在的节点：{edit.source}")
    if edit.target not in graph.nodes:
        raise EditError(f"编辑引用了不存在的节点：{edit.target}")
    existing = find_edge(graph, edit.source, edit.target)
    if edit.kind == EdgeEdit.UPDATE and existing is None:
        raise EditError(
            f"边 {edit.source}→{edit.target} 不存在，无法调权；"
            "请改用新增边"
        )
    if edit.kind == EdgeEdit.ADD and existing is not None:
        raise EditError(
            f"边 {edit.source}→{edit.target} 已经存在（当前权重 "
            f"{existing.weight:g}），不能重复新增；请改用调权"
        )
    if edit.kind == EdgeEdit.DELETE and existing is None:
        raise EditError(f"边 {edit.source}→{edit.target} 本来就不存在，无法删除")


def apply_edit(graph: Graph, edit: EdgeEdit) -> Graph:
    """返回应用编辑后的**新图**（不就地修改入参，便于历史留档）。"""
    validate_edit(graph, edit)
    new = copy.deepcopy(graph)
    if edit.kind == EdgeEdit.DELETE:
        new.edges = [
            e for e in new.edges
            if not (e.source == edit.source and e.target == edit.target)
        ]
        new.adj[edit.source] = [
            e for e in new.adj[edit.source] if e.target != edit.target
        ]
        return new

    assert edit.weight is not None
    if edit.kind == EdgeEdit.ADD:
        edge = Edge(edit.source, edit.target, edit.weight)
        new.edges.append(edge)
        new.adj[edit.source].append(edge)
        return new

    # 调权：edges 与 adj 中的同一条边都要更新（Edge 是 frozen 的，重建之）
    new.edges = [
        replace(e, weight=edit.weight)
        if e.source == edit.source and e.target == edit.target else e
        for e in new.edges
    ]
    new.adj[edit.source] = [
        replace(e, weight=edit.weight) if e.target == edit.target else e
        for e in new.adj[edit.source]
    ]
    return new


def sync_node_positions(graph: Graph, positions: dict[str, dict[str, float]] | None) -> None:
    """把前端随编辑带来的节点坐标就地同步（坐标不参与任何计算）。

    只允许更新**已存在**节点的坐标；引用不存在的节点直接忽略，
    动态实验不支持增删节点。
    """
    if not positions:
        return
    for node_id, pos in positions.items():
        node = graph.nodes.get(node_id)
        if node is None:
            continue
        try:
            node.x = float(pos.get("x", node.x))
            node.y = float(pos.get("y", node.y))
        except (TypeError, ValueError):
            continue
