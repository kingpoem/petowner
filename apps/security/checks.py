from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security, deploy=True)
def check_security_settings(app_configs, **kwargs):
    issues = []
    if settings.SMS_BACKEND == "console":
        issues.append(
            Warning(
                "短信使用控制台通道，用户收不到注册与找回密码验证码。",
                hint="设置 SMS_BACKEND=aliyun 并填写 SMS_ACCESS_KEY_ID 等配置。",
                id="security.W001",
            )
        )
    elif settings.SMS_BACKEND == "aliyun" and not all(
        (settings.SMS_ACCESS_KEY_ID, settings.SMS_ACCESS_KEY_SECRET, settings.SMS_SIGN_NAME, settings.SMS_TEMPLATE_CODE)
    ):
        issues.append(Warning("阿里云短信配置不完整。", hint="检查 SMS_* 配置项。", id="security.W002"))
    return issues
