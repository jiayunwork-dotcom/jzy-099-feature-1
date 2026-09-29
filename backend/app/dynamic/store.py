"""进程内存中的实验表：数量上限 + LRU（最久未访问）淘汰。

- 开实验、提交编辑、取版本都会把对应实验刷新到「最近访问」；
- 超过容量时淘汰 ``last_accessed_at`` 最小的实验；
- 访问一个不存在（或已被淘汰）的 id 抛 :class:`ExperimentNotFound`，
  由 HTTP 层翻译成明确的「实验不存在」，而不是内部错误。
"""

from __future__ import annotations

import threading
from collections import OrderedDict

from .experiment import Experiment


class ExperimentNotFound(KeyError):
    """实验 id 不存在或已被 LRU 淘汰。"""


class VersionNotFound(KeyError):
    """实验存在，但请求的版本号超出范围。"""


class VersionConflict(Exception):
    """编辑基于的版本号落后于实验当前版本。"""

    def __init__(self, current_version: int):
        self.current_version = current_version
        super().__init__(f"版本号冲突：实验当前版本为 {current_version}")


class ExperimentStore:
    def __init__(self, max_experiments: int = 50):
        self._max = max_experiments
        self._items: OrderedDict[str, Experiment] = OrderedDict()
        self._lock = threading.Lock()

    # ---- 写 ------------------------------------------------------------

    def put(self, experiment: Experiment) -> None:
        with self._lock:
            if experiment.id in self._items:
                self._items.move_to_end(experiment.id)
            else:
                self._items[experiment.id] = experiment
                self._evict_locked()

    def _evict_locked(self) -> None:
        while len(self._items) > self._max:
            # OrderedDict 的头部即最久未访问
            self._items.popitem(last=False)

    def delete(self, experiment_id: str) -> None:
        with self._lock:
            self._items.pop(experiment_id, None)

    def clear(self) -> None:
        """测试辅助：清空全部实验。"""
        with self._lock:
            self._items.clear()

    # ---- 读 ------------------------------------------------------------

    def get(self, experiment_id: str) -> Experiment:
        with self._lock:
            experiment = self._items.get(experiment_id)
            if experiment is None:
                raise ExperimentNotFound(experiment_id)
            experiment.touch()
            self._items.move_to_end(experiment_id)
            return experiment

    def get_version(self, experiment_id: str, number: int):
        experiment = self.get(experiment_id)  # 顺带刷新 LRU
        record = experiment.get_version(number)
        if record is None:
            raise VersionNotFound(number)
        return experiment, record

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._items)
