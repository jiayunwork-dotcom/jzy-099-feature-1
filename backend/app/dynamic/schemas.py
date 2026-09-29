"""动态实验相关的 Pydantic 请求 / 响应模型。

与静态运行接口（:mod:`app.models`）完全分开，原有 ``/api/run`` 的请求与响应
格式保持不变。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..models import GraphIn


# ---- 请求 ---------------------------------------------------------------

class CreateExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: GraphIn
    source: str


class EditPayload(BaseModel):
    """一次图编辑（提交时必须带上它所基于的版本号）。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "set_weight", "add_edge", "delete_edge", "add_node", "delete_node",
    ]
    base_version: int = Field(
        ge=0,
        description="本编辑基于的版本号；落后于实验当前版本则拒绝（409）。",
    )
    source: Optional[str] = None
    target: Optional[str] = None
    weight: Optional[float] = None
    node_id: Optional[str] = None
    x: float = 0.0
    y: float = 0.0


# ---- 响应 ---------------------------------------------------------------

class ChangeEntry(BaseModel):
    """一个距离真正发生变化的节点：改动前 → 改动后（null 表示 ∞ / −∞）。"""

    node: str
    old: Optional[float] = None
    new: Optional[float] = None


class RepairStep(BaseModel):
    """增量修复过程中的一帧快照（与现有演示同样可逐帧播放）。"""

    type: str
    message: str
    dist: dict[str, Optional[float]]
    pred: dict[str, Optional[str]]
    current_node: Optional[str] = None
    active_edges: Optional[list[dict[str, Any]]] = None
    relaxed: Optional[bool] = None
    #: 本次修复中被作废的节点（截至本帧，累计）
    invalidated: list[str] = []
    #: 本次修复中被重新处理过的节点（截至本帧，累计）
    reprocessed: list[str] = []
    #: full = 全量重算的逐轮演示；incremental = 增量修复演示
    phase: Literal["full", "incremental"] = "incremental"
    cycle: Optional[dict[str, Any]] = None
    affected: list[str] = []
    #: 全量演示帧（Bellman–Ford 逐轮）携带的轮次信息
    pass_index: Optional[int] = Field(default=None, alias="pass")
    settled: list[str] = []
    queue: list[list[Any]] = []

    model_config = ConfigDict(populate_by_name=True)


class ExperimentResult(BaseModel):
    """一次版本结果：初始结果或一次编辑后的修复结果。"""

    mode: Literal["full", "incremental"]
    reason: Optional[str] = Field(
        default=None,
        description="mode=full 时写明为什么这一版退回了全量重算。",
    )
    version: int
    source: str
    graph: dict[str, Any]
    dist: dict[str, Optional[float]]
    pred: dict[str, Optional[str]]
    has_negative_cycle: bool
    cycle: Optional[dict[str, Any]] = None
    affected: list[str] = []
    reachable: list[str] = []
    changed: list[ChangeEntry] = []
    reprocessed: list[str] = []
    steps: list[RepairStep]
    incremental_relax_count: int
    full_relax_count: int
    edit: Optional[dict[str, Any]] = None


class ExperimentSummary(BaseModel):
    experiment_id: str
    source: str
    current_version: int
    has_negative_cycle: bool
    created_at: float
    last_accessed_at: float
    versions: list[int]


class ExperimentCreated(BaseModel):
    experiment_id: str
    version: int = 0
    result: ExperimentResult
