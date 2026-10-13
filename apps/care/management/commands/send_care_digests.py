from datetime import date

from django.core.management.base import BaseCommand

from apps.care.digest import send_care_digests


class Command(BaseCommand):
    help = "向在住订单主人推送当日护理日报（建议每天晚上执行）"

    def add_arguments(self, parser):
        parser.add_argument("--date", help="YYYY-MM-DD，默认今天")

    def handle(self, *args, **options):
        day = date.fromisoformat(options["date"]) if options.get("date") else None
        n = send_care_digests(day)
        self.stdout.write(self.style.SUCCESS(f"已推送护理日报 {n} 份"))
