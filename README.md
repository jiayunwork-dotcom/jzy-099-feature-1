# 最短路径算法教学看板（Shortest Path Teaching Board）

一个前后端一体的 Web 应用，用于在**带权有向图**上把「单源最短路径」讲透：

- **Dijkstra**：只适用于非负权图，基于优先队列逐个「确定」节点最短距离。
- **Bellman–Ford**：允许负权边，按轮次松弛所有边，并能识别从源点可达的**负权环**。

两种算法在**同一张图**上逐步演示松弛过程，方便对照执行差异与适用边界。
全部算法与正确性校验都在后端（Python 3.12 + FastAPI）完成，前端（React + TypeScript + Vite）
只负责渲染逐步返回的中间状态快照，不自行重算。

此外提供**动态实验**模式：对当前图与选定源点开一个实验后，每次改边（调权 /
加边 / 删除）都作为一次带版本号的编辑提交，后端在上一版结果上做**增量修复**
（负权下同样保证正确），返回新旧距离对比、被重新处理的节点、逐步修复快照，
以及「本次修复检查的边数 / 同图从头跑 Bellman–Ford 的边数」并排对比。

## 目录结构

```
backend/                # FastAPI 后端（算法全部在这里）
  app/
    main.py             # HTTP 接口 / 静态资源挂载
    models.py           # 静态 /api/run 的请求/响应 Pydantic 模型
    graph.py            # 带权有向图模型 + 输入校验
    dijkstra.py         # Dijkstra（含逐步 trace、优先队列快照）
    bellman_ford.py     # Bellman–Ford（含逐轮 trace）
    negative_cycle.py   # 负权环检测（前驱链回溯成环）
    path.py             # 最短路径回溯
    presets.py          # 内置经典示例图
    dynamic/            # 动态实验层（与静态算法模块解耦）
      edits.py          # 边编辑（调权/加边/删边）校验与纯函数应用
      reference.py      # 全量 Bellman–Ford 权威结果与松弛计数
      repair.py         # 增量修复（子树作废 / 改进波次扩散 / 负环校验）
      experiment.py     # 实验与版本记录数据模型
      store.py          # 内存实验表（数量上限 + LRU 淘汰）
      service.py        # 开实验 / 提交编辑 / 取版本的编排
      routes.py         # /api/experiments HTTP 路由
      api_models.py     # 动态实验的请求/响应模型
  tests/                # pytest 自动化测试
    dynamic/            # 动态实验测试（含 7 条验收主线）
frontend/               # React + TS + Vite 前端
  src/components/
    GraphCanvas.tsx     # 图编辑画布（SVG）
    AdjacencyMatrix.tsx # 邻接矩阵（与图实时双向同步）
    DistanceTable.tsx   # 距离表（静态 + 动态修复两态）
    DemoControls.tsx    # 静态模式运行/暂停/单步/变速控制
    ExperimentPanel.tsx # 动态实验状态条（版本/模式/松弛数对比）
    VersionList.tsx     # 实验版本历史列表（回看任一版）
Dockerfile              # 多阶段构建，起一个容器同时提供页面与接口
docker-compose.yml
```

## 用 Docker 一次构建运行

```bash
docker compose up --build
# 打开 http://localhost:8000
```

## 本地开发

后端：

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

前端（Vite 已把 /api 代理到 8000）：

```bash
cd frontend
npm install
npm run dev
# 打开 http://localhost:5173
```

## 测试

```bash
cd backend
pip install -r requirements.txt
pytest
```

测试钉住两条主线：无负权时两种算法距离完全一致（含 30 张随机非负图参数化用例）；
存在源点可达的负权环时必须如实上报（环定位、环权为负、受污染节点距离不得为有限值）。
此外覆盖：源点到自身为 0、不可达为 ∞、边权调大距离不减小、前驱链合法、
Dijkstra 遇负权默认 400 拒绝（放行时必带 warning）、路径回溯与各类非法输入。

`tests/dynamic/` 覆盖动态实验的 7 条验收主线：

1. 5 组随机图（含负权边、不可达节点）上各做 205 次随机编辑，每次增量结果都与
   同图全量 Bellman–Ford 完全一致、前驱链合法、负环标注一致；
2. 调大非树边 / 改动不可达区域边：距离变化与被重处理集合都为空、松弛数为 0；
3. 调大树边：被重处理节点全部落在对应前驱子树内，子树外距离不变（40 组参数化）；
4. 30 节点逆序单链调最后一条边：只重处理链尾、距离 29→30、松弛数 ≤ 全量 1/10；
5. 版本号落后的编辑返回 409 且实验状态不变；
6. 制造再打破源点可达负权环：环/距离两次都正确，打破那步标明走全量并写明原因；
7. 按版本号取回的图与距离表与当时返回一致。

另含 LRU 淘汰、实验/版本不存在 404、非法编辑（不存在节点、加已存在边、删不存在边）
400 且实验不变、松弛计数口径等测试。

## 操作说明

- **添加节点**：切换到「＋ 添加节点」模式，在画布空白处点击。
- **移动节点**：「移动 / 连线」模式下直接拖拽节点（只改坐标，不改图结构）。
- **建立有向边**：把鼠标移到节点上，按住节点左上角的小方块拖到另一个节点松开。
- **标注 / 修改权重（允许负值）**：双击边上的权重标签输入；也可在邻接矩阵里点单元格编辑。
- **删除**：点击选中节点或边后按 `Delete`（或工具条删除按钮）。
- **设置源点**：右键节点，或点击邻接矩阵行首的圆点。
- **运行**：选择算法与目标节点后点「运行」，自动开始播放；支持暂停、单步、
  加速 / 减速、回到开头。跑完后目标最短路径整条高亮并显示总权重。
- **Dijkstra 与负权**：图含负权边时 Dijkstra 默认拒绝执行；可勾选
  「仍然执行」对照观察其错误结果（界面会持续提示结果不可信）。
- **负权环**：Bellman–Ford 在检测轮发现仍可松弛时，红色高亮环上节点与边、
  环及其下游节点距离标为 −∞，并报告「存在负权环，最短路不存在」。
- **动态实验**：设置源点后点「🧪 开启动态实验」。之后在画布上双击边改权、
  从节点端口拖出新边、选中边删除，或在邻接矩阵里改单元格 / 点空格建边，
  都作为一次编辑提交（不再整图重跑）。演示区播放的是**这一次的局部修复**：
  作废重算的节点（红）、距离改变的节点（蓝）、重处理但同值的节点（橙）、
  始终没被碰过的节点（灰）一眼分开；距离表显示旧值（删除线）→ 新值；
  旁栏并排给出「本次修复检查的边数 / 从头跑 Bellman–Ford 的边数」与比例。
  右侧版本列表可回看任一历史版本（只读）；点「✕ 退出实验」回到整图运行方式。
  实验中源点固定、不支持增删节点（需先退出实验）。


## 接口

- `GET /api/health` 健康检查
- `GET /api/presets` 内置示例图
- `POST /api/run` 运行算法，返回最终结果与逐步 trace（请求/响应格式保持不变）
- `POST /api/experiments` 开启动态实验（返回实验 id、版本 0 与全量初始结果）
- `POST /api/experiments/{id}/edits` 提交一次边编辑（带 `base_version` 乐观锁）
- `GET /api/experiments/{id}` 实验概览与完整版本列表
- `GET /api/experiments/{id}/versions/{v}` 取回某一版的图与距离表

```jsonc
// POST /api/run 请求
{
  "graph": {
    "nodes": [{"id": "A", "x": 80, "y": 300}],
    "edges": [{"source": "A", "target": "B", "weight": 4}]
  },
  "source": "A",
  "target": "D",                 // 可选
  "algorithm": "dijkstra",       // 或 "bellman_ford"
  "allow_negative": false        // Dijkstra 遇到负权默认拒绝
}
```

```jsonc
// POST /api/experiments 请求
{"graph": { /* 同上 */ }, "source": "A"}

// POST /api/experiments/{id}/edits 请求
{
  "base_version": 0,                       // 基于的版本号，落后会 409
  "kind": "update_weight",                 // update_weight / add_edge / delete_edge
  "source": "B", "target": "C",
  "weight": 9,                             // delete_edge 时省略
  "positions": {"A": {"x": 80, "y": 300}} // 可选，同步画布坐标，不参与计算
}
```

编辑响应（版本 0 的 `mode` 为 `initial`，`edit`/`changed` 为空）在静态
`/api/run` 字段之外额外包含：

- `version` / `current_version` / `mode`（`initial` / `incremental` / `full`）/ `reason`；
- `changed`：距离真正变化的节点，每项 `{node, before, after}`（`null` 表示 ∞/−∞ 槽位）；
- `reprocessed` / `invalidated`：本次被重新处理 / 被作废重算的节点；
- `relax_count`（本次修复检查过的边数）/ `full_relax_count`（同图从头跑 BF 的边数）；
- `steps`：本次修复的逐帧快照（先作废哪些节点、松弛了哪些边、波次扩散、负环校验）。

错误约定：版本号落后 → `409`（detail 说明当前版本，实验不变）；实验或版本不存在 →
`404`（明确「实验不存在 / 版本不存在」）；编辑引用不存在节点、新增已存在边、
删除不存在边、权重非有限数 → `400`（带原因，实验状态不变）。

实验保存在服务进程内存中（默认上限 50 个，超出按最久未访问 LRU 淘汰）。
