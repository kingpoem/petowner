"""RFC 6238 基于时间的一次性密码（TOTP），兼容 Google Authenticator / 微信小程序“腾讯身份验证器”等。"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
PERIOD = 30


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def match_step(secret: str, code: str, window: int = 1, now: float | None = None) -> int | None:
    """校验验证码，允许前后 window 个时间片的时钟偏差；匹配时返回时间片序号。"""
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != DIGITS:
        return None
    step = current_step(now)
    for candidate in range(step - window, step + window + 1):
        if hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}")
    query = urlencode({"secret": secret, "issuer": issuer, "digits": DIGITS, "period": PERIOD})
    return f"otpauth://totp/{label}?{query}"
