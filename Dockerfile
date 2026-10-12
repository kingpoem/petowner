# 国内服务器构建可指定 Debian 镜像源，如 APT_MIRROR=mirrors.aliyun.com
# 使用 PyMySQL，构建阶段无需 apt 安装编译工具，避开镜像源断连问题
ARG APT_MIRROR=""

# ---- 构建依赖 ----
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- 运行镜像 ----
FROM python:3.13-slim
ARG APT_MIRROR
RUN useradd --create-home --uid 1000 app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    DJANGO_MEDIA_ROOT=/data/media
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY . .
RUN DJANGO_DEBUG=false DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput \
    && mkdir -p /data/media \
    && chown -R app:app /app /data \
    && sed -i "s/\r$//" deploy/*.sh \
    && chmod +x deploy/entrypoint.sh deploy/backup.sh
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
ENTRYPOINT ["deploy/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
