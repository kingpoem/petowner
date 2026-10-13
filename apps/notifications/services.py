import logging

from django.conf import settings

from apps.security.sms import SmsError, send_notice

from .models import Notification

logger = logging.getLogger(__name__)


def notify_owner(
    owner,
    title: str,
    body: str = "",
    link: str = "",
    level: str = Notification.Level.INFO,
    *,
    sms_event: str = "",
):
    """给已开通线上账号的宠物主人发送站内通知；可选同步业务短信。

    sms_event 取值：care / health，需在 SMS_NOTIFY_EVENTS 中启用。
    """
    note = None
    if owner.user_id is not None:
        note = Notification.objects.create(user_id=owner.user_id, title=title, body=body, link=link, level=level)
    if sms_event and sms_event in settings.SMS_NOTIFY_EVENTS and owner.phone:
        try:
            send_notice(owner.phone, f"{title}：{body}" if body else title)
        except SmsError:
            logger.exception("业务短信发送失败：%s %s", owner.phone, sms_event)
    return note
