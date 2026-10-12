from django.core.management.base import BaseCommand

from apps.bookings.models import expire_unpaid_orders, process_waitlist
from apps.payments.services import retry_pending_refunds


class Command(BaseCommand):
    help = "取消超时未支付订单、处理候补，并重试失败的渠道退款（建议每 5 分钟执行一次）"

    def handle(self, *args, **options):
        expired = expire_unpaid_orders()
        notified = process_waitlist()
        refunded = retry_pending_refunds()
        self.stdout.write(f"已取消超时订单 {expired} 笔，候补通知 {notified} 条，退款重试成功 {refunded} 笔")
