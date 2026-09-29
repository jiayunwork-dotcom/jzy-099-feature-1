"""增量修复：在上一版（正确的）最短路径结果上只修受影响的一片。

算法（允许负权边；正确性的唯一前提是上一版结果本身正确）：

**调大 / 删除一条树上的边**
设改动的树边为 u→v（old_pred[v] == u）。

1. 沿前驱树求出 v 的**子树** S —— 只有经过 u→v 才能从源点到达的节点，
   正是「可能松动」的全部节点；子树以外的节点旧距离一定仍然最优，一帧都不动；
2. 作废 S：d、pred 清空为 ∞；
3. 扫描所有「从子树外进入子树内」的边（边界边），用子树外节点不变的最优
   距离给子树节点重新播种；
4. 对子树内做队列式松弛（Bellman–Ford 式，因此负权边也正确），直到队列空。

**调小一条边 / 新增一条边**
改动只会让距离变小：直接以改动边为种子做队列式松弛，改进沿出边向外扩散，
队列不再扩张到哪里就停在哪里。若松弛中前驱链闭合成环且环权为负，
说明此次编辑造出了一个源点可达的负权环，如实上报。

**不动的情况**
调大 / 删除一条不在最短路径树上的边、改动源点不可达区域的边、权重没变等：
没有任何节点被作废，松弛次数为 0，直接给出「纹丝不动」的说明帧。
"""

from __future__ import annotations

from typing import Any

from ..bellman_ford import run_bellman_ford
from ..graph import Graph
from ..negative_cycle import _build_forward_cycle, _pred_cycle  # 复用环校验
from ..negative_cycle import nodes_affected_by_cycle
from .edits import Edit
from .fullrun import full_bellman_ford

# 浮点比较容差：避免 0.1+0.2 这类舍入把本该不动的节点误判为被更新
EPS = 1e-9


# ---- 小工具 --------------------------------------------------------------

def _tree_subtree(pred: dict[str, str | None], root: str,
                  alive: set[str] | None = None) -> list[str]:
    """沿前驱树求 root 的子树（含 root），按「发现顺序」返回。

    pred[x] = p 表示边 p→x 在树上，故子树通过「谁的前驱是我」向下展开。
    ``alive`` 给定时（删除节点场景）剔除已不存在的节点。
    """
    children: dict[str, list[str]] = {}
    for node, parent in pred.items():
        if parent is not None:
            children.setdefault(parent, []).append(node)
    result: list[str] = []
    seen: set[str] = set()
    stack = [root]
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        if alive is None or u in alive:
            result.append(u)  # 根可能已被删除：跳过它，但仍向下找后代
        for child in children.get(u, []):
            if child not in seen:
                stack.append(child)
    return result


def _edge_map(graph: Graph) -> dict[tuple[str, str], Any]:
    return {(e.source, e.target): e for e in graph.edges}


def _frame(dist, pred, *, step_type: str, message: str,
           invalidated: list[str], reprocessed: list[str],
           active_edge: tuple[str, str] | None = None,
           current: str | None = None, relaxed: bool | None = None,
           cycle: dict | None = None, affected: list[str] | None = None,
           phase: str = "incremental") -> dict[str, Any]:
    return {
        "type": step_type,
        "message": message,
        "dist": dict(dist),
        "pred": dict(pred),
        "current_node": current,
        "active_edges": (
            [{"source": active_edge[0], "target": active_edge[1]}]
            if active_edge is not None else None
        ),
        "relaxed": relaxed,
        "invalidated": list(invalidated),
        "reprocessed": list(reprocessed),
        "cycle": cycle,
        "affected": affected or [],
        "phase": phase,
    }


def _fmt(x) -> str:
    if x is None:
        return "∞"
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def _improves(candidate: float, current: float | None) -> bool:
    """候选距离是否严格更优（带容差，防止舍入噪声）。"""
    return current is None or candidate < current - EPS


def _changed_entries(old_dist: dict[str, float | None],
                     new_dist: dict[str, float | None],
                     node_order: list[str]) -> list[dict[str, Any]]:
    """逐节点对比改动前 / 改动后的距离（None = ∞ 或 −∞，按图节点序）。"""
    changed: list[dict[str, Any]] = []
    for node in node_order:
        old = old_dist.get(node)
        new = new_dist.get(node)
        if old is None or new is None:
            differs = old is not new
        else:
            differs = abs(old - new) > EPS
        if differs:
            changed.append({"node": node, "old": old, "new": new})
    return changed


def _detect_cycle(graph: Graph, pred: dict[str, str | None],
                  start: str) -> tuple[list[str], list[dict], float] | None:
    """从刚被更新的 start 沿前驱链回溯，闭合成环且环权为负则返回环信息。"""
    pred_cycle = _pred_cycle(pred, start)
    if not pred_cycle:
        return None
    return _build_forward_cycle(graph, pred_cycle)


# ---- 主入口 --------------------------------------------------------------

def apply_incremental_repair(
    *,
    old_graph: Graph,
    new_graph: Graph,
    source: str,
    old_dist: dict[str, float | None],
    old_pred: dict[str, str | None],
    edit: Edit,
) -> dict[str, Any]:
    """在上一版结果上做一次增量修复，返回新结果 + 修复 trace + 计数。

    调用前提：``old_dist`` / ``old_pred`` 是 ``old_graph`` 上的正确 Bellman–Ford
    结果，且不含源点可达的负权环（含环状态由调用方直接走全量重算）。
    """
    old_edges = _edge_map(old_graph)
    new_edges = _edge_map(new_graph)

    # 1) 找出本次编辑真正改动的边（删 / 增 / 改权），区分树上 / 非树上
    increase_roots: list[str] = []  # 需要作废子树的根
    seed_edges: list = []            # 调小 / 新增的边（只会让距离变小）
    noop_reason: str | None = None

    def is_tree(edge) -> bool:
        return edge.target != source and old_pred.get(edge.target) == edge.source

    removed = [e for e in old_graph.edges if (e.source, e.target) not in new_edges]
    added = [e for e in new_graph.edges if (e.source, e.target) not in old_edges]

    # 删除节点：以被删节点为根作废整棵挂在它下面的子树
    if edit.kind == "delete_node":
        increase_roots.append(edit.node_id)  # type: ignore[arg-type]
        # 删除树边 (p→z) 与 (z→孩子) 的影响都已包含在 z 的子树里，不重复加根

    for e in removed:
        if edit.kind != "delete_node":
            if is_tree(e):
                increase_roots.append(e.target)
            # 删非树边：什么都不会变（下面统一给说明）

    for e in added:
        seed_edges.append(e)

    for key, new_e in new_edges.items():
        old_e = old_edges.get(key)
        if old_e is None:
            continue  # 新增边已在上面处理
        if new_e.weight == old_e.weight:
            if edit.kind == "set_weight":
                noop_reason = (
                    f"边 {old_e.source}→{old_e.target} 的权重仍是 "
                    f"{_fmt(old_e.weight)}，图没有发生任何变化。"
                )
            continue
        if new_e.weight < old_e.weight:
            seed_edges.append(new_e)
        elif is_tree(old_e):
            increase_roots.append(old_e.target)
        # 调大非树边：什么都不会变（下面统一给说明）

    # 工作副本（在新图的节点集上）
    dist: dict[str, float | None] = {v: old_dist.get(v) for v in new_graph.node_ids}
    pred: dict[str, str | None] = {v: old_pred.get(v) for v in new_graph.node_ids}
    steps: list[dict[str, Any]] = []
    edge_checks = 0

    # 去重保序的根
    increase_roots = list(dict.fromkeys(increase_roots))

    # ---- 情形一：作废子树 + 边界播种（调大 / 删除树边、删节点） --------
    if increase_roots:
        return _repair_increase(
            old_graph=old_graph, new_graph=new_graph, source=source,
            old_dist=old_dist, dist=dist, pred=pred,
            roots=increase_roots, edit=edit, steps=steps,
        )

    # ---- 情形二：调小 / 新增边，改进沿出边扩散 -------------------------
    if seed_edges:
        return _repair_decrease(
            new_graph=new_graph, source=source, old_dist=old_dist,
            dist=dist, pred=pred, seed_edges=seed_edges, edit=edit,
            steps=steps,
        )

    # ---- 情形三：纹丝不动 ----------------------------------------------
    if noop_reason is None:
        noop_reason = _explain_noop(edit, old_graph, old_dist, old_edges, new_edges)
    steps.append(_frame(
        dist, pred, step_type="noop", message=noop_reason,
        invalidated=[], reprocessed=[],
    ))
    result = _finalize(
        new_graph=new_graph, source=source, old_dist=old_dist,
        dist=dist, pred=pred, steps=steps, edge_checks=0,
        reprocessed=[], has_cycle=False, cycle_info=None, affected=[],
    )
    return result


def _explain_noop(edit: Edit, old_graph: Graph, old_dist, old_edges, new_edges) -> str:
    """根据编辑类型解释「为什么一个节点都不用动」。"""
    if edit.kind == "add_node":
        return (
            f"新节点 {edit.node_id} 目前没有任何入边，从源点不可达，距离为 ∞；"
            "其余节点的图没有变化，距离全部不变。"
        )
    u, v = edit.source, edit.target
    old_e = old_edges.get((u, v))
    new_e = new_edges.get((u, v))
    unreachable = old_dist.get(u) is None
    if edit.kind == "delete_edge":
        if unreachable:
            return (
                f"边 {u}→{v} 的起点 {u} 从源点不可达，它不在任何最短路径里；"
                "删除它不影响可达范围内的任何距离，无需重新处理节点。"
            )
        return (
            f"边 {u}→{v} 不在当前最短路径树上：没有节点的最短路径经过它，"
            "删除后所有距离保持不变，无需作废任何节点。"
        )
    if old_e is not None and new_e is not None and new_e.weight > old_e.weight:
        if unreachable:
            return (
                f"边 {u}→{v} 的起点 {u} 从源点不可达，调大它不影响可达范围，"
                "距离变化为空。"
            )
        return (
            f"边 {u}→{v}（{_fmt(old_e.weight)}→{_fmt(new_e.weight)}）不在当前"
            "最短路径树上：没有任何最短路径经过它，调大后所有距离纹丝不动，"
            "无需作废任何节点。"
        )
    return "本次编辑不影响任何最短路径，所有距离保持不变。"


# ---- 情形一：调大 / 删除树边 --------------------------------------------

def _repair_increase(*, old_graph, new_graph, source, old_dist,
                     dist, pred, roots, edit, steps) -> dict[str, Any]:
    alive = set(new_graph.node_ids)

    # 1) 求受影响子树的并集（在旧前驱树上）
    invalidated_set: list[str] = []
    seen: set[str] = set()
    for root in roots:
        for node in _tree_subtree(pred, root, alive=alive):
            if node not in seen:
                seen.add(node)
                invalidated_set.append(node)
    invalidated = [v for v in new_graph.node_ids if v in seen]
    # 仅用于说明：哪些树边被「撑断」
    root_names = "、".join(r for r in roots if r in alive or r == edit.node_id)

    steps.append(_frame(
        dist, pred, step_type="invalidate_plan",
        message=(
            f"{edit.describe()}。该边在当前最短路径树上，沿前驱树挂在它下面的"
            f"子树节点（{', '.join(invalidated) if invalidated else root_names}）"
            "的旧路径可能被撑断，先把这些节点的距离作废；子树以外的节点旧路径"
            "不经过这条边，距离一定仍然最优，一个都不碰。"
        ),
        invalidated=[], reprocessed=[],
    ))

    # 2) 作废子树
    for v in invalidated:
        dist[v] = None
        pred[v] = None
    steps.append(_frame(
        dist, pred, step_type="invalidate",
        message=(
            f"作废 {len(invalidated)} 个节点："
            f"{', '.join(invalidated) if invalidated else '（无）'}。"
            "接下来只扫描从子树外伸进子树内的边界边，用外部不变的距离重新播种。"
        ),
        invalidated=invalidated, reprocessed=list(invalidated),
    ))

    edge_checks = 0
    queue: list[str] = []
    in_queue: set[str] = set()

    def enqueue(node: str) -> None:
        if node not in in_queue:
            in_queue.add(node)
            queue.append(node)

    # 3) 边界边播种（按新图固定边序，保证可复现）
    boundary = [
        e for e in new_graph.edges
        if e.target in seen and e.source not in seen
    ]
    if not boundary:
        steps.append(_frame(
            dist, pred, step_type="boundary_scan",
            message=(
                "没有任何从子树外进入子树的边：子树节点全部与源点断开，"
                "它们的新距离为 ∞（不可达）。"
            ),
            invalidated=invalidated, reprocessed=list(invalidated),
        ))
    for e in boundary:
        edge_checks += 1
        u, v, w = e.source, e.target, e.weight
        du = dist[u]
        relaxed = False
        if du is not None:
            candidate = du + w
            if _improves(candidate, dist[v]):
                dist[v] = candidate
                pred[v] = u
                enqueue(v)
                relaxed = True
        if du is None:
            msg = (
                f"边界边 {u}→{v}（权 {_fmt(w)}）：{u} 不可达，无法经它进入子树。"
            )
        elif relaxed:
            msg = (
                f"边界边 {u}→{v}（权 {_fmt(w)}）：{_fmt(du)} + {_fmt(w)} "
                f"= {_fmt(dist[v])}，给作废的 {v} 重新播种，前驱暂记 {u}。"
            )
        else:
            msg = (
                f"边界边 {u}→{v}（权 {_fmt(w)}）：候选 {_fmt(du + w)} "
                f"不优于 {v} 当前的播种值 {_fmt(dist[v])}，不更新。"
            )
        steps.append(_frame(
            dist, pred, step_type="boundary", message=msg,
            active_edge=(u, v), current=u, relaxed=relaxed,
            invalidated=invalidated,
            reprocessed=_ordered_reprocessed(invalidated, in_queue),
        ))

    # 4) 子树内队列式松弛（负权边也正确）；只允许更新子树内节点。
    #    注意：调大树边也可能**造出**一个源点可达的负权环——修复路径可以先离开
    #    子树、再从一条负权边绕回子树（旧图中该边不在任何最短路上）。因此松弛中
    #    同样要沿前驱链检测闭合成环且环权为负的情况。
    cycle_info: dict | None = None
    affected: list[str] = []
    abort = False

    def dequeue() -> str:
        node = queue.pop(0)
        in_queue.discard(node)  # SPFA：节点出队后允许再次入队（被第二次改进时）
        return node

    while queue and not abort:
        u = dequeue()
        for e in new_graph.neighbors(u):
            edge_checks += 1
            v, w = e.target, e.weight
            du = dist[u]
            if du is None:
                continue
            candidate = du + w
            inside = v in seen
            relaxed = bool(inside and _improves(candidate, dist[v]))
            if relaxed:
                dist[v] = candidate
                pred[v] = u
            cycle_hit = _detect_cycle(new_graph, pred, v) if relaxed else None
            if cycle_hit is not None:
                cycle_nodes, cycle_edges, cycle_weight = cycle_hit
                cycle_info = {
                    "nodes": cycle_nodes,
                    "edges": cycle_edges,
                    "weight": cycle_weight,
                }
                affected = nodes_affected_by_cycle(new_graph, source, cycle_nodes)
                marked = set(_ordered_reprocessed(invalidated, in_queue))
                for node in affected:
                    dist[node] = None
                    if node not in marked:
                        marked.add(node)
                        in_queue.add(node)
                reprocessed_now = [
                    x for x in new_graph.node_ids if x in marked
                ]
                steps.append(_frame(
                    dist, pred, step_type="reprocess",
                    message=(
                        f"松弛 {u}→{v}（权 {_fmt(w)}）时前驱链闭合成环且环权为负"
                        f"（{_fmt(cycle_weight)}）：调大这条树边后，一条「离开子树再"
                        "绕回来」的路径构成了源点可达的负权环，环上及其下游距离标记 −∞。"
                    ),
                    active_edge=(u, v), current=u, relaxed=True,
                    invalidated=invalidated, reprocessed=reprocessed_now,
                    cycle=cycle_info, affected=affected,
                ))
                steps.append(_frame(
                    dist, pred, step_type="negative_cycle",
                    message=(
                        "本次编辑造出了源点可达的负权环："
                        f"{'→'.join(cycle_nodes + [cycle_nodes[0]])}，"
                        "环上及其可达节点距离为 −∞，实验进入「含负权环」状态。"
                    ),
                    invalidated=invalidated, reprocessed=reprocessed_now,
                    cycle=cycle_info, affected=affected,
                ))
                abort = True
                break
            if not inside:
                msg = (
                    f"检查出边 {u}→{v}（权 {_fmt(w)}）：{v} 在作废子树之外，"
                    "它的旧距离仍然最优，不允许改动。"
                )
            elif relaxed:
                msg = (
                    f"松弛 {u}→{v}（权 {_fmt(w)}）：{_fmt(du)} + {_fmt(w)} "
                    f"= {_fmt(candidate)}，更新 d[{v}]，前驱记为 {u}。"
                )
                enqueue(v)
            else:
                msg = (
                    f"检查出边 {u}→{v}（权 {_fmt(w)}）：{_fmt(du)} + {_fmt(w)} "
                    f"= {_fmt(candidate)} ≥ d[{v}]={_fmt(dist[v])}，不松弛。"
                )
            steps.append(_frame(
                dist, pred, step_type="reprocess", message=msg,
                active_edge=(u, v), current=u, relaxed=relaxed,
                invalidated=invalidated,
                reprocessed=_ordered_reprocessed(invalidated, in_queue),
            ))

    reprocessed_final = _ordered_reprocessed(invalidated, in_queue)
    if cycle_info is not None:
        # 受污染节点并入「被重新处理」集合
        present = set(reprocessed_final)
        for node in affected:
            if node not in present:
                present.add(node)
                reprocessed_final.append(node)
        steps.append(_frame(
            dist, pred, step_type="finished",
            message=(
                f"增量修复发现负权环：{len(affected)} 个节点距离标记为 −∞，"
                f"共检查 {edge_checks} 条边；下一版起将退回全量重算。"
            ),
            invalidated=invalidated, reprocessed=reprocessed_final,
            cycle=cycle_info, affected=affected,
        ))
        return _finalize(
            new_graph=new_graph, source=source, old_dist=old_dist,
            dist=dist, pred=pred, steps=steps, edge_checks=edge_checks,
            reprocessed=reprocessed_final,
            has_cycle=True, cycle_info=cycle_info, affected=affected,
        )

    steps.append(_frame(
        dist, pred, step_type="finished",
        message=(
            f"增量修复完成：只在 {len(invalidated)} 个节点的子树内重新计算，"
            f"共检查 {edge_checks} 条边；队列为空，子树内距离全部重新确定。"
        ),
        invalidated=invalidated,
        reprocessed=reprocessed_final,
    ))

    return _finalize(
        new_graph=new_graph, source=source, old_dist=old_dist,
        dist=dist, pred=pred, steps=steps, edge_checks=edge_checks,
        reprocessed=reprocessed_final,
        has_cycle=False, cycle_info=None, affected=[],
    )


def _ordered_reprocessed(invalidated: list[str],
                         enqueued: set[str]) -> list[str]:
    """作废过的节点（含最终仍不可达的）+ 真正进过修复队列的节点。"""
    result = list(invalidated)
    present = set(invalidated)
    for node in enqueued:
        if node not in present:
            present.add(node)
            result.append(node)
    return result


# ---- 情形二：调小 / 新增边 ----------------------------------------------

def _repair_decrease(*, new_graph, source, old_dist, dist, pred,
                     seed_edges, edit, steps) -> dict[str, Any]:
    steps.append(_frame(
        dist, pred, step_type="decrease_plan",
        message=(
            f"{edit.describe()}。边变轻（或新出现）只会让距离变小：以这条边为"
            "种子尝试松弛，若有改进就把更新节点入队，改进沿出边一层层向外扩散；"
            "松弛不再带来改进的地方就是扩散停止的边界。"
        ),
        invalidated=[], reprocessed=[],
    ))

    edge_checks = 0
    queue: list[str] = []
    in_queue: set[str] = set()
    enqueued_order: list[str] = []

    def enqueue(node: str) -> None:
        if node not in in_queue:
            in_queue.add(node)
            queue.append(node)
            enqueued_order.append(node)

    # 1) 种子边
    for e in seed_edges:
        edge_checks += 1
        u, v, w = e.source, e.target, e.weight
        du = dist[u]
        relaxed = False
        if du is not None:
            candidate = du + w
            if _improves(candidate, dist[v]):
                dist[v] = candidate
                pred[v] = u
                relaxed = True
        if du is None:
            msg = (
                f"种子边 {u}→{v}（权 {_fmt(w)}）：d[{u}] = ∞，"
                "源点经它到不了任何节点，扩散不会开始。"
            )
        elif relaxed:
            msg = (
                f"种子边 {u}→{v}（权 {_fmt(w)}）：{_fmt(du)} + {_fmt(w)} "
                f"= {_fmt(dist[v])} < 原 d[{v}]={_fmt(old_dist.get(v))}，"
                f"更新 d[{v}]，{v} 入队，改进将从它继续向外扩散。"
            )
        else:
            msg = (
                f"种子边 {u}→{v}（权 {_fmt(w)}）：{_fmt(du)} + {_fmt(w)} "
                f"= {_fmt(du + w)} ≥ d[{v}]={_fmt(dist[v])}，种子没有带来改进，"
                "扩散不开始。"
            )
        steps.append(_frame(
            dist, pred, step_type="seed", message=msg,
            active_edge=(u, v), current=u, relaxed=relaxed,
            invalidated=[], reprocessed=list(enqueued_order),
        ))
        if relaxed:
            enqueue(v)

    # 2) 队列扩散
    has_cycle = False
    cycle_info: dict | None = None
    affected: list[str] = []
    abort = False

    while queue and not abort:
        u = queue.pop(0)
        in_queue.discard(u)  # SPFA：出队后允许再次入队
        for e in new_graph.neighbors(u):
            edge_checks += 1
            v, w = e.target, e.weight
            du = dist[u]
            if du is None:
                continue
            candidate = du + w
            dv = dist[v]
            relaxed = _improves(candidate, dv)
            if relaxed:
                dist[v] = candidate
                pred[v] = u
            cycle_hit = _detect_cycle(new_graph, pred, v) if relaxed else None
            if cycle_hit is not None:
                cycle_nodes, cycle_edges, cycle_weight = cycle_hit
                has_cycle = True
                cycle_info = {
                    "nodes": cycle_nodes,
                    "edges": cycle_edges,
                    "weight": cycle_weight,
                }
                affected = nodes_affected_by_cycle(new_graph, source, cycle_nodes)
                already = set(enqueued_order)
                for node in affected:
                    dist[node] = None
                    # 环上及下游都在本次修复中被重新处理（距离被改为 −∞）
                    if node not in already:
                        already.add(node)
                        enqueued_order.append(node)
                steps.append(_frame(
                    dist, pred, step_type="reprocess",
                    message=(
                        f"松弛 {u}→{v}（权 {_fmt(w)}）时前驱链闭合成环且环权为负"
                        f"（{_fmt(cycle_weight)}）：编辑造出了一个源点可达的负权环，"
                        "停止增量修复，环上及其下游距离标记为 −∞。"
                    ),
                    active_edge=(u, v), current=u, relaxed=True,
                    invalidated=[], reprocessed=list(enqueued_order),
                    cycle=cycle_info, affected=affected,
                ))
                abort = True
                break
            if relaxed:
                msg = (
                    f"松弛 {u}→{v}（权 {_fmt(w)}）：{_fmt(du)} + {_fmt(w)} "
                    f"= {_fmt(candidate)} < 原 d[{v}]={_fmt(dv)}，更新 d[{v}]，"
                    f"前驱记为 {u}，{v} 入队继续向外扩散。"
                )
                enqueue(v)
            else:
                msg = (
                    f"检查出边 {u}→{v}（权 {_fmt(w)}）：{_fmt(du)} + {_fmt(w)} "
                    f"= {_fmt(candidate)} ≥ d[{v}]={_fmt(dv)}，改进到此为止，"
                    "不更新、不入队。"
                )
            steps.append(_frame(
                dist, pred, step_type="reprocess", message=msg,
                active_edge=(u, v), current=u, relaxed=relaxed,
                invalidated=[], reprocessed=list(enqueued_order),
            ))

    if has_cycle:
        steps.append(_frame(
            dist, pred, step_type="negative_cycle",
            message=(
                "存在源点可达的负权环："
                f"{'→'.join(cycle_info['nodes'] + [cycle_info['nodes'][0]])}，"
                "沿环每绕一圈总权继续减小；环上及其可达节点距离为 −∞，"
                "实验进入「含负权环」状态。"
            ),
            invalidated=[], reprocessed=list(enqueued_order),
            cycle=cycle_info, affected=affected,
        ))
    else:
        steps.append(_frame(
            dist, pred, step_type="finished",
            message=(
                f"增量修复完成：改进只扩散到了 {len(enqueued_order)} 个节点，"
                f"共检查 {edge_checks} 条边；队列为空，扩散边界之外的节点从未被碰过。"
            ),
            invalidated=[], reprocessed=list(enqueued_order),
        ))

    return _finalize(
        new_graph=new_graph, source=source, old_dist=old_dist,
        dist=dist, pred=pred, steps=steps, edge_checks=edge_checks,
        reprocessed=list(enqueued_order),
        has_cycle=has_cycle, cycle_info=cycle_info, affected=affected,
    )


# ---- 收尾：变化清单 + 全量对照计数 --------------------------------------

def _finalize(*, new_graph, source, old_dist, dist, pred, steps,
              edge_checks, reprocessed, has_cycle, cycle_info, affected) -> dict[str, Any]:
    changed = _changed_entries(old_dist, dist, new_graph.node_ids)
    # 全量对照：同一张图从头跑一遍 Bellman–Ford 实际检查多少条边
    full_info = full_bellman_ford(new_graph, source)
    return {
        "mode": "incremental",
        "reason": None,
        "dist": dist,
        "pred": pred,
        "has_negative_cycle": has_cycle,
        "cycle": cycle_info,
        "affected": affected,
        "reachable": sorted(new_graph.reachable_from(source)),
        "changed": changed,
        "reprocessed": reprocessed,
        "steps": steps,
        "incremental_relax_count": edge_checks,
        "full_relax_count": full_info["edge_checks"],
    }


def apply_full_recompute(*, new_graph: Graph, source: str,
                         old_dist: dict[str, float | None],
                         reason: str) -> dict[str, Any]:
    """整图从头跑 Bellman–Ford（打破负权环等情形），并标明走的是全量。

    trace 直接复用教学版 Bellman–Ford 的逐轮演示；每帧补上动态实验需要的
    ``invalidated`` / ``reprocessed`` / ``phase`` 字段。
    """
    info = full_bellman_ford(new_graph, source)
    taught = run_bellman_ford(new_graph, source)
    all_nodes = list(new_graph.node_ids)

    steps: list[dict[str, Any]] = []
    for step in taught["steps"]:
        frame = dict(step)
        frame["phase"] = "full"
        frame["invalidated"] = []
        frame["reprocessed"] = list(all_nodes)
        steps.append(frame)

    changed = _changed_entries(old_dist, info["dist"], all_nodes)
    return {
        "mode": "full",
        "reason": reason,
        "dist": info["dist"],
        "pred": info["pred"],
        "has_negative_cycle": info["has_negative_cycle"],
        "cycle": info["cycle"],
        "affected": info["affected"],
        "reachable": info["reachable"],
        "changed": changed,
        "reprocessed": list(all_nodes),
        "steps": steps,
        "incremental_relax_count": info["edge_checks"],
        "full_relax_count": info["edge_checks"],
    }


def initial_result(graph: Graph, source: str) -> dict[str, Any]:
    """版本 0 的完整初始结果（全量 Bellman–Ford）。

    trace 复用教学版逐轮演示，帧上标注 phase=full，前端可与修复演示共用播放器。
    """
    info = full_bellman_ford(graph, source)
    taught = run_bellman_ford(graph, source)
    all_nodes = list(graph.node_ids)
    steps = []
    for step in taught["steps"]:
        frame = dict(step)
        frame["phase"] = "full"
        frame["invalidated"] = []
        frame["reprocessed"] = list(all_nodes)
        steps.append(frame)
    return {
        "mode": "full",
        "reason": "初始版本：对当前图从头运行一遍 Bellman–Ford。",
        "dist": info["dist"],
        "pred": info["pred"],
        "has_negative_cycle": info["has_negative_cycle"],
        "cycle": info["cycle"],
        "affected": info["affected"],
        "reachable": info["reachable"],
        "changed": [],
        "reprocessed": list(all_nodes),
        "steps": steps,
        "incremental_relax_count": info["edge_checks"],
        "full_relax_count": info["edge_checks"],
    }
