"""本机启动入口：MySQL 装在本机，不使用 Docker。

用法（在项目根目录）：
    uv run python scripts/dev.py mysql
    uv run python scripts/dev.py seed
    uv run python scripts/dev.py run
    uv run python scripts/dev.py test
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MYSQL_HOME = Path(os.environ.get("MYSQL_HOME", r"C:\Users\17193\mysql-8.4.9-winx64"))
HOST = "127.0.0.1"
PORT = 3307


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((HOST, port)) == 0


def _mysqld(*args: str) -> list[str]:
    binary = MYSQL_HOME / "bin" / "mysqld.exe"
    if not binary.exists():
        raise SystemExit(f"找不到 {binary}。请先完成本机 MySQL 解压，或设置 MYSQL_HOME。")
    config = MYSQL_HOME / "my.ini"
    return [str(binary), f"--defaults-file={config}", *args]


def ensure_mysql():
    if _port_open(PORT):
        print(f"MySQL 已在 {HOST}:{PORT} 监听")
        return
    data = MYSQL_HOME / "data"
    if not (data / "mysql").exists():
        print("正在初始化 MySQL 数据目录（root 空密码，仅监听本机）...")
        subprocess.check_call(_mysqld("--initialize-insecure", "--console"))
    print("正在启动 MySQL...")
    subprocess.Popen(
        _mysqld(),
        cwd=str(MYSQL_HOME),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    for _ in range(40):
        if _port_open(PORT):
            print(f"MySQL 已启动：{HOST}:{PORT}")
            return
        time.sleep(0.5)
    raise SystemExit("MySQL 启动超时。请查看数据目录里的错误日志。")


def ensure_env():
    target = ROOT / ".env"
    if target.exists():
        return
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    example = example.replace("DJANGO_DEBUG=true", "DJANGO_DEBUG=true")
    example = example.replace("DJANGO_SECURE_SSL_REDIRECT=true", "DJANGO_SECURE_SSL_REDIRECT=false")
    example = example.replace("MYSQL_PORT=3306", "MYSQL_PORT=3307")
    if "DJANGO_SECRET_KEY=\n" in example or example.endswith("DJANGO_SECRET_KEY="):
        example = example.replace("DJANGO_SECRET_KEY=", "DJANGO_SECRET_KEY=dev-only-change-me", 1)
    target.write_text(example, encoding="utf-8")
    print("已生成 .env（调试模式，关闭 HTTPS 跳转，MySQL root 空密码）")


def manage(*args: str):
    subprocess.check_call([sys.executable, "manage.py", *args], cwd=ROOT)


def seed():
    ensure_env()
    ensure_mysql()
    manage("initdb")
    manage("migrate")
    manage("createcachetable")
    manage("seed_demo")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "mysql":
        ensure_mysql()
    elif command == "seed":
        seed()
    elif command == "run":
        ensure_env()
        ensure_mysql()
        manage("runserver", "127.0.0.1:8000")
    elif command == "test":
        ensure_env()
        ensure_mysql()
        manage("test", "apps", "--noinput")
    else:
        raise SystemExit("用法: dev.py [mysql|seed|run|test]")


if __name__ == "__main__":
    main()
