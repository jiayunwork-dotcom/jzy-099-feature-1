"""在上一版 Bellman–Ford 结果之上做**增量修复**（允许负权边）。

一次边编辑只会通过三种方式影响最短路，分别对应本模块的三条修复路径：

1. 边权调小 / 新增边：只可能让距离**变小**。从这条边出发，若它能立刻
   松弛成功，就把改进沿出边一层层向外扩散（波次传播，等价于只在受影响
   节点上跑 Bellman–Ford）。改进沿一条长度为 n 的游走仍能传播，说明
   出现了源点可达的负权环——交由上层用全量结果给出 −∞ 标注。
2. 树边（当前前驱树所用的边）调大 / 删除：只有挂在该边终点下面的那棵
   **前驱子树**会松动。先把整棵子树的距离/前驱作废，再用从子树外射入
   子树的「边界边」作为候选入口，在子树内部重新松弛。子树以外的节点
   距离有旧边权单调性保证，一个都不会变。
3. 非树边调大 / 删除、或改动落在源点不可达区域：旧距离仍然全部合法，
   距离变化与被重处理节点集合都为空。

``relax_count`` 按「本次修复实际检查过的边」计，不论该次松弛是否成功。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..dijkstra import fmt_num
from ..graph import Graph
from .edits import EdgeEdit


@dataclass
class RepairResult:
    dist: dict[str, float | None]
    pred: dict[str, str | None]
    steps: list[dict]
    relax_count: int
    reprocessed: list[str]
    invalidated: list[str]
    # 波次传播中检测到新产生的源点可达负权环时为 True；
    # 最终的环定位 / −∞ 标注由上层用全量 Bellman–Ford 权威给出
    cycle_detected: bool = False
    note: str = ""


# ---- 帧（与 /api/run 的 Step 结构对齐，另加 invalidated 字段） ---------

def _frame(dist, pred, *, step_type, message, active_edges=None,
           current_node=None, relaxed=None, queue=None, pass_index=None,
           invalidated=None) -> dict:
    return {
        "type": step_type,
        "message": message,
        "dist": dict(dist),
        "pred": dict(pred),
        "settled": [],
        "current_node": current_node,
        "active_edges": active_edges,
        "queue": queue or [],
        "pass": pass_index,
        "relaxed": relaxed,
        "cycle": None,
        "affected": [],
        "invalidated": invalidated or [],
    }


def _queue_view(nodes, dist):
    return sorted(
        ([v, dist[v]] for v in nodes if dist[v] is not None),
        key=lambda item: (item[1], item[0]),
    )


def _pred_subtree(root: str, pred: dict[str, str | None]) -> list[str]:
    """前驱树中 root 下面的整棵子树（含 root），按前驱关系展开。"""
    children: dict[str, list[str]] = {}
    for v, p in pred.items():
        if p is not None:
            children.setdefault(p, []).append(v)
    out: list[str] = []
    stack = [root]
    while stack:
        u = stack.pop()
        out.append(u)
        stack.extend(children.get(u, []))
    return out


def _is_tree_edge(u: str, v: str, old_dist, old_pred) -> bool:
    """该边是否为当前最短路径前驱树所用的边（且终点有有限距离）。"""
    return old_dist.get(v) is not None and old_pred.get(v) == u


# =========================================================================
# 入口
# =========================================================================

def incremental_repair(
    graph: Graph,
    source: str,
    old_dist: dict[str, float | None],
    old_pred: dict[str, str | None],
    edit: EdgeEdit,
    old_weight: float | None,
) -> RepairResult:
    dist = dict(old_dist)
    pred = dict(old_pred)
    active = [{"source": edit.source, "target": edit.target}]
    steps: list[dict] = [
        _frame(
            dist, pred, step_type="repair_edit", active_edges=active,
            message=f"本次编辑：{edit.describe()}。在上一版距离表上做局部增量修复。",
        )
    ]

    trivial = (
        edit.kind == EdgeEdit.UPDATE
        and old_weight is not None
        and edit.weight == old_weight
    )
    if trivial:
        steps.append(_frame(
            dist, pred, step_type="repair_noop", active_edges=active,
            message=(
                f"边 {edit.source}→{edit.target} 的权重仍为 {fmt_num(old_weight)}，"
                "图没有实质变化，所有距离保持不变，无需重新处理任何节点。"
            ),
        ))
        return _finish(dist, pred, steps, relax_count=0, reprocessed=[],
                       invalidated=[], note="权重未变化，空修复")

    increasing = edit.kind == EdgeEdit.DELETE or (
        edit.kind == EdgeEdit.UPDATE and edit.weight > old_weight  # type: ignore[operator]
    )

    if increasing:
        if not _is_tree_edge(edit.source, edit.target, old_dist, old_pred):
            return _noop_untouched(
                graph, dist, pred, steps, active, edit, old_dist,
                reason="non_tree",
            )
        if old_dist[edit.source] is None:
            return _noop_untouched(
                graph, dist, pred, steps, active, edit, old_dist,
                reason="unreachable",
            )
        return _repair_increase(
            graph, source, dist, pred, steps, edit,
        )

    return _repair_decrease(graph, source, dist, pred, steps, edit)


# =========================================================================
# 情形一：调大树边 / 删除树边 —— 作废子树 + 边界重灌
# =========================================================================

def _repair_increase(graph, source, dist, pred, steps, edit: EdgeEdit) -> RepairResult:
    u, v = edit.source, edit.target
    subtree = _pred_subtree(v, pred)
    subtree_set = set(subtree)
    ordered = [x for x in graph.node_ids if x in subtree_set]

    steps.append(_frame(
        dist, pred, step_type="repair_invalidate_plan",
        active_edges=[{"source": u, "target": v}],
        invalidated=ordered,
        message=(
            f"边 {u}→{v} 是当前最短路径前驱树上的边，它一变长，旧的 d[{v}] 不再可靠。"
            f"沿前驱树向下，只有挂在 {v} 下面的子树 {{ {', '.join(ordered)} }} "
            "可能被波及；子树以外的节点有旧边权单调性保证，距离纹丝不动。"
            "下面先把这棵子树的距离作废。"
        ),
    ))

    for x in ordered:
        dist[x] = None
        pred[x] = None

    steps.append(_frame(
        dist, pred, step_type="repair_invalidated",
        active_edges=[{"source": u, "target": v}],
        invalidated=ordered,
        message=(
            f"子树 {', '.join(ordered)} 的距离已作废（∞，待重新计算），"
            "其余节点距离原样保留。接下来只从「子树外 → 子树内」的边界边"
            "重新灌入候选距离。"
        ),
    ))

    relax_count = 0
    queue: deque[str] = deque()
    in_queue: set[str] = set()

    def enqueue(node: str) -> None:
        if node not in in_queue:
            in_queue.add(node)
            queue.append(node)

    # ---- 边界边：按图的固定边序检查所有 子树外 → 子树内 的边 ----------
    boundary = [
        e for e in graph.edges
        if e.target in subtree_set and e.source not in subtree_set
    ]
    for edge in boundary:
        relax_count += 1
        active = [{"source": edge.source, "target": edge.target}]
        du = dist[edge.source]
        if du is None:
            steps.append(_frame(
                dist, pred, step_type="repair_boundary", active_edges=active,
                current_node=edge.source, relaxed=False, invalidated=ordered,
                queue=_queue_view(in_queue, dist),
                message=(
                    f"边界边 {edge.source}→{edge.target}（权 {fmt_num(edge.weight)}）："
                    f"d[{edge.source}] = ∞，无法从子树外提供候选距离。"
                ),
            ))
            continue
        candidate = du + edge.weight
        dv = dist[edge.target]
        if dv is None or candidate < dv:
            old_txt = "∞（已作废）" if dv is None else fmt_num(dv)
            dist[edge.target] = candidate
            pred[edge.target] = edge.source
            enqueue(edge.target)
            steps.append(_frame(
                dist, pred, step_type="repair_boundary", active_edges=active,
                current_node=edge.source, relaxed=True, invalidated=ordered,
                queue=_queue_view(in_queue, dist),
                message=(
                    f"边界边 {edge.source}→{edge.target}（权 {fmt_num(edge.weight)}）："
                    f"{fmt_num(du)} + {fmt_num(edge.weight)} = {fmt_num(candidate)} "
                    f"< {old_txt}，从子树外重新灌入 d[{edge.target}]，"
                    f"前驱记为 {edge.source}，加入待重处理队列。"
                ),
            ))
        else:
            steps.append(_frame(
                dist, pred, step_type="repair_boundary", active_edges=active,
                current_node=edge.source, relaxed=False, invalidated=ordered,
                queue=_queue_view(in_queue, dist),
                message=(
                    f"边界边 {edge.source}→{edge.target}（权 {fmt_num(edge.weight)}）："
                    f"{fmt_num(du)} + {fmt_num(edge.weight)} = {fmt_num(candidate)} "
                    f"≥ d[{edge.target}]={fmt_num(dv)}，不采用。"
                ),
            ))

    # ---- 子树内部重新松弛（SPFA 式 FIFO；增/删边不会制造负权环） ------
    while queue:
        x = queue.popleft()
        in_queue.discard(x)
        if dist[x] is None:
            continue
        for edge in graph.neighbors(x):
            if edge.target not in subtree_set:
                # 子树外节点的距离已由旧结果给出且只会变大，不可能被改进，
                # 因此这些边根本不需要检查 —— 这正是「只修这一片」的边界。
                continue
            relax_count += 1
            active = [{"source": edge.source, "target": edge.target}]
            candidate = dist[x] + edge.weight
            dv = dist[edge.target]
            if dv is None or candidate < dv:
                old_txt = "∞" if dv is None else fmt_num(dv)
                dist[edge.target] = candidate
                pred[edge.target] = x
                enqueue(edge.target)
                relaxed = True
                message = (
                    f"子树内松弛 {edge.source}→{edge.target}"
                    f"（权 {fmt_num(edge.weight)}）："
                    f"{fmt_num(dist[x])} + {fmt_num(edge.weight)} "
                    f"= {fmt_num(candidate)} < {old_txt}，"
                    f"更新 d[{edge.target}]，继续向外扩散。"
                )
            else:
                relaxed = False
                message = (
                    f"子树内检查 {edge.source}→{edge.target}"
                    f"（权 {fmt_num(edge.weight)}）："
                    f"{fmt_num(dist[x])} + {fmt_num(edge.weight)} "
                    f"= {fmt_num(candidate)} ≥ d[{edge.target}]={fmt_num(dv)}，"
                    "不松弛。"
                )
            steps.append(_frame(
                dist, pred, step_type="repair_relax", active_edges=active,
                current_node=x, relaxed=relaxed, invalidated=ordered,
                queue=_queue_view(in_queue, dist),
                message=message,
            ))

    still_none = [x for x in ordered if dist[x] is None]
    tail = (
        "子树内已无可松弛的边，修复在子树边界处停下。"
        + (f" 节点 {', '.join(still_none)} 从源点不再可达，距离为 ∞。"
           if still_none else "")
        + f" 本次增量修复共检查 {relax_count} 条边，"
          "子树以外的节点自始至终没有被碰到。"
    )
    steps.append(_frame(
        dist, pred, step_type="repair_finished", invalidated=ordered,
        message=tail,
    ))
    return RepairResult(
        dist=dist, pred=pred, steps=steps, relax_count=relax_count,
        reprocessed=ordered, invalidated=ordered,
        note="树边调大/删除：作废前驱子树后从边界边重新松弛",
    )


# =========================================================================
# 情形二：边权调小 / 新增边 —— 改进沿出边波次扩散
# =========================================================================

def _repair_decrease(graph, source, dist, pred, steps, edit: EdgeEdit) -> RepairResult:
    u, v, w_new = edit.source, edit.target, edit.weight
    n = len(graph)
    relax_count = 0
    reprocessed: list[str] = []
    seen_reprocessed: set[str] = set()

    def remember(node: str) -> None:
        if node not in seen_reprocessed:
            seen_reprocessed.add(node)
            reprocessed.append(node)

    active = [{"source": u, "target": v}]

    # 起点从源点不可达：无论边怎么调小 / 新增，都不可能影响任何
    # 源点可达的距离 —— 连触发边都不必松弛，直接空修复（0 次检查）。
    if dist[u] is None:
        steps.append(_frame(
            dist, pred, step_type="repair_noop", active_edges=active,
            current_node=u, relaxed=False,
            message=(
                f"边 {u}→{v}（新权 {fmt_num(w_new)}）的起点 {u} 从源点不可达，"
                f"改动发生在不可达区域里，源点可达范围内的距离表纹丝不动，"
                "没有节点需要重新处理。"
            ),
        ))
        steps.append(_frame(
            dist, pred, step_type="repair_finished",
            message="修复结束：不可达区域内的改动不影响可达距离，本次检查 0 条边。",
        ))
        return RepairResult(
            dist=dist, pred=pred, steps=steps, relax_count=0,
            reprocessed=[], invalidated=[],
            note="改动落在源点不可达区域，距离不变",
        )

    # 先检查触发编辑本身这一条边
    relax_count += 1
    level: dict[str, int] = {}
    frontier: list[str] = []
    candidate = dist[u] + w_new
    dv = dist[v]
    if not (dv is None or candidate < dv):
        steps.append(_frame(
            dist, pred, step_type="repair_relax", active_edges=active,
            current_node=u, relaxed=False,
            message=(
                f"检查被改动的边 {u}→{v}（权 {fmt_num(w_new)}）："
                f"{fmt_num(dist[u])} + {fmt_num(w_new)} = {fmt_num(candidate)} "
                f"≥ d[{v}]={fmt_num(dv)}，它不在任何更短路径上，"
                "距离一个都不会变，无需继续。"
            ),
        ))
        steps.append(_frame(
            dist, pred, step_type="repair_finished",
            message=f"修复结束：本次只检查了 {relax_count} 条边，距离表不变。",
        ))
        return RepairResult(
            dist=dist, pred=pred, steps=steps, relax_count=relax_count,
            reprocessed=[], invalidated=[],
            note="改动的边不在最短路径树上，且不能松弛，距离不变",
        )

    old_txt = "∞" if dv is None else fmt_num(dv)
    dist[v] = candidate
    pred[v] = u
    remember(v)
    level[v] = 1
    frontier = [v]
    steps.append(_frame(
        dist, pred, step_type="repair_relax", active_edges=active,
        current_node=u, relaxed=True, queue=_queue_view(frontier, dist),
        message=(
            f"松弛被改动的边 {u}→{v}（权 {fmt_num(w_new)}）："
            f"{fmt_num(dist[u])} + {fmt_num(w_new)} = {fmt_num(candidate)} "
            f"< {old_txt}，更新 d[{v}]。改进将沿它的出边一层层向外扩散。"
        ),
    ))

    # 沿出边按波次传播：第 ℓ 波 = 改进沿 ℓ 条边到达的节点。
    # 简单路径最多 n−1 条边；若改进还能沿第 n 条边继续传播，
    # 则存在源点可达的负权环。
    wave = 1
    cycle_found = False
    while frontier and not cycle_found:
        steps.append(_frame(
            dist, pred, step_type="repair_wave_start", pass_index=wave,
            queue=_queue_view(frontier, dist),
            message=(
                f"—— 第 {wave} 层扩散：处理上一层被更新的节点 "
                f"{ {x for x in frontier} }，只检查它们的出边 ——"
            ),
        ))
        next_frontier_set: set[str] = set()
        next_frontier: list[str] = []
        for x in frontier:
            for edge in graph.neighbors(x):
                relax_count += 1
                active = [{"source": edge.source, "target": edge.target}]
                cand = dist[x] + edge.weight
                cur = dist[edge.target]
                if cur is not None and not (cand < cur):
                    steps.append(_frame(
                        dist, pred, step_type="repair_relax",
                        active_edges=active, current_node=x, relaxed=False,
                        pass_index=wave, queue=_queue_view(frontier, dist),
                        message=(
                            f"检查边 {edge.source}→{edge.target}"
                            f"（权 {fmt_num(edge.weight)}）："
                            f"{fmt_num(dist[x])} + {fmt_num(edge.weight)} "
                            f"= {fmt_num(cand)} ≥ d[{edge.target}]={fmt_num(cur)}，"
                            "改进在这里停住。"
                        ),
                    ))
                    continue
                old_txt = "∞" if cur is None else fmt_num(cur)
                if wave + 1 > n - 1:
                    # 改进沿 n 条边的游走仍在继续 —— 必有可达负权环
                    cycle_found = True
                    steps.append(_frame(
                        dist, pred, step_type="repair_relax",
                        active_edges=active, current_node=x, relaxed=True,
                        pass_index=wave, queue=_queue_view(frontier, dist),
                        message=(
                            f"边 {edge.source}→{edge.target}"
                            f"（权 {fmt_num(edge.weight)}）仍能把距离从 {old_txt} "
                            f"降到 {fmt_num(cand)}：改进已经传播了 {n} 条边，"
                            "超过任何简单路径的长度，说明出现了源点可达的"
                            "负权环，增量修复停止，交由全量 Bellman–Ford "
                            "定位环并标注 −∞。"
                        ),
                    ))
                    break
                dist[edge.target] = cand
                pred[edge.target] = x
                remember(edge.target)
                level[edge.target] = wave + 1
                if edge.target not in next_frontier_set:
                    next_frontier_set.add(edge.target)
                    next_frontier.append(edge.target)
                steps.append(_frame(
                    dist, pred, step_type="repair_relax",
                    active_edges=active, current_node=x, relaxed=True,
                    pass_index=wave,
                    queue=_queue_view(
                        list(next_frontier_set) + [z for z in frontier if z != x],
                        dist,
                    ),
                    message=(
                        f"松弛边 {edge.source}→{edge.target}"
                        f"（权 {fmt_num(edge.weight)}）："
                        f"{fmt_num(dist[x])} + {fmt_num(edge.weight)} "
                        f"= {fmt_num(cand)} < {old_txt}，"
                        f"更新 d[{edge.target}]，改进继续向外扩散一层。"
                    ),
                ))
            if cycle_found:
                break
        frontier = next_frontier
        wave += 1

    if cycle_found:
        steps.append(_frame(
            dist, pred, step_type="repair_negative_cycle",
            pass_index=wave,
            message=(
                "检测到本次编辑在源点可达范围内制造了负权环。"
                "下面改用全量 Bellman–Ford 给出权威结果：环上及其下游节点"
                "距离标注为 −∞。"
            ),
        ))
        return RepairResult(
            dist=dist, pred=pred, steps=steps, relax_count=relax_count,
            reprocessed=reprocessed, invalidated=[], cycle_detected=True,
            note="增量传播检测到新产生的源点可达负权环",
        )

    # ---- 收敛后的负环安全校验：候选区域上的受限 Bellman–Ford -----------
    # 波次传播只跟随「新被更新的节点」，会漏掉沿「已处理节点」绕回的
    # 负环。为在负权下保证正确，这里把「修复」与「负环判定」分开：修复
    # 结果完全来自上面的局部传播；负环有无则用一遍**受限 Bellman–Ford**
    # 判定——取重处理节点的「前驱闭包 ∪ 出边可达闭包」为候选集（新环
    # 必经被改动的边，必与重处理区域相交，故整个环都在这个闭包里），
    # 从源点 0 重新初始化，只在候选起点的出边上做 n−1 轮松弛，再做一轮
    # 检测轮。检测轮仍能松弛即坐实源点可达负权环。这是安全校验而非修复
    # 动作，**不计入本次修复松弛数**；真正局部的编辑（如只动链尾）候选
    # 集只有 1 个源点，校验规模也是 O(1)。
    check_sources: set[str] = set(seen_reprocessed)
    for edge in graph.edges:
        if edge.target in seen_reprocessed:
            check_sources.add(edge.source)
    stack = list(seen_reprocessed)
    while stack:
        x = stack.pop()
        for edge in graph.neighbors(x):
            if edge.target not in check_sources:
                check_sources.add(edge.target)
                stack.append(edge.target)
    check_edges = [e for e in graph.edges if e.source in check_sources]
    steps.append(_frame(
        dist, pred, step_type="repair_detect_start", pass_index=wave,
        message=(
            "正向扩散已结束。负环安全校验：取重处理节点的前驱/出边闭包"
            f"（{len(check_sources)} 个候选节点），从源点 {source} = 0 "
            "重新初始化，在候选出边上按 Bellman–Ford 的方式做 n−1 轮"
            "松弛 + 一轮检测轮（该校验不计入本次修复松弛数）。"
        ),
    ))
    verify_dist: dict[str, float | None] = {x: None for x in graph.node_ids}
    verify_dist[source] = 0.0
    for _ in range(n - 1):
        for edge in check_edges:
            du = verify_dist[edge.source]
            if du is None:
                continue
            cand = du + edge.weight
            cur = verify_dist[edge.target]
            if cur is None or cand < cur:
                verify_dist[edge.target] = cand

    cycle_edge = None
    for edge in check_edges:
        du = verify_dist[edge.source]
        if du is None:
            continue
        cand = du + edge.weight
        cur = verify_dist[edge.target]
        if cur is None or cand < cur:
            cycle_edge = (edge.source, edge.target)
            break

    if cycle_edge is not None:
        steps.append(_frame(
            dist, pred, step_type="repair_detect",
            active_edges=[{"source": cycle_edge[0], "target": cycle_edge[1]}],
            current_node=cycle_edge[0], relaxed=True, pass_index=wave,
            message=(
                f"安全校验的检测轮中，边 {cycle_edge[0]}→{cycle_edge[1]} "
                "仍能松弛，坐实候选区域内存在源点可达的负权环。"
                "增量修复停止，交由全量 Bellman–Ford 定位环、标注 "
                "−∞ 与受影响节点。"
            ),
        ))
        steps.append(_frame(
            dist, pred, step_type="repair_negative_cycle",
            pass_index=wave,
            message=(
                "确认本次编辑制造了源点可达的负权环。"
                "下面改用全量 Bellman–Ford 给出权威结果。"
            ),
        ))
        return RepairResult(
            dist=dist, pred=pred, steps=steps, relax_count=relax_count,
            reprocessed=reprocessed, invalidated=[], cycle_detected=True,
            note="增量修复后的受限 Bellman–Ford 安全校验发现源点可达负权环",
        )

    changed_preview = [x for x in graph.node_ids if level.get(x) is not None]
    steps.append(_frame(
        dist, pred, step_type="repair_finished", pass_index=wave - 1,
        message=(
            f"下一层没有任何边能继续松弛，改进在扩散边界处停下。"
            f"距离被更新的节点：{ {x for x in changed_preview} }；"
            f"本次增量修复共检查 {relax_count} 条边，"
            "其余节点自始至终没有被碰到。"
        ),
    ))
    return RepairResult(
        dist=dist, pred=pred, steps=steps, relax_count=relax_count,
        reprocessed=reprocessed, invalidated=[],
        note="边权调小/新增边：改进沿出边波次扩散",
    )


# =========================================================================
# 情形三：不会影响任何距离的编辑
# =========================================================================

def _noop_untouched(graph, dist, pred, steps, active, edit: EdgeEdit,
                    old_dist, *, reason: str) -> RepairResult:
    if reason == "unreachable":
        message = (
            f"边 {edit.source}→{edit.target} 的起点 {edit.source} 从源点不可达，"
            "改动发生在不可达区域里，源点可达范围内的距离表纹丝不动，"
            "没有节点需要重新处理。"
        )
    else:
        message = (
            f"边 {edit.source}→{edit.target} 不在当前最短路径前驱树上"
            "（没有最短路径经过它）。把它调大或删除只会让「本来就没走它」"
            "的路径更不划算，旧距离仍然全部合法，距离变化与被重处理节点"
            "集合都为空。"
        )
    steps.append(_frame(
        dist, pred, step_type="repair_noop", active_edges=active,
        message=message,
    ))
    return RepairResult(
        dist=dist, pred=pred, steps=steps, relax_count=0,
        reprocessed=[], invalidated=[],
        note="非树边调大/删除（或不可达区域内的改动），距离不变",
    )


def _finish(dist, pred, steps, *, relax_count, reprocessed, invalidated,
            note) -> RepairResult:
    return RepairResult(
        dist=dist, pred=pred, steps=steps, relax_count=relax_count,
        reprocessed=reprocessed, invalidated=invalidated, note=note,
    )
