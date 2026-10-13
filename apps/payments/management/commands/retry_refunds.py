from django.core.management.base import BaseCommand

from apps.payments.services import retry_pending_refunds


class Command(BaseCommand):
    help = "重试渠道退款失败（provider_trade_no 以 RETRY- 开头）的流水"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--max-retries", type=int, default=8)

    def handle(self, *args, **options):
        ok = retry_pending_refunds(limit=options["limit"], max_retries=options["max_retries"])
        self.stdout.write(self.style.SUCCESS(f"退款重试成功 {ok} 笔"))
