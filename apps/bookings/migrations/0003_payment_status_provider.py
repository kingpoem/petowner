from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0002_payment_partial_cancel_fee"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="provider_trade_no",
            field=models.CharField("渠道交易号", max_length=64, blank=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="status",
            field=models.CharField(
                choices=[("pending", "待确认"), ("success", "已成功"), ("failed", "已关闭")],
                default="success",
                max_length=10,
                verbose_name="状态",
            ),
        ),
        migrations.AddField(
            model_name="payment",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="更新时间"),
        ),
        migrations.AlterField(
            model_name="payment",
            name="transaction_no",
            field=models.CharField(editable=False, max_length=40, unique=True, verbose_name="商户流水号"),
        ),
    ]
