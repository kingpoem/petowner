import MySQLdb
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "若不存在则创建 MySQL 数据库（utf8mb4）"
    requires_system_checks = []

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        try:
            conn = MySQLdb.connect(
                host=db["HOST"], port=int(db["PORT"]), user=db["USER"], password=db["PASSWORD"], charset="utf8mb4"
            )
        except MySQLdb.OperationalError as exc:
            raise CommandError(
                f"无法连接 MySQL（{db['HOST']}:{db['PORT']}），请确认服务已启动且 .env 配置正确：{exc}"
            ) from exc
        with conn:
            conn.cursor().execute(
                f"CREATE DATABASE IF NOT EXISTS `{db['NAME']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        self.stdout.write(self.style.SUCCESS(f"数据库 {db['NAME']} 已就绪"))
