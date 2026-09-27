"""FastAPI 的请求 / 响应模型（Pydantic v2）。

结构层面的校验（必填字段、JSON 类型、权重是数字）在这里做；
图的*语义*校验（端点存在、重复边等）在 :mod:`app.graph` 里做，
以便算法模块不依赖 Web 层。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class NodeIn(BaseModel):
    id: str
    x: float = 0.0
    y: float = 0.0


class EdgeIn(BaseModel):
    source: str
    target: str
    weight: float = Field(description="边权重，允许为负；必须是有限数")


class GraphIn(BaseModel):
    nodes: list[NodeIn] = Field(default_factory=list)
    edges: list[EdgeIn] = Field(default_factory=list)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: GraphIn
    source: str
    target: Optional[str] = None
    algorithm: Literal["dijkstra", "bellman_ford"]
    # Dijkstra 遇负权默认严格拒绝；勾选「允许执行（结果不可信）」时才放行
    allow_negative: bool = False


# ---- 响应 ---------------------------------------------------------------

class Step(BaseModel):
    """算法执行过程中的一个中间状态快照（前端动画的一帧）。"""

    type: str
    message: str
    dist: dict[str, Optional[float]]
    pred: dict[str, Optional[str]]
    settled: list[str] = []
    current_node: Optional[str] = None
    active_edges: Optional[list[dict[str, Any]]] = None
    queue: list[list[Any]] = Field(
        default_factory=list,
        description="Dijkstra 优先队列内容 [[node, dist], ...]；BF 为空",
    )
    pass_index: Optional[int] = Field(default=None, alias="pass")
    relaxed: Optional[bool] = None
    cycle: Optional[dict[str, Any]] = None
    affected: list[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class PathInfo(BaseModel):
    target: str
    distance: Optional[float] = None
    nodes: list[str] = []
    edges: list[dict[str, Any]] = []
    exists: bool
    reason: Optional[str] = None
    total_weight: Optional[float] = None


class CycleInfo(BaseModel):
    nodes: list[str]
    edges: list[dict[str, Any]]
    weight: Optional[float] = None


class RunResponse(BaseModel):
    algorithm: str
    source: str
    dist: dict[str, Optional[float]]
    pred: dict[str, Optional[str]]
    settled: list[str]
    reachable: list[str]
    steps: list[Step]
    warning: Optional[str] = None
    has_negative_cycle: bool
    cycle: Optional[CycleInfo] = None
    affected: list[str] = []
    path: Optional[PathInfo] = None


class ErrorResponse(BaseModel):
    detail: str
