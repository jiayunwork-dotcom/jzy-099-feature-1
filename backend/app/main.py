"""FastAPI 入口：承载算法接口并在生产环境托管前端构建产物。

算法全部由后端计算，接口返回最终结果 + 逐步 trace；
前端只渲染 trace，不自行实现算法。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .bellman_ford import run_bellman_ford
from .dijkstra import run_dijkstra
from .dynamic.experiment import (
    ExperimentNotFound,
    InvalidEdit,
    StaleVersion,
    store as experiment_store,
)
from .dynamic.schemas import (
    CreateExperimentRequest,
    EditPayload,
    ExperimentCreated,
    ExperimentResult,
    ExperimentSummary,
)
from .graph import Graph, GraphError
from .models import RunRequest, RunResponse
from .path import backtrack_path
from .presets import list_presets

app = FastAPI(
    title="最短路径算法教学看板 API",
    version="1.0.0",
    description="Dijkstra / Bellman–Ford 逐步演示，含负权环检测与路径回溯。",
)


def _error(message: str, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/presets")
def presets() -> dict:
    return {
        key: {
            "name": data["name"],
            "description": data["description"],
            "source": data["source"],
            "target": data.get("target"),
            "graph": data["graph"],
        }
        for key, data in list_presets().items()
    }


@app.post("/api/run", response_model=RunResponse)
def run_algorithm(req: RunRequest):
    """运行指定算法。非法输入 / Dijkstra 负权（未放行）→ 400 并说明原因。"""
    try:
        graph = Graph.from_payload(req.model_dump()["graph"])
    except GraphError as exc:
        raise _error(f"图结构非法：{exc}")

    if not graph.nodes:
        raise _error("图为空：请至少添加一个节点")
    if req.source not in graph.nodes:
        raise _error(f"源点不存在：{req.source}")
    if req.target is not None and req.target not in graph.nodes:
        raise _error(f"目标节点不存在：{req.target}")

    try:
        if req.algorithm == "dijkstra":
            result = run_dijkstra(graph, req.source,
                                  allow_negative=req.allow_negative)
        else:
            result = run_bellman_ford(graph, req.source)
    except GraphError as exc:
        # 例如 Dijkstra 遇到负权边：明确拒绝，而不是悄悄给错答案
        raise _error(str(exc))

    if req.target is not None:
        result["path"] = backtrack_path(
            graph, req.source, req.target,
            result["dist"], result["pred"],
            affected=result.get("affected"),
        )

    # 统一校验返回结构；异常会以 500 暴露，便于开发期发现问题
    return RunResponse.model_validate(result)


# ---- 动态实验 -----------------------------------------------------------
#
# 与静态 /api/run 完全独立：开实验后，每次改边都作为一次「编辑」提交，
# 后端在上一版结果上做增量修复，并返回变化清单 / 被重新处理的节点 /
# 逐帧修复过程 / 增量与全量松弛次数对照。

@ app.post("/api/experiments", response_model=ExperimentCreated, status_code=201)
def create_experiment(req: CreateExperimentRequest):
    """对当前图 + 源点开一个实验，返回实验编号、版本 0 与完整初始结果。"""
    try:
        experiment_id, v0 = experiment_store.create(
            req.model_dump()["graph"], req.source
        )
    except InvalidEdit as exc:
        raise _error(str(exc))
    return {
        "experiment_id": experiment_id,
        "version": 0,
        "result": v0.result_payload(req.source),
    }


@ app.post("/api/experiments/{experiment_id}/edits",
           response_model=ExperimentResult)
def submit_experiment_edit(experiment_id: str, req: EditPayload):
    """提交一次图编辑；落后版本返回 409，实验不存在 / 已淘汰返回 404。"""
    try:
        version = experiment_store.submit_edit(experiment_id, req.model_dump())
        return version.result_payload(experiment_store.summarize(experiment_id).source)
    except ExperimentNotFound as exc:
        raise _error(str(exc), status=404)
    except StaleVersion as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InvalidEdit as exc:
        raise _error(str(exc))


@ app.get("/api/experiments/{experiment_id}", response_model=ExperimentSummary)
def get_experiment(experiment_id: str):
    """实验元信息与版本号列表（不含逐版大图）。"""
    try:
        exp = experiment_store.summarize(experiment_id)
    except ExperimentNotFound as exc:
        raise _error(str(exc), status=404)
    return {
        "experiment_id": exp.experiment_id,
        "source": exp.source,
        "current_version": exp.current_version,
        "has_negative_cycle": exp.versions[exp.current_version].has_negative_cycle,
        "created_at": exp.created_at,
        "last_accessed_at": exp.last_accessed_at,
        "versions": sorted(exp.versions),
    }


@ app.get("/api/experiments/{experiment_id}/versions/{version}",
          response_model=ExperimentResult)
def get_experiment_version(experiment_id: str, version: int):
    """按版本号取回那一版的图、距离表与修复结果。"""
    try:
        exp = experiment_store.summarize(experiment_id)
        v = experiment_store.get_version(experiment_id, version)
    except ExperimentNotFound as exc:
        raise _error(str(exc), status=404)
    except InvalidEdit as exc:
        raise _error(str(exc))
    return v.result_payload(exp.source)


@ app.delete("/api/experiments/{experiment_id}")
def delete_experiment(experiment_id: str):
    """退出实验时顺手清理；实验不存在同样返回 404。"""
    try:
        experiment_store.delete(experiment_id)
    except ExperimentNotFound as exc:
        raise _error(str(exc), status=404)
    return {"deleted": True, "experiment_id": experiment_id}


# ---- 生产环境：托管前端静态文件 ----------------------------------------

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if os.getenv("SERVE_FRONTEND", "1") == "1" and STATIC_DIR.is_dir():
    from fastapi.responses import FileResponse

    assets_dir = STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):  # pragma: no cover - 仅生产静态托管
        # 命中真实文件则返回文件，其余路径交给前端 SPA 路由
        candidate = (STATIC_DIR / full_path).resolve()
        if (
            full_path
            and STATIC_DIR.resolve() in candidate.parents
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
