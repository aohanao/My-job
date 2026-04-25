# 使用官方 Python 3.10 镜像，推荐使用 slim 减少体积
FROM python:3.10-slim

# 设置工作区
WORKDIR /app

# 安装必要的系统级依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖列表并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 将整个当前文件夹内容复制进容器
COPY . .

# 暴露 Streamlit Web 端口
EXPOSE 8501

# 设置 Streamlit 配置，使其能被外部访问
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

# 配置执行入口：启动 Streamlit
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
