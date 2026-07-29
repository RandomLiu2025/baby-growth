FROM python:3.12-slim

WORKDIR /app

# 系统依赖：ffmpeg 用于上传视频时自动截取封面帧（缺失时会自动降级，不影响其它功能）
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 依赖
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

# 代码
COPY server/ server/
COPY client/ client/

WORKDIR /app/server
ENV CLIENT_DIR=/app/client \
    DATABASE_URL=sqlite:///./data/baby.db \
    UPLOAD_DIR=./data/uploads

EXPOSE 8000

# 首次启动自动建表并创建管理员；如需示例数据可执行： docker compose exec app python seed.py
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
