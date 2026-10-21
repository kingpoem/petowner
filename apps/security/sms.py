"""短信验证码：发送限流、校验次数限制，以及可切换的短信通道（控制台 / 阿里云短信）。"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import UTC, datetime
from urllib.parse import quote, urlencode
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache
from django.utils.crypto import salted_hmac

logger = logging.getLogger(__name__)

PURPOSES = {"register": "注册账号", "reset": "找回密码"}
CODE_TTL = 300
RESEND_SECONDS = 60
MAX_PER_PHONE_DAY = 10
MAX_PER_IP_HOUR = 20
MAX_ATTEMPTS = 5


class SmsError(Exception):
    pass


def _hash(phone: str, purpose: str, code: str) -> str:
    return salted_hmac("sms-code", f"{purpose}:{phone}:{code}").hexdigest()


def _bump(key: str, timeout: int) -> int:
    cache.add(key, 0, timeout)
    return cache.incr(key)


def cooldown_left(phone: str, purpose: str) -> int:
    sent_at = cache.get(f"sms:sent:{purpose}:{phone}")
    if sent_at is None:
        return 0
    return max(0, RESEND_SECONDS - int(datetime.now(UTC).timestamp() - sent_at))


def issue_code(phone: str, purpose: str, ip: str = "") -> str:
    """生成并发送验证码；超出频率限制时抛出 SmsError。"""
    if purpose not in PURPOSES:
        raise SmsError("不支持的验证码用途")
    if wait := cooldown_left(phone, purpose):
        raise SmsError(f"发送太频繁，请 {wait} 秒后再试")
    if (cache.get(f"sms:day:{phone}") or 0) >= MAX_PER_PHONE_DAY:
        raise SmsError("该手机号今日获取验证码次数已达上限")
    if ip and (cache.get(f"sms:ip:{ip}") or 0) >= MAX_PER_IP_HOUR:
        raise SmsError("当前网络请求过于频繁，请稍后再试")
    code = f"{secrets.randbelow(10**6):06d}"
    send(phone, code)
    cache.set(f"sms:code:{purpose}:{phone}", {"hash": _hash(phone, purpose, code), "attempts": 0}, CODE_TTL)
    cache.set(f"sms:sent:{purpose}:{phone}", datetime.now(UTC).timestamp(), RESEND_SECONDS)
    _bump(f"sms:day:{phone}", 86400)
    if ip:
        _bump(f"sms:ip:{ip}", 3600)
    return code


def verify_code(phone: str, purpose: str, code: str) -> bool:
    """校验验证码，成功后立即作废；连续错误 MAX_ATTEMPTS 次后需重新获取。"""
    key = f"sms:code:{purpose}:{phone}"
    entry = cache.get(key)
    if not entry or entry["attempts"] >= MAX_ATTEMPTS:
        return False
    if hmac.compare_digest(entry["hash"], _hash(phone, purpose, (code or "").strip())):
        cache.delete(key)
        return True
    entry["attempts"] += 1
    cache.set(key, entry, CODE_TTL)
    return False


# ---------- 短信通道 ----------


def send(phone: str, code: str):
    backend = settings.SMS_BACKEND
    if backend == "console":
        logger.warning("【短信验证码】%s -> %s（控制台通道，未真实发送）", phone, code)
    elif backend == "aliyun":
        _send_aliyun(phone, {"code": code})
    else:
        raise SmsError(f"未知的短信通道：{backend}")


def send_notice(phone: str, content: str):
    """业务触达短信（护理动态、健康异常）。模板变量为 ${content}。"""
    text = (content or "")[:60]
    backend = settings.SMS_BACKEND
    template = settings.SMS_NOTIFY_TEMPLATE_CODE or settings.SMS_TEMPLATE_CODE
    if backend == "console":
        logger.warning("【业务短信】%s -> %s（控制台通道，未真实发送）", phone, text)
        return
    if backend == "aliyun":
        if not template:
            raise SmsError("未配置 SMS_NOTIFY_TEMPLATE_CODE")
        _send_aliyun(phone, {"content": text}, template_code=template)
        return
    raise SmsError(f"未知的短信通道：{backend}")


def _percent(value: str) -> str:
    return quote(value, safe="~")


def aliyun_signed_query(params: dict, secret: str) -> str:
    """阿里云 RPC 风格 API 签名（HMAC-SHA1，SignatureVersion 1.0）。"""
    canonical = "&".join(f"{_percent(k)}={_percent(str(v))}" for k, v in sorted(params.items()))
    string_to_sign = f"GET&{_percent('/')}&{_percent(canonical)}"
    digest = hmac.new(f"{secret}&".encode(), string_to_sign.encode(), hashlib.sha1).digest()
    return urlencode({**params, "Signature": base64.b64encode(digest).decode()})


def _send_aliyun(phone: str, template_params: dict, template_code: str | None = None):
    params = {
        "AccessKeyId": settings.SMS_ACCESS_KEY_ID,
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": phone,
        "RegionId": "cn-hangzhou",
        "SignName": settings.SMS_SIGN_NAME,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "TemplateCode": template_code or settings.SMS_TEMPLATE_CODE,
        "TemplateParam": json.dumps(template_params, ensure_ascii=False),
        "Timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2017-05-25",
    }
    url = "https://dysmsapi.aliyuncs.com/?" + aliyun_signed_query(params, settings.SMS_ACCESS_KEY_SECRET)
    try:
        with urlopen(url, timeout=8) as resp:  # noqa: S310 - 固定的 https 地址
            result = json.load(resp)
    except OSError as exc:
        logger.exception("短信发送失败：%s", phone)
        raise SmsError("短信服务暂时不可用，请稍后再试") from exc
    if result.get("Code") != "OK":
        logger.error("短信发送失败：%s %s", phone, result)
        raise SmsError("短信发送失败，请稍后再试")
