HOST ?= 127.0.0.1
PORT ?= 8000
MANAGE = uv run python manage.py
COMPOSE = docker compose

export PYTHONUTF8 := 1

.DEFAULT_GOAL := help
.PHONY: help install env initdb makemigrations migrate setup run seed reset-demo superuser expire test lint format check \
	deploy-check launch-accept collectstatic images shell clean docker-build docker-up docker-down docker-logs docker-seed docker-backup

help: ## 显示所有命令
	@uv run python scripts/make_help.py

# ---------- 本地开发 ----------

install: ## 安装/同步依赖（uv sync）
	uv sync

env: ## 若 .env 不存在则从 .env.example 复制
	@uv run python -c "import pathlib, shutil; p = pathlib.Path('.env'); p.exists() or shutil.copy('.env.example', p)"

initdb: env ## 创建 MySQL 数据库（已存在则跳过）
	$(MANAGE) initdb

makemigrations: initdb ## 根据模型变更生成迁移文件
	$(MANAGE) makemigrations

migrate: initdb ## 执行数据库迁移并创建缓存表
	$(MANAGE) migrate
	$(MANAGE) createcachetable

setup: install migrate ## 一键初始化：依赖 + 建库 + 迁移

run: setup ## 一键启动开发服务器（默认 http://127.0.0.1:8000）
	$(MANAGE) runserver $(HOST):$(PORT)

seed: setup ## 写入演示数据（管理员 admin/admin123，顾客 13800000001/pawstay123）
	$(MANAGE) seed_demo

reset-demo: setup ## 清空数据库与上传文件后重新写入演示数据
	$(MANAGE) flush --noinput
	@uv run python -c "import shutil; shutil.rmtree('media', ignore_errors=True)"
	$(MANAGE) seed_demo

superuser: ## 交互式创建管理员账号
	$(MANAGE) createsuperuser

expire: ## 取消超时未支付订单并处理候补（生产环境由 scheduler 每 5 分钟执行）
	$(MANAGE) expire_orders

images: ## 按 scripts/fetch_images.py 中的清单下载授权图片
	uv run python scripts/fetch_images.py download

# ---------- 质量 ----------

test: install env ## 运行全部单元测试（自动创建/销毁 test_petowner 库）
	$(MANAGE) test apps --noinput

lint: ## 代码检查（ruff）
	uv run ruff check .
	uv run ruff format --check .

format: ## 代码格式化（ruff）
	uv run ruff format .
	uv run ruff check . --fix

check: initdb ## Django 系统检查 + 迁移缺失检查
	$(MANAGE) check
	$(MANAGE) makemigrations --check --dry-run

deploy-check: ## 以生产配置运行 Django 部署安全检查
	uv run python scripts/deploy_check.py

launch-accept: ## 上线路由与关键配置验收（见 docs/LAUNCH.md）
	uv run python scripts/launch_accept.py

collectstatic: ## 收集静态文件到 staticfiles/
	$(MANAGE) collectstatic --noinput

shell: ## 进入 Django shell
	$(MANAGE) shell

clean: ## 清理 __pycache__ 与 staticfiles
	@uv run python -c "import pathlib, shutil; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__') if '.venv' not in p.parts]; shutil.rmtree('staticfiles', ignore_errors=True)"

# ---------- Docker 生产部署 ----------

docker-build: ## 构建生产镜像
	$(COMPOSE) build

docker-up: ## 启动 MySQL + Web + 定时任务 + Nginx
	$(COMPOSE) up -d --build

docker-down: ## 停止全部容器（数据卷保留）
	$(COMPOSE) down

docker-logs: ## 跟踪容器日志
	$(COMPOSE) logs -f --tail=100

docker-seed: ## 在容器中写入演示数据
	$(COMPOSE) exec web python manage.py seed_demo

docker-backup: ## 立即备份数据库与上传文件到 backups/（平时每天自动备份）
	$(COMPOSE) exec backup bash /backup.sh once
