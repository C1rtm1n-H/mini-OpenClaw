FROM python:3.12-slim

# 系统依赖：ripgrep（grep 工具需要）、poppler-utils（PDF 提取）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# ── Agent 代码 ──
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY . .

# ── 被审计的实验代码（部署时放在 data/ 目录，与 agent 隔离）──
COPY data /data

# 默认进入交互式 REPL
CMD ["python", "-m", "agent.cli"]
