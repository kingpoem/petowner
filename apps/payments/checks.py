from django.conf import settings
from django.core.checks import Warning, register


@register()
def payment_channel_check(app_configs, **kwargs):
    if settings.PAYMENT_SANDBOX:
        return []
    missing = []
    if not (settings.WECHAT_APP_ID and settings.WECHAT_MCH_ID and settings.WECHAT_API_KEY):
        missing.append("微信支付（WECHAT_APP_ID / WECHAT_MCH_ID / WECHAT_API_KEY）")
    if not (settings.ALIPAY_APP_ID and settings.ALIPAY_PRIVATE_KEY and settings.ALIPAY_PUBLIC_KEY):
        missing.append("支付宝（ALIPAY_APP_ID / ALIPAY_PRIVATE_KEY / ALIPAY_PUBLIC_KEY）")
    if not missing:
        return []
    return [
        Warning(
            "PAYMENT_SANDBOX=false 但支付渠道密钥不完整：" + "、".join(missing),
            hint="填写渠道密钥，或将 PAYMENT_SANDBOX 设为 true 使用本站模拟收银台。",
            id="payments.W001",
        )
    ]
