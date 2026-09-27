# syntax=docker/dockerfile:1

# ---------- 阶段 1：构建前端 ----------
FROM node:20-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：后端 + 前端产物 ----------
FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SERVE_FRONTEND=1

WORKDIR /app

# 先装依赖，利用层缓存
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 后端代码
COPY backend/ ./

# 前端构建产物（FastAPI 在根路由托管 dist）
COPY --from=frontend /build/frontend/dist ../frontend/dist

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
