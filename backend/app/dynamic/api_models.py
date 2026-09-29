"""动态实验接口的请求 / 响应模型（Pydantic v2）。

与静态 :mod:`app.models` 平行：静态 ``/api/run`` 的请求响应格式保持不变，
动态实验的模型全部集中在这里。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..models import GraphIn, Step


class DynamicStep(Step):
    """增量修复帧：在静态 Step 之上额外携带「本帧已作废、待重算」节点。

    静态 /api/run 的响应模型保持原样（不含 invalidated），动态实验的
    帧用这个模型校验与序列化。
    """

    invalidated: list[str] = Field(default_factory=list)


class CreateExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: GraphIn
    source: str


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(
        ge=0,
        description="本次编辑基于的版本号；落后于当前版本会被拒绝（409）",
    )
    kind: str = Field(
        description="update_weight（调权）/ add_edge（新增边）/ delete_edge（删边）"
    )
    source: str
    target: str
    weight: Optional[float] = None
    # 前端画布上的节点坐标随编辑同步（坐标不参与计算）
    positions: Optional[dict[str, dict[str, float]]] = None


class ChangedDistance(BaseModel):
    node: str
    before: Optional[float] = None
    after: Optional[float] = None


class EditInfo(BaseModel):
    kind: str
    source: str
    target: str
    weight: Optional[float] = None
    description: Optional[str] = None


class ExperimentVersionResponse(BaseModel):
    experiment_id: str
    source: str
    version: int
    current_version: int
    mode: str = Field(description="initial / incremental / full")
    reason: str
    graph: dict[str, Any]
    dist: dict[str, Optional[float]]
    pred: dict[str, Optional[str]]
    has_negative_cycle: bool
    cycle: Optional[dict[str, Any]] = None
    affected: list[str]
    reachable: list[str]
    changed: list[ChangedDistance]
    reprocessed: list[str]
    invalidated: list[str]
    relax_count: int
    full_relax_count: int
    steps: list[dict[str, Any]]
    edit: Optional[EditInfo] = None


class VersionSummary(BaseModel):
    version: int
    mode: str
    has_negative_cycle: bool
    changed_count: int
    relax_count: int
    full_relax_count: int
    edit: Optional[EditInfo] = None


class HistoryResponse(BaseModel):
    experiment_id: str
    source: str
    current_version: int
    versions: list[VersionSummary]
