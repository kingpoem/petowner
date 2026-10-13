# 本地运行说明

本机安装 MySQL，用 uv 启动。不使用 Docker。

Windows（已安装 uv，MySQL 解压在 `C:\Users\17193\mysql-8.4.9-winx64`，可用环境变量 `MYSQL_HOME` 改路径）：

```bash
uv sync
uv run python scripts/dev.py seed
uv run python scripts/dev.py run
```

`seed` 会在 3307 未监听时启动本机 MySQL（root 空密码，只绑定 127.0.0.1），然后建库、迁移并写入演示数据。本机 3306 已被另一个 MySQL 占用，所以这个项目使用 3307。

已安装 GNU Make 时也可以：

```bash
make seed
make run    # http://127.0.0.1:8000/
make test
```

演示账号：

| 角色 | 入口 | 账号 / 密码 |
| --- | --- | --- |
| 管理员 | `/admin/` | `admin` / `admin123` |
| 顾客 | `/account/login/` | `13800000001` / `pawstay123` |

更多说明见项目根目录 [README.md](../README.md)。
