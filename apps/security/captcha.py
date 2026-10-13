"""图形验证码：答案存于 session，一次有效，5 分钟过期。"""

import io
import random
import secrets
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SESSION_KEY = "captcha"
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 去掉易混淆的 0/O、1/I
LENGTH = 4
TTL_SECONDS = 300
SIZE = (120, 44)


def issue(request) -> str:
    text = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    request.session[SESSION_KEY] = {"text": text, "expires": time.time() + TTL_SECONDS}
    return text


def verify(request, answer: str) -> bool:
    stored = request.session.pop(SESSION_KEY, None)
    if not stored or stored["expires"] < time.time():
        return False
    return secrets.compare_digest(stored["text"], (answer or "").strip().upper())


def render_png(text: str) -> bytes:
    rnd = random.Random(secrets.randbits(64))
    width, height = SIZE
    image = Image.new("RGB", SIZE, (255, 246, 240))
    draw = ImageDraw.Draw(image)
    for _ in range(6):
        points = [(rnd.randint(0, width), rnd.randint(0, height)) for _ in range(2)]
        draw.line(points, fill=(rnd.randint(200, 235), rnd.randint(170, 210), rnd.randint(150, 200)), width=1)
    font = ImageFont.load_default(size=28)
    step = (width - 16) / LENGTH
    for i, char in enumerate(text):
        glyph = Image.new("RGBA", (34, 40), (0, 0, 0, 0))
        color = (rnd.randint(150, 230), rnd.randint(60, 110), rnd.randint(30, 80), 255)
        ImageDraw.Draw(glyph).text((5, 2), char, font=font, fill=color)
        glyph = glyph.rotate(rnd.uniform(-25, 25), resample=Image.Resampling.BICUBIC, expand=False)
        image.paste(glyph, (int(8 + i * step + rnd.uniform(-2, 2)), rnd.randint(0, 6)), glyph)
    for _ in range(80):
        draw.point((rnd.randint(0, width - 1), rnd.randint(0, height - 1)), fill=(rnd.randint(150, 220),) * 3)
    image = image.filter(ImageFilter.SMOOTH)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
