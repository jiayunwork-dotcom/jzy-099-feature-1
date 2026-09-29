"""动态实验 HTTP 路由。

- POST /api/experiments               开实验（返回实验 id、版本 0、全量初始结果）
- GET  /api/experiments/{id}          实验当前版本概览（含完整版本列表）
- GET  /api/experiments/{id}/versions/{v}   按版本号取回那一版的图和距离表
- POST /api/experiments/{id}/edits    提交一次边编辑（带 base_version 乐观锁）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..graph import Graph, GraphError
from .api_models import (
    CreateExperimentRequest,
    DynamicStep,
    EditRequest,
    ExperimentVersionResponse,
    HistoryResponse,
)
from .edits import EdgeEdit, EditError
from .service import DynamicService
from .store import ExperimentNotFound, VersionConflict, VersionNotFound

router = APIRouter(prefix="/api/experiments", tags=["dynamic-experiments"])

# 进程内单例：所有实验保存在服务内存里（LRU 淘汰）
service = DynamicService()


def _error(message: str, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


def _validate_steps(steps: list[dict]) -> list[dict]:
    """用动态帧模型统一校验修复帧（在静态 Step 上另加 invalidated）。"""
    return [
        DynamicStep.model_validate(step).model_dump(by_alias=True)
        for step in steps
    ]


@router.post("", response_model=ExperimentVersionResponse, status_code=201)
def create_experiment(req: CreateExperimentRequest):
    try:
        graph = Graph.from_payload(req.model_dump()["graph"])
    except GraphError as exc:
        raise _error(f"图结构非法：{exc}")
    if not graph.nodes:
        raise _error("图为空：请至少添加一个节点")
    if req.source not in graph.nodes:
        raise _error(f"源点不存在：{req.source}")
    experiment, record = service.create_experiment(graph, req.source)
    payload = service.serialize_version(experiment, record)
    payload["steps"] = _validate_steps(payload["steps"])
    return ExperimentVersionResponse.model_validate(payload)


@router.post("/{experiment_id}/edits", response_model=ExperimentVersionResponse)
def submit_edit(experiment_id: str, req: EditRequest):
    try:
        edit = EdgeEdit.from_payload(req.model_dump())
    except EditError as exc:
        raise _error(str(exc))

    try:
        experiment, record = service.submit_edit(
            experiment_id, edit, req.base_version, positions=req.positions
        )
    except ExperimentNotFound:
        raise _error(f"实验不存在：{experiment_id}（可能已被淘汰，请重新开实验）",
                     status=404)
    except VersionConflict as exc:
        raise _error(
            f"编辑基于的版本号 {req.base_version} 已过期：实验当前版本为 "
            f"{exc.current_version}，请先取回最新版本再提交；本次编辑未应用，"
            "实验状态保持不变。",
            status=409,
        )
    except EditError as exc:
        # 端点不存在 / 边已存在 / 边不存在：实验状态不变
        raise _error(str(exc))

    payload = service.serialize_version(experiment, record)
    payload["steps"] = _validate_steps(payload["steps"])
    return ExperimentVersionResponse.model_validate(payload)


@router.get("/{experiment_id}", response_model=HistoryResponse)
def get_experiment(experiment_id: str):
    try:
        experiment = service.get_experiment(experiment_id)
    except ExperimentNotFound:
        raise _error(f"实验不存在：{experiment_id}（可能已被淘汰，请重新开实验）",
                     status=404)
    return HistoryResponse.model_validate(service.serialize_history(experiment))


@router.get(
    "/{experiment_id}/versions/{version}",
    response_model=ExperimentVersionResponse,
)
def get_version(experiment_id: str, version: int):
    try:
        experiment, record = service.get_version(experiment_id, version)
    except VersionNotFound:
        raise _error(
            f"版本不存在：实验 {experiment_id} 没有版本 {version}",
            status=404,
        )
    except ExperimentNotFound:
        raise _error(f"实验不存在：{experiment_id}（可能已被淘汰，请重新开实验）",
                     status=404)
    payload = service.serialize_version(experiment, record)
    payload["steps"] = _validate_steps(payload["steps"])
    return ExperimentVersionResponse.model_validate(payload)
