"""动态实验层：在已有 Bellman–Ford 结果之上做边编辑的增量修复。

与静态算法层（:mod:`app.bellman_ford` 等）完全解耦：

- :mod:`app.dynamic.edits`     ：边编辑（改权 / 加边 / 删边）的校验与纯函数应用；
- :mod:`app.dynamic.reference` ：同图全量 Bellman–Ford 权威结果与松弛计数；
- :mod:`app.dynamic.repair`    ：在上一版距离/前驱上做局部增量修复（允许负权）；
- :mod:`app.dynamic.experiment`：实验与版本记录的数据模型；
- :mod:`app.dynamic.store`     ：内存中的实验表（数量上限 + LRU 淘汰）；
- :mod:`app.dynamic.service`   ：把以上模块编排成「开实验 / 提交编辑 / 取版本」。
"""
