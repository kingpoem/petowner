"""上传图片处理：按 EXIF 自动旋转、去除 EXIF（含 GPS 定位）、限制尺寸并重新压缩；按需生成 WebP 缩略图。"""

import io
import logging
import uuid
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models
from django.db.models.fields.files import ImageFieldFile
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

MAX_PIXELS = 40_000_000  # 约 8000×5000，超出视为异常文件（防解压炸弹）
THUMB_DIR = "thumbs"


def _open(content) -> Image.Image:
    content.seek(0)
    try:
        image = Image.open(content)
        if image.width * image.height > MAX_PIXELS:
            raise ValidationError("图片分辨率过大，请压缩后再上传")
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("无法识别的图片文件") from exc
    return image


def _flatten(image: Image.Image) -> tuple[Image.Image, str]:
    """返回 (图片, 格式)：带透明通道的保存为 WebP，其余统一为 JPEG。"""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        return image.convert("RGBA"), "WEBP"
    return image.convert("RGB"), "JPEG"


def optimize(content, max_side: int, quality: int = 85) -> ContentFile:
    image = ImageOps.exif_transpose(_open(content))
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    image, fmt = _flatten(image)
    buffer = io.BytesIO()
    options = {"quality": quality, "optimize": True, "progressive": True} if fmt == "JPEG" else {"quality": quality}
    image.save(buffer, fmt, **options)  # 不传 exif，原图元数据（拍摄地点、设备）全部丢弃
    ext = "jpg" if fmt == "JPEG" else "webp"
    return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex[:16]}.{ext}")


def validate_upload(value):
    """表单校验阶段提前拦截超大或损坏的图片，避免在保存时才报错。"""
    if value and not getattr(value, "_committed", True):
        _open(value.file)


class OptimizedImageFieldFile(ImageFieldFile):
    def save(self, name, content, save=True):
        processed = optimize(content, self.field.max_side)
        directory = PurePosixPath(name).parent
        super().save(str(directory / processed.name) if str(directory) != "." else processed.name, processed, save)


class OptimizedImageField(models.ImageField):
    attr_class = OptimizedImageFieldFile
    default_validators = [*models.ImageField.default_validators, validate_upload]

    def __init__(self, *args, max_side: int = 1920, **kwargs):
        self.max_side = max_side
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.max_side != 1920:
            kwargs["max_side"] = self.max_side
        return name, path, args, kwargs


def thumbnail_name(name: str, size: int) -> str:
    return str(PurePosixPath(THUMB_DIR, str(size), name).with_suffix(".webp"))


def thumbnail_url(file, size: int) -> str:
    """返回 size×size 以内的 WebP 缩略图地址，首次访问时生成；生成失败时退回原图。"""
    if not file:
        return ""
    target = thumbnail_name(file.name, size)
    storage = file.storage
    if not storage.exists(target):
        try:
            with storage.open(file.name, "rb") as source:
                image = _open(source)
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            image, _ = _flatten(image)
            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=80, method=4)
            storage.save(target, ContentFile(buffer.getvalue()))
        except (OSError, ValidationError):
            logger.warning("缩略图生成失败：%s", file.name, exc_info=True)
            return file.url
    return storage.url(target)
