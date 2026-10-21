from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.images import OptimizedImageField


class Species(models.TextChoices):
    DOG = "dog", "狗"
    CAT = "cat", "猫"
    OTHER = "other", "其他"


class PetSize(models.IntegerChoices):
    SMALL = 1, "小型（<10kg）"
    MEDIUM = 2, "中型（10-25kg）"
    LARGE = 3, "大型（>25kg）"

    @classmethod
    def from_weight(cls, weight) -> "PetSize":
        if weight is None or weight < 10:
            return cls.SMALL
        return cls.MEDIUM if weight <= 25 else cls.LARGE


class Owner(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="线上账号",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owner_profile",
    )
    name = models.CharField("主人姓名", max_length=50)
    phone = models.CharField("联系方式", max_length=20, unique=True)
    email = models.EmailField("邮箱", blank=True)
    address = models.CharField("地址", max_length=200, blank=True)
    emergency_contact = models.CharField("紧急联系人", max_length=50, blank=True)
    emergency_phone = models.CharField("紧急联系电话", max_length=20, blank=True)
    avatar = OptimizedImageField("头像", upload_to="avatars/%Y/%m/", blank=True, max_side=640)
    created_at = models.DateTimeField("登记时间", auto_now_add=True)

    class Meta:
        verbose_name = "主人信息"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name}（{self.phone}）"


class Pet(models.Model):
    class Gender(models.TextChoices):
        MALE = "male", "公"
        FEMALE = "female", "母"
        UNKNOWN = "unknown", "未知"

    class Temperament(models.TextChoices):
        GENTLE = "gentle", "温顺"
        ACTIVE = "active", "活泼"
        TIMID = "timid", "胆小"
        AGGRESSIVE = "aggressive", "有攻击性"

    code = models.CharField("宠物编号", max_length=20, unique=True, blank=True, editable=False)
    name = models.CharField("宠物名称", max_length=50)
    photo = OptimizedImageField("照片", upload_to="pets/%Y/%m/", blank=True, max_side=1280)
    species = models.CharField("宠物类型", max_length=10, choices=Species, default=Species.DOG)
    breed = models.CharField("品种", max_length=50)
    age = models.PositiveSmallIntegerField("年龄（岁）", default=0)
    gender = models.CharField("性别", max_length=10, choices=Gender, default=Gender.UNKNOWN)
    weight = models.DecimalField(
        "体重（kg）", max_digits=5, decimal_places=1, default=Decimal("5.0"), validators=[MinValueValidator(0)]
    )
    sterilized = models.BooleanField("已绝育", default=False)
    temperament = models.CharField("性格", max_length=20, choices=Temperament, default=Temperament.GENTLE)
    health_status = models.CharField("健康情况", max_length=200, default="健康")
    diet_notes = models.CharField(
        "饮食习惯",
        max_length=300,
        blank=True,
        help_text="可选。如：每日两餐每餐 150g 狗粮；对鸡肉过敏",
    )
    owner = models.ForeignKey(Owner, verbose_name="主人", on_delete=models.PROTECT, related_name="pets")
    created_at = models.DateTimeField("建档时间", auto_now_add=True)

    class Meta:
        verbose_name = "宠物档案"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} {self.name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.code:
            self.code = f"P{self.pk:05d}"
            Pet.objects.filter(pk=self.pk).update(code=self.code)

    @property
    def size(self) -> PetSize:
        return PetSize.from_weight(self.weight)
