# 最短路径算法教学看板（Shortest Path Teaching Board）

一个前后端一体的 Web 应用，用于在**带权有向图**上把「单源最短路径」讲透：

- **Dijkstra**：只适用于非负权图，基于优先队列逐个「确定」节点最短距离。
- **Bellman–Ford**：允许负权边，按轮次松弛所有边，并能识别从源点可达的**负权环**。

两种算法在**同一张图**上逐步演示松弛过程，方便对照执行差异与适用边界。
全部算法与正确性校验都在后端（Python 3.12 + FastAPI）完成，前端（React + TypeScript + Vite）
只负责渲染逐步返回的中间状态快照，不自行重算。

此外提供一层**动态实验**：开实验后，每次改一条边（调权 / 加边 / 删边 / 加删节点）
都作为一次带版本号的「编辑」提交，后端**在上一版结果上做增量修复**，只把受影响的
一片距离修回来，并逐帧演示「修了哪里、为什么只修这里」，同时并排给出
「本次松弛次数 / 同图从头跑 Bellman–Ford 的松弛次数」。增量修复在**负权边**下
同样保证正确；编辑造出源点可达的负权环时如实报告，环被打破时允许退回全量重算
（响应中明确标注本次走的是全量及原因）。

## 目录结构

```
backend/                # FastAPI 后端（算法全部在这里）
  app/
    main.py             # HTTP 接口 / 静态资源挂载
    models.py           # 请求/响应 Pydantic 模型
    graph.py            # 带权有向图模型 + 输入校验
    dijkstra.py         # Dijkstra（含逐步 trace、优先队列快照）
    bellman_ford.py     # Bellman–Ford（含逐轮 trace）
    negative_cycle.py   # 负权环检测（前驱链回溯成环）
    path.py             # 最短路径回溯
    presets.py          # 内置经典示例图
    dynamic/            # 动态实验：增量修复 + 实验/版本管理（独立成包）
      edits.py          #   编辑（改权/加边/删边/加删节点）的语义校验与应用
      repair.py         #   在上一版结果上做局部增量修复（负权下同样正确）
      fullrun.py        #   全量基准：从头跑 Bellman–Ford，用于初始/对照计数
      experiment.py     #   实验、完整版本历史与 LRU 淘汰（纯内存）
      schemas.py        #   动态实验请求/响应模型
  tests/                # pytest 自动化测试（含动态实验验收用例与随机压测）
frontend/               # React + TS + Vite 前端
  src/components/
    GraphCanvas.tsx     # 图编辑画布（SVG）
    AdjacencyMatrix.tsx # 邻接矩阵（与图实时双向同步）
    DistanceTable.tsx   # 距离表 + 优先队列/轮次信息
    DemoControls.tsx    # 运行/暂停/单步/变速控制
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

动态实验对应 `tests/test_dynamic_*.py`：
非树边/不可达边改动零变化、树上调大只动子树、30 节点单链只重算链尾且
松弛次数 ≤ 全量 1/10、落后版本 409 且状态不变、负权环造出与打破（打破标全量）、
历史版本取回一致、LRU 淘汰与 404；以及在多张随机图（含负权边、不可达节点、
加删节点）上各做 200+ 次随机编辑，每次结果都与在当前图从头跑 Bellman–Ford
完全一致、前驱链合法。

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

### 动态实验（增量修复）

- 侧栏点「🧪 对当前图开实验」（需先设置源点），后端返回实验编号、版本 0 与
  一份完整的初始 Bellman–Ford 结果。
- 开实验后，**双击边改权重、邻接矩阵改单元格、从节点拖出新边、删除边 / 节点**
  都作为一次编辑提交给实验（移动节点只改坐标，不触发计算），不再整图重跑。
- 演示区播放**这一次的修复过程**：被作废后重新计算的节点（紫）、被重新处理过
  的节点（蓝）、始终没被碰过的节点（暗）一眼分开；距离表里真正变化的格子显示
  `旧值 → 新值`；旁边并排给出 **本次松弛次数 / 同图全量 BF 次数**。
  - 调大 / 删除一条**不在最短路径树上**的边、改动**源点不可达区域**的边：
    变化清单为空、被重新处理的节点集合为空、松弛次数为 0。
  - 调大一条**树上的边**：只作废该边终点在树上的整棵子树，子树外一个节点都不碰。
  - 调小一条边 / 新增边：改进沿出边向外扩散，松弛不再带来改进处即停止。
- 编辑造出**源点可达的负权环**时，环上节点与边、受污染下游距离（−∞）如实报告，
  实验进入「含负权环」状态；之后的编辑会**全量重算**（响应 `mode="full"` 且
  `reason` 说明原因）；把环打破后距离恢复为有限值、状态回到正常。
- **版本列表**可回看任一历史版本的图与距离表（只读）；**退出实验**后看板回到
  原来「点运行整图重算」的方式。
- 实验保存在服务进程内存中，数量有上限（默认 50），超出淘汰最久未访问者；
  访问已淘汰 / 不存在的实验返回明确的 404「实验不存在」。


## 接口

- `GET /api/health` 健康检查
- `GET /api/presets` 内置示例图
- `POST /api/run` 运行算法，返回最终结果与逐步 trace

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

### 动态实验接口（原有 `/api/run` 请求/响应格式保持不变）

- `POST /api/experiments`：开实验，body 同图结构 + `source`；返回
  `{experiment_id, version: 0, result}`，`result` 是完整初始结果。
- `POST /api/experiments/{id}/edits`：提交一次编辑（必须带 `base_version`），
  返回新版本结果：`version`、`mode`（`incremental` / `full`）、`reason`、
  新 `dist` / `pred` / `graph`、`changed`（每个变化节点带 `old`→`new`）、
  `reprocessed`、逐步 `steps`、`incremental_relax_count` 与
  `full_relax_count`、`has_negative_cycle` / `cycle` / `affected`。
  - `base_version` 落后 → **409** 且实验状态不变；
  - 引用不存在的节点 / 删除不存在的边 / 新增已存在的边 → **400** 带原因；
  - 实验不存在 / 已淘汰 → **404**「实验不存在」。
- `GET /api/experiments/{id}`：实验元信息与版本号列表。
- `GET /api/experiments/{id}/versions/{v}`：取回任一历史版本的图与结果。
- `DELETE /api/experiments/{id}`：退出 / 清理实验。

```jsonc
// POST /api/experiments/{id}/edits 请求
{ "kind": "set_weight", "base_version": 3, "source": "A", "target": "B", "weight": 9 }
// kind 还可以是 add_edge / delete_edge / add_node / delete_node
```
