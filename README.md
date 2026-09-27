# 最短路径算法教学看板（Shortest Path Teaching Board）

一个前后端一体的 Web 应用，用于在**带权有向图**上把「单源最短路径」讲透：

- **Dijkstra**：只适用于非负权图，基于优先队列逐个「确定」节点最短距离。
- **Bellman–Ford**：允许负权边，按轮次松弛所有边，并能识别从源点可达的**负权环**。

两种算法在**同一张图**上逐步演示松弛过程，方便对照执行差异与适用边界。
全部算法与正确性校验都在后端（Python 3.12 + FastAPI）完成，前端（React + TypeScript + Vite）
只负责渲染逐步返回的中间状态快照，不自行重算。

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
  tests/                # pytest 自动化测试
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
