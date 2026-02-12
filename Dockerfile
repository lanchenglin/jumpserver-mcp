# 任意环境 clone 后可直接 docker build，仅依赖仓库内文件，不依赖本地 lockfile 或本地命令
FROM ghcr.io/astral-sh/uv:python3.11-alpine

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# 仅用仓库内 pyproject.toml 解析并安装依赖（不依赖 uv.lock，保证任意环境可构建）
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev --no-editable

# 拷贝完整源码并安装项目（始终按 pyproject.toml 解析，与仓库是否含 uv.lock 无关）
COPY . ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uv", "run", "main.py"]