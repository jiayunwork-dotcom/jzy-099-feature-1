"""实验与版本记录的数据模型。

一个 :class:`Experiment` 绑定「一张图 + 一个源点」，持有从版本 0 开始的
完整版本序列；每个 :class:`VersionRecord` 同时保存那一版的图、距离/前驱、
负权环状态以及（非初始版本）本次修复的全过程，因此可以按版本号取回
任意一版的图和距离表。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..graph import Graph
from .edits import EdgeEdit


@dataclass
class VersionRecord:
    version: int
    graph: Graph
    dist: dict[str, float | None]
    pred: dict[str, str | None]
    has_negative_cycle: bool
    cycle: dict | None
    affected: list[str]
    steps: list[dict]
    changed: list[dict]          # [{node, before, after}]
    reprocessed: list[str]
    invalidated: list[str]
    mode: str                    # "full" | "incremental" | "initial"
    reason: str
    relax_count: int
    full_relax_count: int
    edit: EdgeEdit | None = None  # 版本 0 没有编辑
    created_at: float = field(default_factory=time.time)


@dataclass
class Experiment:
    id: str
    source: str
    versions: list[VersionRecord]
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)

    @property
    def version(self) -> int:
        return self.versions[-1].version

    @property
    def latest(self) -> VersionRecord:
        return self.versions[-1]

    def touch(self) -> None:
        self.last_accessed_at = time.time()

    def get_version(self, number: int) -> VersionRecord | None:
        if 0 <= number < len(self.versions):
            return self.versions[number]
        return None
