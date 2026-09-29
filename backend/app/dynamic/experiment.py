"""实验与版本管理（纯内存，带 LRU 上限）。

一个 :class:`Experiment` 绑定一张初始图与一个源点，持有完整的版本历史：
版本 0 是全量初始结果，之后每次编辑产生一个新版本。实验之间互不影响；
编辑带版本号做乐观并发控制，落后即拒绝。

:class:`ExperimentStore` 用一把锁串行化全部操作，实验数超过
:data:`MAX_EXPERIMENTS` 时淘汰「最久没被访问」（LRU，按
``last_accessed_at``）的那个。已被淘汰 / 不存在的实验一律抛
:class:`ExperimentNotFound`，由路由层翻译成明确的 404，而不是内部错误。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..graph import Graph, GraphError
from .edits import Edit, EditError, graph_to_payload
from .repair import (
    apply_full_recompute,
    apply_incremental_repair,
    initial_result,
)

# 内存中同时保留的实验数量上限；超出后淘汰最久未访问的实验
MAX_EXPERIMENTS = 50

# 打破负权环等必须全量重算时给出的统一理由
FULL_FROM_CYCLE_REASON = (
    "上一版处于「含负权环」状态：旧距离标签不是有限最短距离，"
    "无法在其基础上做局部修复，本次退回全量重算，"
    "在改动后的图上整图运行 Bellman–Ford。"
)


class ExperimentError(Exception):
    """实验层业务错误基类（路由据此返回带原因的 4xx）。"""


class ExperimentNotFound(ExperimentError):
    """实验不存在或已被 LRU 淘汰。"""


class StaleVersion(ExperimentError):
    """编辑基于的版本号落后于实验当前版本（HTTP 409）。"""


class InvalidEdit(ExperimentError):
    """编辑语义非法（HTTP 400），实验状态不变。"""


@dataclass
class Version:
    """一个不可变的历史版本。"""

    version: int
    graph: Graph
    graph_payload: dict[str, Any]
    dist: dict[str, float | None]
    pred: dict[str, str | None]
    has_negative_cycle: bool
    cycle: dict[str, Any] | None
    affected: list[str]
    reachable: list[str]
    changed: list[dict[str, Any]]
    reprocessed: list[str]
    steps: list[dict[str, Any]]
    mode: str
    reason: str | None
    incremental_relax_count: int
    full_relax_count: int
    edit: dict[str, Any] | None
    created_at: float

    def result_payload(self, source: str) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "reason": self.reason,
            "version": self.version,
            "source": source,
            "graph": self.graph_payload,
            "dist": self.dist,
            "pred": self.pred,
            "has_negative_cycle": self.has_negative_cycle,
            "cycle": self.cycle,
            "affected": list(self.affected),
            "reachable": list(self.reachable),
            "changed": [dict(c) for c in self.changed],
            "reprocessed": list(self.reprocessed),
            "steps": self.steps,
            "incremental_relax_count": self.incremental_relax_count,
            "full_relax_count": self.full_relax_count,
            "edit": self.edit,
        }


@dataclass
class Experiment:
    experiment_id: str
    source: str
    versions: dict[int, Version] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)

    @property
    def current_version(self) -> int:
        return max(self.versions)

    def touch(self) -> None:
        self.last_accessed_at = time.time()


class ExperimentStore:
    """线程安全的内存实验表，LRU 淘汰。"""

    def __init__(self, *, max_experiments: int = MAX_EXPERIMENTS) -> None:
        self._experiments: dict[str, Experiment] = {}
        self._lock = threading.RLock()
        self._max = max_experiments

    # ---- 内部 ----------------------------------------------------------

    def _get_live(self, experiment_id: str) -> Experiment:
        exp = self._experiments.get(experiment_id)
        if exp is None:
            raise ExperimentNotFound(
                f"实验不存在或已被淘汰：{experiment_id}"
            )
        exp.touch()
        return exp

    def _evict_if_needed(self) -> None:
        while len(self._experiments) >= self._max:
            victim_id = min(
                self._experiments,
                key=lambda key: self._experiments[key].last_accessed_at,
            )
            del self._experiments[victim_id]

    # ---- 对外 API ------------------------------------------------------

    def create(self, graph_payload: dict[str, Any], source: str) -> tuple[str, Version]:
        """开一个新实验：校验图 / 源点，跑版本 0 的全量初始结果。"""
        try:
            graph = Graph.from_payload(graph_payload)
        except GraphError as exc:
            raise InvalidEdit(f"图结构非法：{exc}")
        if not graph.nodes:
            raise InvalidEdit("图为空：请至少添加一个节点")
        if source not in graph.nodes:
            raise InvalidEdit(f"源点不存在：{source}")

        with self._lock:
            self._evict_if_needed()
            experiment_id = uuid.uuid4().hex[:12]
            while experiment_id in self._experiments:
                experiment_id = uuid.uuid4().hex[:12]
            exp = Experiment(experiment_id=experiment_id, source=source)

            outcome = initial_result(graph, source)
            v0 = Version(
                version=0,
                graph=graph,
                graph_payload=graph_to_payload(graph),
                dist=dict(outcome["dist"]),
                pred=dict(outcome["pred"]),
                has_negative_cycle=outcome["has_negative_cycle"],
                cycle=outcome["cycle"],
                affected=list(outcome["affected"]),
                reachable=list(outcome["reachable"]),
                changed=[],
                reprocessed=list(outcome["reprocessed"]),
                steps=outcome["steps"],
                mode=outcome["mode"],
                reason=outcome["reason"],
                incremental_relax_count=outcome["incremental_relax_count"],
                full_relax_count=outcome["full_relax_count"],
                edit=None,
                created_at=time.time(),
            )
            exp.versions[0] = v0
            self._experiments[experiment_id] = exp
            return experiment_id, v0

    def submit_edit(self, experiment_id: str,
                    edit_payload: dict[str, Any]) -> Version:
        """在实验当前版本上提交一次编辑，做增量修复（必要时全量重算）。"""
        with self._lock:
            exp = self._get_live(experiment_id)
            try:
                edit = Edit.from_payload(edit_payload)
            except EditError as exc:
                raise InvalidEdit(str(exc))

            base_version = edit_payload.get("base_version")
            current = exp.current_version
            if not isinstance(base_version, int) or base_version < current:
                raise StaleVersion(
                    f"编辑基于的版本号 {base_version!r} 已过期：实验当前版本为 "
                    f"{current}，本次编辑被拒绝，实验状态保持不变。"
                )
            if base_version > current:
                raise InvalidEdit(
                    f"编辑基于的版本号 {base_version} 超前于实验当前版本 {current}。"
                )

            old_version = exp.versions[current]
            old_graph = old_version.graph

            # 语义校验在旧图上进行；任何失败都必须在改动实验之前抛出
            try:
                new_graph = edit.apply(old_graph, source=exp.source)
            except EditError as exc:
                raise InvalidEdit(str(exc))

            if old_version.has_negative_cycle:
                outcome = apply_full_recompute(
                    new_graph=new_graph,
                    source=exp.source,
                    old_dist=dict(old_version.dist),
                    reason=FULL_FROM_CYCLE_REASON,
                )
            else:
                outcome = apply_incremental_repair(
                    old_graph=old_graph,
                    new_graph=new_graph,
                    source=exp.source,
                    old_dist=dict(old_version.dist),
                    old_pred=dict(old_version.pred),
                    edit=edit,
                )

            new_version_no = current + 1
            version = Version(
                version=new_version_no,
                graph=new_graph,
                graph_payload=graph_to_payload(new_graph),
                dist=dict(outcome["dist"]),
                pred=dict(outcome["pred"]),
                has_negative_cycle=outcome["has_negative_cycle"],
                cycle=outcome["cycle"],
                affected=list(outcome["affected"]),
                reachable=list(outcome["reachable"]),
                changed=list(outcome["changed"]),
                reprocessed=list(outcome["reprocessed"]),
                steps=outcome["steps"],
                mode=outcome["mode"],
                reason=outcome["reason"],
                incremental_relax_count=outcome["incremental_relax_count"],
                full_relax_count=outcome["full_relax_count"],
                edit=edit.to_payload(),
                created_at=time.time(),
            )
            exp.versions[new_version_no] = version
            exp.touch()
            return version

    def get_version(self, experiment_id: str,
                    version: int | None = None) -> Version:
        """取回某一版（默认当前版）的完整结果。"""
        with self._lock:
            exp = self._get_live(experiment_id)
            if version is None:
                version = exp.current_version
            v = exp.versions.get(version)
            if v is None:
                raise InvalidEdit(
                    f"版本 {version} 不存在：该实验共有 0…{exp.current_version} 版。"
                )
            return v

    def summarize(self, experiment_id: str) -> Experiment:
        with self._lock:
            return self._get_live(experiment_id)

    def delete(self, experiment_id: str) -> None:
        with self._lock:
            self._get_live(experiment_id)  # 不存在则抛 404
            del self._experiments[experiment_id]


# 进程级单例（接口层共享；测试可自行 new 一个小容量的 store）
store = ExperimentStore()
