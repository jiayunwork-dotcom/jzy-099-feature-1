"""动态实验编排层：把编辑、增量修复、全量权威结果、版本归档串起来。

修复模式只有两种：

- ``initial``     ：版本 0，整图全量 Bellman–Ford（完整逐轮演示）；
- ``incremental`` ：在上一版结果上由 :mod:`app.dynamic.repair` 局部修复；
- ``full``        ：退回整图全量 Bellman–Ford，响应中必带原因
  （从上一版的负权环状态恢复，或增量修复自己检出了新产生的负权环）。
"""

from __future__ import annotations

import copy
import uuid
from math import isclose

from ..bellman_ford import run_bellman_ford
from ..graph import Graph
from .edits import EdgeEdit, apply_edit, find_edge, sync_node_positions
from .experiment import Experiment, VersionRecord
from .reference import full_bellman_ford
from .repair import incremental_repair
from .store import ExperimentStore, VersionConflict

# 教学进程内存有限，实验太多就淘汰最久没访问的
DEFAULT_MAX_EXPERIMENTS = 50

_EPS = 1e-9


class DynamicService:
    def __init__(self, max_experiments: int = DEFAULT_MAX_EXPERIMENTS):
        self.store = ExperimentStore(max_experiments=max_experiments)

    # ---- 工具 ----------------------------------------------------------

    @staticmethod
    def _changed_nodes(old_dist, new_dist, node_order) -> list[dict]:
        """对比前后距离表，返回 [{node, before, after}]（null = ∞ / −∞ 槽位）。"""
        changed = []
        for node in node_order:
            before = old_dist.get(node)
            after = new_dist.get(node)
            same = (
                before == after
                if before is None or after is None
                else isclose(before, after, rel_tol=0.0, abs_tol=_EPS)
            )
            if not same:
                changed.append({"node": node, "before": before, "after": after})
        return changed

    @staticmethod
    def _graph_payload(graph: Graph) -> dict:
        return {
            "nodes": [
                {"id": node.id, "x": node.x, "y": node.y}
                for node in graph.nodes.values()
            ],
            "edges": [
                {"source": e.source, "target": e.target, "weight": e.weight}
                for e in graph.edges
            ],
        }

    # ---- 开实验：版本 0 全量 ------------------------------------------

    def create_experiment(self, graph: Graph, source: str) -> tuple[Experiment, VersionRecord]:
        bf = run_bellman_ford(graph, source)
        full = full_bellman_ford(graph, source)
        record = VersionRecord(
            version=0,
            graph=copy.deepcopy(graph),
            dist=bf["dist"],
            pred=bf["pred"],
            has_negative_cycle=bf["has_negative_cycle"],
            cycle=bf["cycle"],
            affected=list(bf["affected"]),
            steps=bf["steps"],
            changed=[],
            reprocessed=[],
            invalidated=[],
            mode="initial",
            reason=(
                "实验初始化：从源点全量运行 Bellman–Ford"
                + ("（初始图即含源点可达的负权环）" if bf["has_negative_cycle"] else "")
            ),
            relax_count=full.relax_count,
            full_relax_count=full.relax_count,
            edit=None,
        )
        experiment = Experiment(
            id=uuid.uuid4().hex[:12],
            source=source,
            versions=[record],
        )
        self.store.put(experiment)
        return experiment, record

    # ---- 提交一次编辑 --------------------------------------------------

    def submit_edit(
        self,
        experiment_id: str,
        edit: EdgeEdit,
        base_version: int,
        positions: dict | None = None,
    ) -> tuple[Experiment, VersionRecord]:
        experiment = self.store.get(experiment_id)  # 不存在 → ExperimentNotFound
        current = experiment.latest

        if base_version != current.version:
            # 拒绝基于旧版本的编辑，实验状态原封不动
            raise VersionConflict(current.version)

        # validate_edit 抛 EditError 时，下面的代码一行都不会执行，
        # 图、版本、距离全部保持原样
        new_graph = apply_edit(current.graph, edit)
        sync_node_positions(new_graph, positions)
        old_edge = find_edge(current.graph, edit.source, edit.target)
        old_weight = old_edge.weight if old_edge is not None else None

        old_dist, old_pred = current.dist, current.pred
        new_version_no = current.version + 1

        # ---- 上一版已含负权环：恢复阶段一律先试全量 ------------------
        if current.has_negative_cycle:
            record = self._full_record(
                experiment, new_graph, new_version_no, edit,
                reason="上一版含源点可达的负权环，先用全量 Bellman–Ford 恢复权威结果",
            )
            experiment.versions.append(record)
            self.store.put(experiment)
            return experiment, record

        # ---- 增量修复 ------------------------------------------------
        # repair 内部已用受限 Bellman–Ford 严格判定是否产生了负环；
        # 无环时才需要跑一遍全量，仅为取得「从头跑 BF 的松弛次数」口径。
        repair = incremental_repair(
            new_graph, experiment.source,
            old_dist, old_pred, edit, old_weight,
        )

        if repair.cycle_detected:
            # 增量修复检出了新环：退回全量给权威 −∞ 标注，
            # 但保留增量帧，让学生看到「环是怎么冒出来的」
            record = self._full_record(
                experiment, new_graph, new_version_no, edit,
                reason=(
                    "本次编辑在源点可达范围内产生了负权环：增量修复的"
                    "负环安全校验仍能松弛，已退回全量 Bellman–Ford 定位环"
                    "并标注 −∞"
                ),
                prefix_steps=repair.steps,
                prefix_counts=repair.relax_count,
                prefix_reprocessed=repair.reprocessed,
                prefix_invalidated=repair.invalidated,
            )
        else:
            full = full_bellman_ford(new_graph, experiment.source)
            changed = self._changed_nodes(
                old_dist, repair.dist, new_graph.node_ids
            )
            record = VersionRecord(
                version=new_version_no,
                graph=new_graph,
                dist=repair.dist,
                pred=repair.pred,
                has_negative_cycle=False,
                cycle=None,
                affected=[],
                steps=repair.steps,
                changed=changed,
                reprocessed=list(repair.reprocessed),
                invalidated=list(repair.invalidated),
                mode="incremental",
                reason=repair.note,
                relax_count=repair.relax_count,
                full_relax_count=full.relax_count,
                edit=edit,
            )
        experiment.versions.append(record)
        self.store.put(experiment)
        return experiment, record

    def _full_record(
        self,
        experiment: Experiment,
        new_graph: Graph,
        version_no: int,
        edit: EdgeEdit,
        *,
        reason: str,
        prefix_steps: list[dict] | None = None,
        prefix_counts: int = 0,
        prefix_reprocessed: list[str] | None = None,
        prefix_invalidated: list[str] | None = None,
    ) -> VersionRecord:
        """构造一个全量模式的版本记录。"""
        bf = run_bellman_ford(new_graph, experiment.source)
        full = full_bellman_ford(new_graph, experiment.source)
        old_dist = experiment.latest.dist
        changed = self._changed_nodes(old_dist, bf["dist"], new_graph.node_ids)

        steps: list[dict] = []
        if prefix_steps is not None:
            # 保留「增量修复发现环」的完整前情
            steps.extend(prefix_steps)
        else:
            steps.append({
                "type": "repair_edit",
                "message": f"本次编辑：{edit.describe()}。",
                "dist": dict(old_dist),
                "pred": dict(experiment.latest.pred),
                "settled": [],
                "current_node": None,
                "active_edges": [{"source": edit.source, "target": edit.target}],
                "queue": [],
                "pass": None,
                "relaxed": None,
                "cycle": None,
                "affected": [],
                "invalidated": [],
            })

        steps.append({
            "type": "repair_full",
            "message": (
                f"本次不走增量，改为在整图上全量重跑 Bellman–Ford。原因：{reason}。"
            ),
            "dist": dict(bf["dist"]),
            "pred": dict(bf["pred"]),
            "settled": [],
            "current_node": None,
            "active_edges": None,
            "queue": [],
            "pass": None,
            "relaxed": None,
            "cycle": bf["cycle"],
            "affected": list(bf["affected"]),
            "invalidated": [],
        })
        # 全量逐轮 trace 紧随其后（沿用教学版 Bellman–Ford 的每一帧）
        steps.extend(bf["steps"])

        reprocessed = prefix_reprocessed
        if reprocessed is None:
            # 纯粹的全量重算（如环被打破后的恢复）：所有源点可达节点都被重处理
            reprocessed = [
                v for v in new_graph.node_ids
                if v in set(bf["reachable"])
            ]
        return VersionRecord(
            version=version_no,
            graph=new_graph,
            dist=bf["dist"],
            pred=bf["pred"],
            has_negative_cycle=bf["has_negative_cycle"],
            cycle=bf["cycle"],
            affected=list(bf["affected"]),
            steps=steps,
            changed=changed,
            reprocessed=list(reprocessed),
            invalidated=list(prefix_invalidated or []),
            mode="full",
            reason=reason + ("；全量确认负权环仍在。" if bf["has_negative_cycle"]
                             else "；全量结果已恢复为有限距离。"),
            relax_count=prefix_counts + full.relax_count,
            full_relax_count=full.relax_count,
            edit=edit,
        )

    # ---- 查询 ----------------------------------------------------------

    def get_experiment(self, experiment_id: str) -> Experiment:
        return self.store.get(experiment_id)

    def get_version(self, experiment_id: str, number: int):
        return self.store.get_version(experiment_id, number)

    # ---- 序列化 --------------------------------------------------------

    def serialize_version(
        self, experiment: Experiment, record: VersionRecord
    ) -> dict:
        edit_payload = None
        if record.edit is not None:
            edit_payload = {
                "kind": record.edit.kind,
                "source": record.edit.source,
                "target": record.edit.target,
                "weight": record.edit.weight,
                "description": record.edit.describe(),
            }
        cycle = None
        if record.cycle is not None:
            cycle = dict(record.cycle)
        return {
            "experiment_id": experiment.id,
            "source": experiment.source,
            "version": record.version,
            "current_version": experiment.version,
            "mode": record.mode,
            "reason": record.reason,
            "graph": self._graph_payload(record.graph),
            "dist": dict(record.dist),
            "pred": dict(record.pred),
            "has_negative_cycle": record.has_negative_cycle,
            "cycle": cycle,
            "affected": list(record.affected),
            "reachable": sorted(record.graph.reachable_from(experiment.source)),
            "changed": [dict(item) for item in record.changed],
            "reprocessed": list(record.reprocessed),
            "invalidated": list(record.invalidated),
            "relax_count": record.relax_count,
            "full_relax_count": record.full_relax_count,
            "steps": record.steps,
            "edit": edit_payload,
        }

    def serialize_history(self, experiment: Experiment) -> dict:
        return {
            "experiment_id": experiment.id,
            "source": experiment.source,
            "current_version": experiment.version,
            "versions": [
                {
                    "version": r.version,
                    "mode": r.mode,
                    "has_negative_cycle": r.has_negative_cycle,
                    "changed_count": len(r.changed),
                    "relax_count": r.relax_count,
                    "full_relax_count": r.full_relax_count,
                    "edit": (
                        {
                            "kind": r.edit.kind,
                            "source": r.edit.source,
                            "target": r.edit.target,
                            "weight": r.edit.weight,
                            "description": r.edit.describe(),
                        }
                        if r.edit is not None else None
                    ),
                }
                for r in experiment.versions
            ],
        }
