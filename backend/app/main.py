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
