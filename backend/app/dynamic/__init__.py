"""动态实验：在已有最短路径结果上做增量修复。

本包与静态算法模块（``dijkstra`` / ``bellman_ford``）解耦：

- :mod:`app.dynamic.edits`       —— 编辑（改权 / 加边 / 删边 / 加节点 / 删节点）的
  语义校验与应用；
- :mod:`app.dynamic.repair`      —— 在上一版结果上做局部增量修复，产出修复 trace、
  距离变化清单、被重新处理的节点集合与松弛计数；
- :mod:`app.dynamic.fullrun`     —— 同一张图从头跑一遍 Bellman–Ford 的规范实现，
  只用于「全量基准」：初始结果、负权环状态切换时的重算、以及松弛次数对照；
- :mod:`app.dynamic.experiment`  —— 实验、版本历史与 LRU 淘汰（纯内存）；
- :mod:`app.dynamic.schemas`     —— 动态实验相关的 Pydantic 请求 / 响应模型。
"""
