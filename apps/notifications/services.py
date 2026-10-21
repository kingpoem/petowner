import logging

from django.conf import settings

from apps.security.sms import SmsError, send_notice

logger = logging.getLogger(__name__)


def notify_owner(
    owner,
    title: str,
    body: str = "",
    link: str = "",
    level: str = "info",
    *,
    sms_event: str = "",
):
    """可选业务短信提醒（不再写入站内通知）。

    sms_event 取值：care / health，需在 SMS_NOTIFY_EVENTS 中启用。
    """
    del link, level  # 兼容旧调用签名
    if sms_event and sms_event in settings.SMS_NOTIFY_EVENTS and owner.phone:
        try:
            send_notice(owner.phone, f"{title}：{body}" if body else title)
        except SmsError:
            logger.exception("业务短信发送失败：%s %s", owner.phone, sms_event)
